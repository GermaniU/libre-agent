"""Bot de Telegram de LocalAgent — chat con el modelo local + comandos de control.

Comandos: /status /model /ctx /new /mcp /help. Cualquier otro texto va al modelo
(mismo soul y tools que la UI web). Solo responde al user de TELEGRAM_ALLOWED_USER.
Token y allowlist en .env (no se commitea a ningún lado).
"""
import os
import re
import subprocess
import time
import traceback

import requests as rq

import agent
import clients
import config
import mcp_bridge

DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env():
    p = os.path.join(DIR, ".env")
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED = int(os.environ["TELEGRAM_ALLOWED_USER"])
API = f"https://api.telegram.org/bot{TOKEN}"

state = {"model": config.DEFAULT_MODEL, "messages": [], "tokens": 0, "ctx": 0,
         "mcps": set(), "bridge": None}


def _soul():
    try:
        with open(os.path.join(DIR, "soul.md")) as f:
            return f.read()
    except Exception:
        return "Sos un asistente con tools. Respondé en español."


def send(chat, text):
    for i in range(0, max(len(text), 1), 3900):
        chunk = text[i:i + 3900]
        r = rq.post(f"{API}/sendMessage",
                    json={"chat_id": chat, "text": chunk, "parse_mode": "Markdown"}, timeout=30)
        if not r.ok or not r.json().get("ok"):  # markdown roto -> plano
            rq.post(f"{API}/sendMessage", json={"chat_id": chat, "text": chunk}, timeout=30)


MEDIA_RE = re.compile(
    r'(?:[A-Za-z]:\\|/)[^\s"\'`)\]]+?\.(?:wav|mp3|ogg|m4a|png|jpg|jpeg|webp|mp4|gif|pdf)\b', re.I)


def _to_wsl(path):
    m = re.match(r"^([A-Za-z]):\\(.*)$", path)
    if m:
        return "/mnt/" + m.group(1).lower() + "/" + m.group(2).replace("\\", "/")
    return path


def send_media(chat, calls_log):
    """Detecta rutas de archivos generados por las tools y los manda al chat."""
    sent = []
    seen = set()
    for t in calls_log:
        for m in MEDIA_RE.finditer(str(t.get("result") or "")):
            p = _to_wsl(m.group(0))
            if p in seen or not os.path.isfile(p):
                continue
            seen.add(p)
            ext = p.rsplit(".", 1)[-1].lower()
            if ext in ("png", "jpg", "jpeg", "webp"):
                method, field = "sendPhoto", "photo"
            elif ext in ("wav", "mp3", "m4a", "ogg"):
                method, field = "sendAudio", "audio"
            else:
                method, field = "sendDocument", "document"
            # requests da SSLError EOF subiendo archivos desde WSL; curl no
            try:
                r = subprocess.run(
                    ["curl", "-s", "-m", "180", "-F", f"chat_id={chat}",
                     "-F", f"{field}=@{p}", f"{API}/{method}"],
                    capture_output=True, text=True, timeout=200)
                if '"ok":true' not in r.stdout:  # formato no aceptado -> documento
                    subprocess.run(
                        ["curl", "-s", "-m", "180", "-F", f"chat_id={chat}",
                         "-F", f"document=@{p}", f"{API}/sendDocument"],
                        capture_output=True, text=True, timeout=200)
                sent.append(os.path.basename(p))
            except Exception:
                traceback.print_exc()
    return sent


def typing(chat):
    try:
        rq.post(f"{API}/sendChatAction", json={"chat_id": chat, "action": "typing"}, timeout=10)
    except Exception:
        pass


def _gpu_line():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
        u, mu, mt, t = [float(x) for x in out.strip().split(",")]
        return f"🎮 GPU {u:.0f}% · VRAM {mu/1024:.1f}/{mt/1024:.0f} GB · {t:.0f}°C"
    except Exception:
        return "🎮 GPU: n/d"


def _sys_line():
    try:
        import psutil
        vm = psutil.virtual_memory()
        return (f"💻 CPU {psutil.cpu_percent():.0f}% · "
                f"RAM {vm.used/1024**3:.1f}/{vm.total/1024**3:.0f} GB ({vm.percent:.0f}%)")
    except Exception:
        return "💻 CPU/RAM: n/d"


def _ctx_line():
    limit = clients.context_limit(state["model"])
    if limit:
        pct = state["ctx"] / limit
        filled = int(pct * 10)
        bar = "█" * filled + "░" * (10 - filled)
        return f"🧮 `{bar}` {state['ctx']:,}/{limit:,} ({pct:.0%})"
    return f"🧮 Contexto: {state['ctx']:,} tokens (límite desconocido)"


def cmd_status():
    mcps = ", ".join(sorted(state["mcps"])) or "ninguno"
    corpus = "✅" if clients.corpus_ok() else "⚠️ sin conexión"
    return (f"🧠 *LocalAgent*\n"
            f"Modelo: `{state['model']}`\n"
            f"{_ctx_line()}\n"
            f"Tokens de la sesión: {state['tokens']:,} · mensajes: {len(state['messages'])}\n"
            f"MCPs: {mcps} · Corpus: {corpus}\n"
            f"{_gpu_line()}\n{_sys_line()}")


def _chat_models():
    return [m for m in clients.list_local_models() if m["kind"] in ("chat", "vision")]


def cmd_model(arg):
    models = _chat_models()
    if not arg:
        lines = []
        for i, m in enumerate(models, 1):
            mark = " ←" if m["name"] == state["model"] else ""
            cpu = "" if m["fits"] else " ⚠️CPU"
            lines.append(f"{i}. `{m['name']}` ({m['gb']} GB){cpu}{mark}")
        return "Modelos locales:\n" + "\n".join(lines) + "\n\nCambiar: `/model <número o nombre>`"
    pick = None
    if arg.isdigit() and 1 <= int(arg) <= len(models):
        pick = models[int(arg) - 1]["name"]
    else:
        names = [m["name"] for m in models]
        exact = [n for n in names if n == arg]
        partial = [n for n in names if arg.lower() in n.lower()]
        pick = (exact or partial or [None])[0]
    if not pick:
        return f"No encontré `{arg}`. Mirá la lista con /model"
    state["model"] = pick
    return f"✅ Modelo cambiado a `{pick}`"


def cmd_new():
    state["messages"] = []
    state["ctx"] = 0
    return "🆕 Conversación nueva (el contador de tokens de la sesión sigue acumulando)."


def cmd_mcp(arg):
    avail = mcp_bridge.list_configured_servers()
    if not arg:
        lines = [f"{'🟢' if s in state['mcps'] else '⚪'} `{s}`" for s in avail]
        return ("MCPs (tocá para alternar con `/mcp <nombre>`):\n" + "\n".join(lines)
                + "\n\nOjo: cada MCP suma tools al contexto — conectá pocos.")
    if arg not in avail:
        return f"No existe `{arg}`. Mirá /mcp"
    if arg in state["mcps"]:
        state["mcps"].discard(arg)
        action = f"🔌 Desconectado `{arg}`"
    else:
        state["mcps"].add(arg)
        action = f"🔌 Conectando `{arg}`…"
    if state["bridge"]:
        state["bridge"].close()
        state["bridge"] = None
    if state["mcps"]:
        state["bridge"] = mcp_bridge.MCPBridge(sorted(state["mcps"]))
        ok = ", ".join(state["bridge"].connected) or "ninguno"
        errs = "".join(f"\n⚠️ {s}: {e[:120]}" for s, e in state["bridge"].errors.items())
        return f"{action}\nActivos: {ok} · {len(state['bridge'].specs)} tools{errs}"
    return f"{action}\nSin MCPs activos."


HELP = ("🧠 *LocalAgent Bot*\n"
        "/status — modelo, contexto, tokens, GPU/RAM\n"
        "/model — listar o cambiar modelo\n"
        "/ctx — barra de contexto\n"
        "/new — conversación nueva\n"
        "/mcp — listar/conectar MCPs de Claude\n"
        "Cualquier otro texto → chatea con el modelo local (tools incluidas).")


def handle_chat(chat, text):
    state["messages"].append({"role": "user", "content": text})
    # mismo núcleo que la UI: recall de memoria + system prompt
    system, recalled = agent.build_system(_soul(), text, use_memory=True)
    api_msgs = [{"role": "system", "content": system}] + state["messages"]
    typing(chat)
    t0 = time.time()
    try:
        reply, log, usage = clients.chat_with_tools(
            state["model"], api_msgs, bridge=state["bridge"],
            on_tool=lambda n, a: typing(chat))
    except Exception as e:
        state["messages"].pop()
        agent.finalize("telegram", text, "", [], {}, time.time() - t0, state["model"],
                       use_memory=False, recalled=recalled, error=str(e))
        send(chat, f"⚠️ Error del modelo: {e}")
        return
    state["messages"].append({"role": "assistant", "content": reply})
    state["tokens"] += usage["total"]
    state["ctx"] = usage["ctx"]
    secs = time.time() - t0
    # mismo núcleo: auto-save de memoria + traza (idéntico a la UI)
    _, meta = agent.finalize("telegram", text, reply, log, usage, secs, state["model"],
                             use_memory=True, recalled=recalled)
    tools_used = f" · 🛠️ {', '.join(t['tool'] for t in log)}" if log else ""
    send(chat, reply + f"\n\n`{meta['gen']:,} tok · {meta['secs']:.0f}s · {meta['tps']} tok/s{tools_used}`")
    send_media(chat, log)


def main():
    me = rq.get(f"{API}/getMe", timeout=15).json()["result"]["username"]
    print(f"bot @{me} escuchando (user permitido: {ALLOWED})")
    offset = None
    while True:
        try:
            r = rq.get(f"{API}/getUpdates", params={"timeout": 50, "offset": offset}, timeout=70)
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                uid = (msg.get("from") or {}).get("id")
                chat = (msg.get("chat") or {}).get("id")
                text = (msg.get("text") or "").strip()
                if not text or uid != ALLOWED:
                    continue
                cmd, _, arg = text.partition(" ")
                arg = arg.strip()
                if cmd in ("/start", "/help"):
                    send(chat, HELP)
                elif cmd == "/status":
                    send(chat, cmd_status())
                elif cmd == "/model":
                    send(chat, cmd_model(arg))
                elif cmd == "/ctx":
                    send(chat, _ctx_line())
                elif cmd == "/new":
                    send(chat, cmd_new())
                elif cmd == "/mcp":
                    send(chat, cmd_mcp(arg))
                else:
                    handle_chat(chat, text)
        except KeyboardInterrupt:
            break
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()
