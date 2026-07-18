"""Memoria persistente de LibreAgent sobre mcp-memory, namespace 'libreagent'.

El "latido" del núcleo: auto-recall antes de responder + auto-save después.
mcp-memory (Qdrant) es el ÚNICO dueño del store — acá solo llamamos su API por el
mismo puente MCP que ya usa la app, sin duplicar colecciones ni embeddings.
"""
import json

import streamlit as st

import mcp_bridge

NAMESPACE = "libreagent"
_SERVER = "mcp-memory"
_SEARCH = "mcp_memory__memory_search"
_SAVE = "mcp_memory__memory_save"


@st.cache_resource
def _bridge():
    """Puente dedicado y persistente solo a mcp-memory (cacheado toda la sesión)."""
    try:
        b = mcp_bridge.MCPBridge([_SERVER])
        return b if _SEARCH in b.tools else None
    except Exception:
        return None


def available():
    """True si mcp-memory está conectado y usable."""
    return _bridge() is not None


def recall(query, k=4, min_score=0.35):
    """Hasta k memorias relevantes del namespace libreagent (lista de strings; [] si falla).

    El server (vía MCP) devuelve una lista JSON directa; toleramos también {"result": [...]}.
    """
    b = _bridge()
    if not b or not (query or "").strip():
        return []
    try:
        raw = b.call(_SEARCH, {"query": query, "limit": k, "namespace": NAMESPACE}, timeout=20)
        data = json.loads(raw)
        items = data.get("result", []) if isinstance(data, dict) else data
    except Exception:
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        score = it.get("score")
        if score is not None and score < min_score:
            continue
        c = (it.get("content") or "").strip()
        if c:
            out.append(c)
    return out


def remember(content, tags=None):
    """Guarda un hecho en el namespace libreagent (best-effort, no rompe el chat)."""
    b = _bridge()
    content = (content or "").strip()
    if not b or len(content) < 8:
        return False
    try:
        res = b.call(_SAVE, {"content": content, "namespace": NAMESPACE,
                             "tags": tags or ["libreagent"]}, timeout=20)
        return not str(res).startswith("Error del tool")
    except Exception:
        return False


_EXTRACT_PROMPT = (
    "De este intercambio, extraé SOLO hechos duraderos y personales sobre el USUARIO que "
    "valga la pena recordar en futuras conversaciones: preferencias, datos suyos, decisiones, "
    "proyectos, cómo le gusta trabajar. Ignorá lo trivial, lo efímero y lo que sea del asistente. "
    "Devolvé 0 a 3 líneas, una por hecho, en español, sin numerar ni viñetas. "
    "Si no hay nada que valga la pena recordar, devolvé EXACTAMENTE: NADA\n\n"
    "Usuario: {u}\nAsistente: {a}"
)


def remember_from_exchange(user_msg, assistant_msg, extractor_model):
    """Extrae hechos duraderos del intercambio con un modelo local y los guarda.

    Devuelve la lista de hechos guardados (para mostrarla en la UI). No rompe si falla.
    """
    import clients
    if not available():
        return []
    prompt = _EXTRACT_PROMPT.format(u=(user_msg or "")[:2000], a=(assistant_msg or "")[:2000])
    try:
        raw, _, _ = clients.chat_with_tools(
            extractor_model, [{"role": "user", "content": prompt}],
            temperature=0.2, use_tools=False, think=False)
    except Exception:
        return []
    if not raw or raw.strip().upper().startswith("NADA"):
        return []
    saved = []
    for line in raw.splitlines():
        fact = line.strip("-•* \t")
        if len(fact) >= 8 and "NADA" not in fact.upper() and remember(fact):
            saved.append(fact)
    return saved
