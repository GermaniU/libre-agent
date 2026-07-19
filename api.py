"""Bridge backend for LocalAgent: exposes the agent loop over HTTP.

Does not replace the agent logic: it delegates everything to agent.py, clients.py,
store.py, memory.py, trace.py, etc. It only adds an HTTP layer + a static frontend.
"""
import json
import logging
import os
import re
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import agent
import clients
import config
import mcp_bridge
import prompts
import store

# Entry point: configure logging once (LOG_LEVEL env overrides; default INFO).
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("localagent.api")

_DIR = os.path.dirname(os.path.abspath(__file__))
_WEB_DIR = os.path.join(_DIR, "web")
_STATIC_DIR = os.path.join(_DIR, "static")

app = FastAPI(title="LocalAgent API", version="0.1.0")

# The frontend is served from the same origin; CORS only for local origins
# (with "*" any page open in the browser could read /api/sessions).
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


# Soul path lives under prompts/ (single source of truth loaded via agent.load_soul).
_SOUL_PATH = os.path.join(_DIR, "prompts", "soul.md")


# ---------------------------------------------------------------- models
class ChatRequest(BaseModel):
    session: str
    message: str
    model: str
    temperature: float = 0.4
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    num_ctx: Optional[int] = None
    system: Optional[str] = None  # override of soul.md for this session
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


class CompactRequest(BaseModel):
    session: str
    model: str
    keep: int = 4


# ---------------------------------------------------------------- API
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/models")
def list_models():
    """Chat/vision models available in Ollama, with a VRAM indicator."""
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
    target: str  # http(s) URL -> http server; anything else -> stdio command


class McpEdit(BaseModel):
    target: str


def _mcp_cfg():
    try:
        with open(mcp_bridge.CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        log.debug("no readable mcp.json at %s", mcp_bridge.CONFIG_PATH, exc_info=True)
        cfg = {}
    cfg.setdefault("mcpServers", {})
    return cfg


def _mcp_save(cfg):
    with open(mcp_bridge.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _mcp_server_from_target(target):
    """Translates a 'target' (http URL or 'command args…') into an MCP config dict."""
    if re.match(r"^https?://", target):
        return {"type": "http", "url": target}
    parts = target.split()
    return {"command": parts[0], "args": parts[1:]}


def _mcp_target_of(s):
    """Derives the readable 'target' from a config dict (for display/editing)."""
    if s.get("type") == "http" or "url" in s:
        return s.get("url", "")
    return " ".join([s.get("command", "")] + s.get("args", [])).strip()


def _mcp_view(cfg):
    """Public list of servers: name + type + target + env (without env values)."""
    out = []
    for name, s in cfg["mcpServers"].items():
        is_http = s.get("type") == "http" or "url" in s
        out.append({
            "name": name,
            "type": "http" if is_http else "stdio",
            "target": _mcp_target_of(s),
            "env_keys": sorted((s.get("env") or {}).keys()),  # keys only, never values
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
    # preserve existing env (e.g. tokens) when changing only the URL/command
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
    """Local paths/endpoints for the config panel. No network checks (non-blocking)."""
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    return {
        "vault_dir": config.VAULT_DIR,
        "workspace_dir": config.WORKSPACE_DIR,
        "ollama_url": config.OLLAMA_URL,
        # Telegram: read-only and masked token — never leaves whole to the front
        "tg_token": (tg_token[:6] + "…" + tg_token[-4:]) if len(tg_token) > 12 else ("configurado" if tg_token else ""),
        "tg_chats": os.getenv("TELEGRAM_ALLOWED_USER", ""),
    }


@app.get("/api/soul")
def get_soul():
    return {"content": agent.load_soul()}


@app.post("/api/soul")
def set_soul(req: SoulUpdate):
    try:
        with open(_SOUL_PATH, "w", encoding="utf-8") as f:
            f.write(req.content)
        return {"ok": True}
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"No se pudo guardar el soul: {e}")


@app.get("/api/context-limit")
def context_limit(model: str):
    return {"limit": clients.context_limit(model)}


@app.post("/api/compact")
def compact(req: CompactRequest):
    """Summarizes the old part of a session and collapses it into one message.

    Frees up context (like Claude Code's /compact): the oldest messages are
    replaced by a single assistant message with their summary, keeping the last
    ``req.keep`` messages verbatim.
    """
    try:
        sessions = store.load_sessions()
        sess = sessions.get(req.session)
        if not sess:
            raise HTTPException(status_code=404, detail="No existe esa sesión")
        messages = sess.get("messages", [])
        if len(messages) <= req.keep:
            return {"ok": True, "compacted": False}

        old = messages[:-req.keep]
        lines = []
        for m in old:
            who = "Usuario" if m.get("role") == "user" else "Asistente"
            lines.append(f"{who}: {m.get('content', '')}")
        conversation = "\n".join(lines)
        prompt = prompts.load("compact.txt").format(conversation=conversation)

        summary, _calls, _usage = clients.chat_with_tools(
            req.model, [{"role": "user", "content": prompt}],
            temperature=0.3, use_tools=False, think=False)

        sess["messages"] = agent.compact_messages(messages, summary, req.keep)
        # metadata (tool calls / saved memories) is keyed by old message index — stale now
        sess["tools"] = {}
        sess["mem"] = {}
        sess["ctx"] = 0
        store.save_session(req.session, sess)
        return {"ok": True, "compacted": True, "removed": len(old), "session": sess}
    except HTTPException:
        raise
    except Exception as e:
        log.warning("could not compact session %r", req.session, exc_info=True)
        raise HTTPException(status_code=500, detail=f"No se pudo compactar la conversación: {e}")


# ---------------------------------------------------------------- chat streaming
@app.post("/api/chat")
def chat(req: ChatRequest):
    """Orchestrates a full agent turn in streaming (NDJSON).

    Emitted events:
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

        # add the user message
        sess["messages"].append({"role": "user", "content": req.message})

        # the front can override the soul for this session
        soul = req.system.strip() if req.system and req.system.strip() else agent.load_soul()

        # connect the selected MCPs (this gateway owns the bridge lifecycle)
        bridge = None
        if req.mcp_servers:
            try:
                bridge = mcp_bridge.MCPBridge(list(req.mcp_servers))
            except Exception as e:
                yield _event("warning", {"text": f"MCP: {e}"})

        opts = {}
        if req.top_p is not None:
            opts["top_p"] = req.top_p
        if req.max_tokens:
            opts["num_predict"] = req.max_tokens
        if req.num_ctx:
            opts["num_ctx"] = req.num_ctx

        # the shared turn loop; this gateway only translates events to NDJSON + persists
        reply, calls_log, usage, meta, saved_facts, err_msg = "", [], {}, None, [], None
        try:
            for ev in agent.run_turn(
                req.model, sess["messages"], req.message, soul,
                channel="web", temperature=req.temperature, options=opts,
                use_tools=req.use_tools, think=req.think, use_memory=req.use_memory,
                bridge=bridge, stream=True,
            ):
                t = ev["type"]
                if t == "recall":
                    yield _event("recall", {"count": ev["count"], "facts": ev["facts"]})
                elif t == "token":
                    yield _event("token", {"token": ev["token"]})
                elif t == "tool":
                    yield _event("tool", {"name": ev["name"], "args": ev["args"]})
                elif t == "error":
                    yield _event("error", {"text": ev["text"]})
                elif t == "done":
                    reply, calls_log, usage = ev["reply"], ev["calls"], ev["usage"]
                    meta, saved_facts, err_msg = ev["meta"], ev["saved_facts"], ev["error"]
        finally:
            if bridge:
                try:
                    bridge.close()
                except Exception:
                    log.debug("error closing MCP bridge after turn", exc_info=True)

        # persist the exchange (gateway-specific)
        sess["tokens"] = sess.get("tokens", 0) + usage.get("total", 0)
        sess["ctx"] = usage.get("ctx", sess.get("ctx", 0))
        idx = len(sess["messages"])
        sess["messages"].append({"role": "assistant", "content": reply})
        if calls_log:
            sess.setdefault("tools", {})[str(idx)] = calls_log
        if saved_facts:
            sess.setdefault("mem", {})[str(idx)] = saved_facts
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


# ---------------------------------------------------------------- static files (must go last so they don't shadow /api/*)
@app.get("/", include_in_schema=False)
def root():
    return FileResponse(os.path.join(_WEB_DIR, "index.html"))


def _safe_file(base: str, path: str):
    """Resolves path within base; None if it escapes the directory (../ etc.)."""
    base = os.path.realpath(base)
    p = os.path.realpath(os.path.join(base, path))
    if p != base and not p.startswith(base + os.sep):
        return None
    return p if os.path.isfile(p) else None


@app.get("/{path:path}", include_in_schema=False)
def static_files(path: str):
    """Serves the SPA and the static/ folder from write_html."""
    for base in (_WEB_DIR, _STATIC_DIR):
        p = _safe_file(base, path)
        if p:
            return FileResponse(p)
    # Fallback to index.html for SPA routes
    if os.path.isfile(os.path.join(_WEB_DIR, "index.html")):
        return FileResponse(os.path.join(_WEB_DIR, "index.html"))
    raise HTTPException(status_code=404, detail="Not found")


def _event(kind, payload):
    return json.dumps({"type": kind, **payload}, ensure_ascii=False) + "\n"
