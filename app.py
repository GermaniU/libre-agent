"""LibreAgent — espacio de trabajo/chat con modelos locales, tools y RAG sobre tu vault.

Todo corre en tu LAN: ollama + corpus/Qdrant (opcional). Cero tokens de nube.
El modelo decide solo cuándo usar web, vault o generar HTML (ver soul.md).
"""
import json
import os
import subprocess
import time

import psutil
import streamlit as st

import agent
import clients
import config
import mcp_bridge
import memory
import store
import trace

st.set_page_config(page_title="LibreAgent", page_icon="🧠", layout="wide")

# ------------------------------------------------------------- tema (rediseño)
# Capa visual sobre Streamlit: IBM Plex + acento terracota, burbujas de usuario,
# code blocks y detalles del mockup. Los selectores de Streamlit pueden cambiar
# entre versiones; si alguno no matchea, degrada sin romper la app.
_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
:root{
  --bg0:#101014; --bg1:#16161B; --bg2:#1D1D24; --bg3:#26262E;
  --bd:#2A2A33; --bd2:#3E3E4A; --tx:#ECECF1; --tx2:#A6A6B4; --tx3:#73737F;
  --ac:#E17A54; --ac2:#EA8A66; --acbg:rgba(225,122,84,.13);
  --ok:#4CAF82; --err:#E5555A; --usr:#22222B; --code:#131318; --cw:820px;
}
html, body, [class*="css"], .stApp{ font-family:'IBM Plex Sans',sans-serif; }
.stApp{ background:var(--bg0); color:var(--tx); }
.block-container{ max-width:var(--cw); padding-top:2.2rem; }
[data-testid="stSidebar"]{ background:var(--bg1); border-right:1px solid var(--bd); }
h1,h2,h3,h4{ letter-spacing:-.01em; color:var(--tx); }
.stButton>button, .stFormSubmitButton>button, .stLinkButton>a{
  border-radius:10px; border:1px solid var(--bd); background:var(--bg2); color:var(--tx2);
  font-weight:500; transition:all .12s;
}
.stButton>button:hover, .stLinkButton>a:hover{ border-color:var(--ac); color:var(--tx); }
.stButton>button[kind="primary"]{ background:var(--ac); border-color:var(--ac); color:#fff; }
.stButton>button[kind="primary"]:hover{ background:var(--ac2); border-color:var(--ac2); }
[data-baseweb="select"]>div, .stTextInput input, .stTextArea textarea, .stNumberInput input{
  background:var(--bg2)!important; border-color:var(--bd)!important; border-radius:10px!important; color:var(--tx)!important;
}
[data-testid="stSlider"] [role="slider"]{ background:var(--ac)!important; }
[data-testid="stChatInput"]{ background:var(--bg2); border:1px solid var(--bd); border-radius:14px; }
[data-testid="stChatInput"] textarea{ color:var(--tx); }
[data-testid="stChatMessage"]{ background:transparent; padding:.2rem 0; gap:.6rem; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]){ flex-direction:row-reverse; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageAvatarUser"]{ display:none; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"]{
  background:var(--usr); border:1px solid var(--bd); border-radius:16px 16px 4px 16px; padding:10px 14px; max-width:82%;
}
[data-testid="stChatMessageAvatarAssistant"]{ background:var(--ac)!important; color:#fff!important; border:none!important; }
code{ font-family:'IBM Plex Mono',monospace; }
pre, [data-testid="stCode"]{ background:var(--code)!important; border:1px solid var(--bd); border-radius:10px; }
:not(pre)>code{ background:var(--bg3); color:var(--tx); border-radius:6px; padding:1px 6px; font-size:.85em; }
th,td{ border:1px solid var(--bd)!important; } thead th{ background:var(--bg1)!important; color:var(--tx2)!important; }
[data-testid="stExpander"]{ border:1px solid var(--bd); border-radius:10px; background:var(--bg1); }
[data-testid="stProgress"] div[role="progressbar"]>div{ background:var(--ac)!important; }
hr{ border-color:var(--bd); }
*{ scrollbar-width:thin; scrollbar-color:var(--bd2) transparent; }
::-webkit-scrollbar{ width:8px; height:8px; } ::-webkit-scrollbar-thumb{ background:var(--bd2); border-radius:4px; }
#MainMenu, footer{ visibility:hidden; }
@media (prefers-reduced-motion:reduce){ *{ animation:none!important; transition:none!important; } }
</style>
"""
st.markdown(_THEME_CSS, unsafe_allow_html=True)

_DIR = os.path.dirname(os.path.abspath(__file__))

FALLBACK_SOUL = (
    "Sos un asistente con tools. Usá web_search/web_fetch para info externa, vault_search "
    "para las notas del usuario y write_html si pide un documento. Respondé en español. "
    "Atendé SOLO el último mensaje; nunca repitas búsquedas de temas anteriores."
)


@st.cache_data(ttl=30)
def _soul():
    try:
        with open(os.path.join(_DIR, "soul.md")) as f:
            return f.read()
    except Exception:
        return FALLBACK_SOUL


@st.cache_data(ttl=30)
def _models():
    return clients.list_local_models()


@st.cache_resource
def _bridge(servers):
    return mcp_bridge.MCPBridge(list(servers))


@st.cache_data(ttl=120)
def _ctx_limit(model_name):
    return clients.context_limit(model_name)


def _gpu_stats():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        util, used, total, temp = [float(x) for x in out.split(",")]
        return {"util": util, "vram_used": used, "vram_total": total, "temp": temp}
    except Exception:
        return None


@st.fragment(run_every="5s")
def _resources():
    st.caption("📟 Recursos del equipo")
    cpu = psutil.cpu_percent()
    vm = psutil.virtual_memory()
    st.progress(min(cpu / 100, 1.0), text=f"CPU {cpu:.0f}%")
    st.progress(min(vm.percent / 100, 1.0),
                text=f"RAM {vm.percent:.0f}% · {vm.used/1024**3:.1f}/{vm.total/1024**3:.0f} GB (WSL)")
    g = _gpu_stats()
    if g:
        st.progress(min(g["util"] / 100, 1.0), text=f"GPU {g['util']:.0f}% · {g['temp']:.0f}°C")
        st.progress(min(g["vram_used"] / g["vram_total"], 1.0),
                    text=f"VRAM {g['vram_used']/1024:.1f}/{g['vram_total']/1024:.0f} GB")
    else:
        st.caption("GPU no disponible (nvidia-smi falló)")


# ------------------------------------------------------------- estado
def _new_session():
    return {"messages": [], "tools": {}, "mem": {}, "tokens": 0, "ctx": 0}

if "sessions" not in st.session_state:
    # cargar de SQLite (sobreviven reinicios); si no hay nada, arrancar un chat vacío
    saved = store.load_sessions()
    st.session_state.sessions = saved or {"Chat 1": _new_session()}
    st.session_state.current = next(iter(st.session_state.sessions))


# ------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🧠 LibreAgent")
    st.caption("Modelos locales · web · vault · HTML · sin nube")

    st.subheader("Espacios")
    names = list(st.session_state.sessions.keys())
    st.session_state.current = st.radio("Sesión", names,
                                         index=names.index(st.session_state.current),
                                         label_visibility="collapsed")
    c1, c2 = st.columns(2)
    if c1.button("➕ Nuevo", use_container_width=True, type="primary"):
        n = f"Chat {len(st.session_state.sessions)+1}"
        st.session_state.sessions[n] = _new_session()
        st.session_state.current = n
        store.save_session(n, st.session_state.sessions[n])
        st.rerun()
    if c2.button("🗑️ Limpiar", use_container_width=True):
        cur = st.session_state.current
        st.session_state.sessions[cur] = _new_session()
        store.save_session(cur, st.session_state.sessions[cur])
        st.rerun()

    st.divider()
    try:
        models = _models()
    except Exception as e:
        st.error(f"Ollama no responde: {e}")
        st.stop()
    chat_models = [m for m in models if m["kind"] in ("chat", "vision")]
    if not chat_models:
        st.error("No hay modelos de chat que entren en la VRAM.")
        st.stop()
    labels = [f"{m['name']}  ({m['gb']} GB)" + ("" if m["fits"] else " ⚠️ CPU")
              for m in chat_models]
    default_i = next((i for i, m in enumerate(chat_models) if m["name"] == config.DEFAULT_MODEL), 0)
    sel = st.selectbox("Modelo local", labels, index=default_i,
                        help="⚠️ CPU = no entra en los 12 GB de la 3060; corre parcial en CPU (lento).")
    model = chat_models[labels.index(sel)]["name"]

    use_tools = st.toggle(
        "🛠️ Usar tools (web · vault · HTML)", value=True,
        help="Apagalo para CHAT PURO: el modelo responde solo con su conocimiento, "
             "sin buscar en la web ni en el vault. Ideal para modelos sin tool-calling.")
    think = st.toggle(
        "🧠 Razonamiento (thinking)", value=False,
        help="Activá el pensamiento paso a paso: mejor en preguntas complejas, pero más "
             "lento. Apagado = respuestas ágiles. Se ignora solo si el modelo no razona.")
    use_memory = st.toggle(
        "💾 Memoria persistente", value=True,
        help="Recuerda cosas tuyas entre sesiones (mcp-memory, namespace 'libreagent'): "
             "recall antes de responder + guardado automático de hechos duraderos.")

    # todo lo fino vive acá; el día a día no necesita tocar nada
    bridge = None
    with st.expander("⚙️ Avanzado"):
        temp = st.slider("Temperatura", 0.0, 1.2, 0.4, 0.1)
        mcp_sel = st.multiselect("🔌 MCPs de Claude", mcp_bridge.list_configured_servers(),
                                  default=[],
                                  help="Suma los MCP servers de ~/.claude.json. "
                                       "Elegí pocos: cada uno mete tools al contexto del modelo.")
        if mcp_sel:
            with st.spinner("Conectando MCPs…"):
                bridge = _bridge(tuple(sorted(mcp_sel)))
            if bridge.connected:
                st.caption(f"✅ {', '.join(bridge.connected)} · {len(bridge.specs)} tools")
            for srv, err in bridge.errors.items():
                st.warning(f"{srv}: {err}")
        st.caption("El soul se edita en `soul.md` (se recarga solo).")

    st.caption(("✅ Corpus OK" if clients.corpus_ok() else "⚠️ Corpus sin conexión")
               + " · 🛠️ tools siempre activas")

    st.divider()
    _resources()

    st.divider()
    # ☕ Donaciones (opcional): reemplazá el usuario de PayPal. Software libre; esto es un "si te sirve".
    st.link_button("☕ Invitame un café", "https://paypal.me/TU_USUARIO", use_container_width=True)

    with st.expander("🔍 Trazas recientes"):
        evs = trace.recent(8)
        if not evs:
            st.caption("Sin trazas todavía.")
        for r in reversed(evs):
            tls = r.get("tools", [])
            head = (f"{r.get('ts', '')[11:]} · {r.get('gen', 0)}tok/{r.get('secs', 0)}s"
                    + (f" · 🛠️{len(tls)}" if tls else "")
                    + (" · ⚠️" if r.get("error") else ""))
            st.caption(head)
            st.text((r.get("prompt", "") or "")[:70])
            if tls:
                st.caption("  ↳ " + ", ".join(t["tool"] for t in tls))
    st.caption(f"Log completo: `{os.path.basename(trace.LOG)}`")


# ------------------------------------------------------------- chat
sess = st.session_state.sessions[st.session_state.current]
st.subheader(f"💬 {st.session_state.current}")

ctx_bar = st.empty()

def _draw_ctx():
    limit = _ctx_limit(model)
    used, total = sess.get("ctx", 0), sess.get("tokens", 0)
    with ctx_bar.container():
        if limit:
            pct = min(used / limit, 1.0)
            st.progress(pct, text=f"🧮 Contexto: {used:,} / {limit:,} tokens ({pct:.0%}) · "
                                   f"consumidos en la sesión: {total:,}")
            if pct >= 0.85:
                st.warning("El contexto está casi lleno — abrí un espacio nuevo o limpiá este.")
        else:
            st.caption(f"🧮 Tokens consumidos en la sesión: {total:,}")

_draw_ctx()

for i, msg in enumerate(sess["messages"]):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        tcs = sess.get("tools", {}).get(str(i))
        if tcs:
            with st.expander(f"🛠️ {len(tcs)} tools ejecutadas"):
                for t in tcs:
                    st.markdown(f"**{t['tool']}** `{json.dumps(t['args'], ensure_ascii=False)[:200]}`")
                    st.caption(t["result"][:280])
        mems = sess.get("mem", {}).get(str(i))
        if mems:
            with st.expander(f"💾 {len(mems)} recuerdo(s) guardado(s)"):
                for m in mems:
                    st.caption(m)
        mt = sess.get("meta", {}).get(str(i))
        if mt:
            st.caption(f"⏱️ {mt['secs']}s · {mt['gen']} tokens · {mt['tps']} tok/s")

prompt = st.chat_input("Preguntá lo que sea — el modelo decide si usa web, vault o tools…")
if prompt:
    sess["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    system, recalled = agent.build_system(_soul(), prompt, use_memory)
    api_msgs = [{"role": "system", "content": system}]
    api_msgs += [{"role": m["role"], "content": m["content"]} for m in sess["messages"]]

    reply, calls_log, usage = "", [], {"total": 0, "gen": 0, "ctx": sess.get("ctx", 0)}
    saved_ok = False
    meta = None
    err_msg = None
    with st.chat_message("assistant"):
        if recalled:
            st.caption(f"💾 recordé {len(recalled)} cosa(s) tuya(s)")
        slot = st.empty()
        t0 = time.time()
        try:
            acc = ""
            for kind, pl in clients.chat_stream_with_tools(model, api_msgs, temperature=temp,
                                                           bridge=bridge, use_tools=use_tools,
                                                           think=think):
                if kind == "token":
                    acc += pl
                    slot.markdown(acc + " ▌")
                elif kind == "tool":
                    slot.markdown(acc + f"\n\n> 🛠️ `{pl[0]}` {json.dumps(pl[1], ensure_ascii=False)[:120]}")
                elif kind == "done":
                    reply, calls_log, usage = pl["reply"], pl["calls"], pl["usage"]
            slot.markdown(reply)
            secs = time.time() - t0
            gen = usage.get("gen", 0)
            meta = {"gen": gen, "total": usage["total"], "secs": round(secs, 1),
                    "tps": round(gen / secs, 1) if secs > 0 else 0}
            st.caption(f"⏱️ {meta['secs']}s · {meta['gen']} tokens · {meta['tps']} tok/s")
            sess["tokens"] = sess.get("tokens", 0) + usage["total"]
            sess["ctx"] = usage["ctx"]
            saved_ok = True
        except Exception as e:
            reply = f"⚠️ Error del modelo local: {e}"
            err_msg = str(e)
            slot.error(reply)

    idx = len(sess["messages"])
    sess["messages"].append({"role": "assistant", "content": reply})
    if calls_log:
        sess.setdefault("tools", {})[str(idx)] = calls_log
    if meta:
        sess.setdefault("meta", {})[str(idx)] = meta
    # núcleo compartido: auto-save de memoria + traza (idéntico a lo que hace el bot)
    secs = (meta or {}).get("secs", 0)
    saved_facts, _ = agent.finalize("web", prompt, reply, calls_log, usage, secs, model,
                                    use_memory=use_memory and saved_ok, recalled=recalled,
                                    error=err_msg)
    if saved_facts:
        sess.setdefault("mem", {})[str(idx)] = saved_facts
        st.caption(f"💾 {len(saved_facts)} recuerdo(s) guardado(s) en memoria")
    store.save_session(st.session_state.current, sess)   # persiste el intercambio
    _draw_ctx()
