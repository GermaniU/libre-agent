"""Backend puente para LocalAgent: expone el loop del agente vía HTTP.

No reemplaza la lógica del agente: delega todo en agent.py, clients.py, store.py,
memory.py, trace.py, etc. Sólo añade una capa HTTP + un frontend estático.
"""
import json
import os
import re
import time
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import agent
import clients
import config
import mcp_bridge
import skills
import store

_DIR = os.path.dirname(os.path.abspath(__file__))
_WEB_DIR = os.path.join(_DIR, "web")
_STATIC_DIR = os.path.join(_DIR, "static")

app = FastAPI(title="LocalAgent API", version="0.1.0")

# El frontend se sirve desde el mismo origen; CORS solo para orígenes locales
# (con "*" cualquier página abierta en el navegador podría leer /api/sessions).
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


def _soul():
    """Carga soul.md con fallback idéntico al de app.py."""
    try:
        with open(os.path.join(_DIR, "soul.md"), encoding="utf-8") as f:
            return f.read()
    except Exception:
        return (
            "Sos un asistente con tools. Usá web_search/web_fetch para info externa, "
            "vault_search para las notas del usuario y write_html si pide un documento. "
            "Respondé en español. Atendé SOLO el último mensaje; nunca repitas búsquedas "
            "de temas anteriores."
        )


# ---------------------------------------------------------------- modelos
class ChatRequest(BaseModel):
    session: str
    message: str
    model: str
    temperature: float = 0.4
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    num_ctx: Optional[int] = None
    system: Optional[str] = None  # override del soul.md para esta sesión
    use_tools: bool = True
    think: Optional[bool] = None
    use_memory: bool = True
    mcp_servers: List[str] = Field(default_factory=list)


class SaveSessionRequest(BaseModel):
    data: dict


class RenameRequest(BaseModel):
    new: str


class SoulUpdate(BaseModel):
    content: str


# ---------------------------------------------------------------- API
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/models")
def list_models():
    """Modelos de chat/visión disponibles en Ollama, con indicador de VRAM."""
    try:
        models = clients.list_local_models()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama no responde: {e}")
    chat_models = [m for m in models if m["kind"] in ("chat", "vision")]
    return {"models": chat_models, "default": config.DEFAULT_MODEL}


@app.get("/api/sessions")
def load_sessions():
    return store.load_sessions()


@app.post("/api/sessions/{name}")
def save_session(name: str, req: SaveSessionRequest):
    store.save_session(name, req.data)
    return {"ok": True}


@app.delete("/api/sessions/{name}")
def delete_session(name: str):
    store.delete_session(name)
    return {"ok": True}


@app.post("/api/sessions/{old}/rename")
def rename_session(old: str, req: RenameRequest):
    new = req.new.strip()
    if not new:
        raise HTTPException(status_code=400, detail="new name required")
    if not store.rename_session(old, new):
        raise HTTPException(status_code=409, detail=f"Ya existe una sesión llamada '{new}'")
    return {"ok": True, "name": new}


class McpAdd(BaseModel):
    name: str
    target: str  # URL http(s) -> server http; cualquier otra cosa -> comando stdio


class McpEdit(BaseModel):
    target: str


def _mcp_cfg():
    try:
        with open(mcp_bridge.CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    cfg.setdefault("mcpServers", {})
    return cfg


def _mcp_save(cfg):
    with open(mcp_bridge.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _mcp_server_from_target(target):
    """Traduce un 'target' (URL http o 'comando args…') a un dict de config MCP."""
    if re.match(r"^https?://", target):
        return {"type": "http", "url": target}
    parts = target.split()
    return {"command": parts[0], "args": parts[1:]}


def _mcp_target_of(s):
    """Deriva el 'target' legible de un dict de config (para mostrar/editar)."""
    if s.get("type") == "http" or "url" in s:
        return s.get("url", "")
    return " ".join([s.get("command", "")] + s.get("args", [])).strip()


def _mcp_view(cfg):
    """Lista pública de servers: nombre + tipo + target + env (sin valores de env)."""
    out = []
    for name, s in cfg["mcpServers"].items():
        is_http = s.get("type") == "http" or "url" in s
        out.append({
            "name": name,
            "type": "http" if is_http else "stdio",
            "target": _mcp_target_of(s),
            "env_keys": sorted((s.get("env") or {}).keys()),  # solo claves, nunca valores
        })
    return out


@app.get("/api/mcps")
def list_mcps():
    cfg = _mcp_cfg()
    return {"servers": list(cfg["mcpServers"].keys()), "configs": _mcp_view(cfg)}


@app.post("/api/mcps")
def add_mcp(req: McpAdd):
    name = req.name.strip()
    target = req.target.strip()
    if not re.match(r"^[a-zA-Z0-9_-]{1,60}$", name):
        raise HTTPException(status_code=400, detail="Nombre inválido: usá letras, números, - o _")
    if not target:
        raise HTTPException(status_code=400, detail="Falta la URL o el comando")
    cfg = _mcp_cfg()
    if name in cfg["mcpServers"]:
        raise HTTPException(status_code=409, detail=f"Ya existe un MCP llamado '{name}'")
    cfg["mcpServers"][name] = _mcp_server_from_target(target)
    _mcp_save(cfg)
    return {"ok": True, "servers": list(cfg["mcpServers"].keys()), "configs": _mcp_view(cfg)}


@app.put("/api/mcps/{name}")
def edit_mcp(name: str, req: McpEdit):
    target = req.target.strip()
    if not target:
        raise HTTPException(status_code=400, detail="Falta la URL o el comando")
    cfg = _mcp_cfg()
    if name not in cfg["mcpServers"]:
        raise HTTPException(status_code=404, detail="No existe ese MCP")
    # preservar env existente (p.ej. tokens) al cambiar solo la URL/comando
    prev_env = cfg["mcpServers"][name].get("env")
    new = _mcp_server_from_target(target)
    if prev_env:
        new["env"] = prev_env
    cfg["mcpServers"][name] = new
    _mcp_save(cfg)
    return {"ok": True, "servers": list(cfg["mcpServers"].keys()), "configs": _mcp_view(cfg)}


@app.delete("/api/mcps/{name}")
def delete_mcp(name: str):
    cfg = _mcp_cfg()
    if name not in cfg["mcpServers"]:
        raise HTTPException(status_code=404, detail="No existe ese MCP")
    del cfg["mcpServers"][name]
    _mcp_save(cfg)
    return {"ok": True, "servers": list(cfg["mcpServers"].keys()), "configs": _mcp_view(cfg)}


@app.get("/api/env")
def env_status():
    """Rutas/endpoints locales para el panel de config. Sin chequeos de red (no bloquea)."""
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    return {
        "vault_dir": config.VAULT_DIR,
        "workspace_dir": config.WORKSPACE_DIR,
        "ollama_url": config.OLLAMA_URL,
        # Telegram: solo lectura y token enmascarado — nunca sale entero al front
        "tg_token": (tg_token[:6] + "…" + tg_token[-4:]) if len(tg_token) > 12 else ("configurado" if tg_token else ""),
        "tg_chats": os.getenv("TELEGRAM_ALLOWED_USER", ""),
    }


@app.get("/api/soul")
def get_soul():
    return {"content": _soul()}


@app.post("/api/soul")
def set_soul(req: SoulUpdate):
    try:
        path = os.path.join(_DIR, "soul.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(req.content)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo guardar soul.md: {e}")


@app.get("/api/context-limit")
def context_limit(model: str):
    return {"limit": clients.context_limit(model)}


# ---------------------------------------------------------------- chat streaming
@app.post("/api/chat")
def chat(req: ChatRequest):
    """Orquesta un turno completo del agente en streaming (NDJSON).

    Eventos emitidos:
      {"type":"recall","count":N}
      {"type":"token","token":"..."}
      {"type":"tool","name":"...","args":{...}}
      {"type":"done","reply":"...","calls":[...],"usage":{...},"meta":{...},
              "saved_facts":[...],"error":...}
    """

    def event_stream():
        sess_name = req.session
        sessions = store.load_sessions()
        sess = sessions.get(sess_name, {"messages": [], "tools": {}, "mem": {},
                                         "tokens": 0, "ctx": 0})
        sess.setdefault("messages", [])
        sess.setdefault("tools", {})
        sess.setdefault("mem", {})
        sess.setdefault("tokens", 0)
        sess.setdefault("ctx", 0)

        # agregar mensaje del usuario
        sess["messages"].append({"role": "user", "content": req.message})

        # armar system prompt + recall de memoria (el front puede pisar el soul)
        soul = req.system.strip() if req.system and req.system.strip() else _soul()
        system, recalled = agent.build_system(soul, req.message, req.use_memory)
        api_msgs = [{"role": "system", "content": system}]
        api_msgs += [{"role": m["role"], "content": m["content"]} for m in sess["messages"]]

        yield _event("recall", {"count": len(recalled), "facts": recalled})

        # conectar MCPs seleccionados (igual que el multiselect de app.py)
        bridge = None
        if req.mcp_servers:
            try:
                bridge = mcp_bridge.MCPBridge(list(req.mcp_servers))
            except Exception as e:
                yield _event("warning", {"text": f"MCP: {e}"})

        reply, calls_log, usage = "", [], {"total": 0, "gen": 0, "ctx": sess.get("ctx", 0)}
        meta = None
        err_msg = None
        saved_ok = False
        saved_facts = []
        opts = {}
        if req.top_p is not None:
            opts["top_p"] = req.top_p
        if req.max_tokens:
            opts["num_predict"] = req.max_tokens
        if req.num_ctx:
            opts["num_ctx"] = req.num_ctx
        t0 = time.time()
        try:
            for kind, pl in clients.chat_stream_with_tools(
                req.model, api_msgs,
                temperature=req.temperature,
                bridge=bridge,
                use_tools=req.use_tools,
                think=req.think,
                options=opts,
            ):
                if kind == "token":
                    yield _event("token", {"token": pl})
                elif kind == "tool":
                    name, args = pl
                    yield _event("tool", {"name": name, "args": args})
                elif kind == "done":
                    reply, calls_log, usage = pl["reply"], pl["calls"], pl["usage"]
            secs = time.time() - t0
            gen = usage.get("gen", 0)
            meta = {"gen": gen, "total": usage.get("total", 0),
                    "secs": round(secs, 1),
                    "tps": round(gen / secs, 1) if secs > 0 else 0}
            sess["tokens"] = sess.get("tokens", 0) + usage.get("total", 0)
            sess["ctx"] = usage.get("ctx", sess.get("ctx", 0))
            saved_ok = True
        except Exception as e:
            err_msg = str(e)
            reply = f"⚠️ Error del modelo local: {e}"
            yield _event("error", {"text": reply})
        finally:
            if bridge:
                try:
                    bridge.close()
                except Exception:
                    pass

        idx = len(sess["messages"])
        sess["messages"].append({"role": "assistant", "content": reply})
        if calls_log:
            sess.setdefault("tools", {})[str(idx)] = calls_log

        # post-turno compartido: memoria + traza
        try:
            secs = (meta or {}).get("secs", 0)
            saved_facts, _ = agent.finalize(
                "web", req.message, reply, calls_log, usage, secs, req.model,
                use_memory=req.use_memory and saved_ok,
                recalled=recalled,
                error=err_msg,
            )
            if saved_facts:
                sess.setdefault("mem", {})[str(idx)] = saved_facts
        except Exception:
            pass

        store.save_session(sess_name, sess)

        yield _event("done", {
            "reply": reply,
            "calls": calls_log,
            "usage": usage,
            "meta": meta,
            "saved_facts": saved_facts,
            "error": err_msg,
        })

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


# ---------------------------------------------------------------- archivos estáticos (deben ir al final para no sombrear /api/*)
@app.get("/", include_in_schema=False)
def root():
    return FileResponse(os.path.join(_WEB_DIR, "index.html"))


def _safe_file(base: str, path: str):
    """Resuelve path dentro de base; None si escapa del directorio (../ etc.)."""
    base = os.path.realpath(base)
    p = os.path.realpath(os.path.join(base, path))
    if p != base and not p.startswith(base + os.sep):
        return None
    return p if os.path.isfile(p) else None


@app.get("/{path:path}", include_in_schema=False)
def static_files(path: str):
    """Sirve la SPA y la carpeta static/ de write_html."""
    for base in (_WEB_DIR, _STATIC_DIR):
        p = _safe_file(base, path)
        if p:
            return FileResponse(p)
    # Fallback a index.html para rutas de la SPA
    if os.path.isfile(os.path.join(_WEB_DIR, "index.html")):
        return FileResponse(os.path.join(_WEB_DIR, "index.html"))
    raise HTTPException(status_code=404, detail="Not found")


def _event(kind, payload):
    return json.dumps({"type": kind, **payload}, ensure_ascii=False) + "\n"
