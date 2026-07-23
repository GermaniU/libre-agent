"""LocalAgent persistent memory over mcp-memory, namespace 'localagent'.

The core's "heartbeat": auto-recall before answering + auto-save afterwards.
mcp-memory (Qdrant) is the ONLY owner of the store — here we just call its API through
the same MCP bridge the app already uses, without duplicating collections or embeddings.

The bridge is a module-level singleton (framework-agnostic) so this layer works the same
under the SPA (FastAPI), the Streamlit UI and the Telegram bot.
"""
import json
import logging
import os
import re
import threading

import config
import mcp_bridge
import prompts

log = logging.getLogger("localagent.memory")

NAMESPACE = "localagent"
# Which MCP server backs the memory. Must match a name in mcp.json (override via env).
_SERVER = config.MEMORY_MCP_SERVER
# mcp_bridge namespaces tools as "<safe_server>__<tool>"; mirror that sanitization here.
_NS = re.sub(r"[^a-zA-Z0-9_]", "_", _SERVER)
_SEARCH = f"{_NS}__memory_search"
_SAVE = f"{_NS}__memory_save"

_bridge_lock = threading.Lock()
_bridge_singleton = None
_bridge_ready = False


def _bridge():
    """Dedicated, persistent bridge to mcp-memory only (built once, cached for the process)."""
    global _bridge_singleton, _bridge_ready
    if _bridge_ready:
        return _bridge_singleton
    with _bridge_lock:
        if _bridge_ready:
            return _bridge_singleton
        try:
            b = mcp_bridge.MCPBridge([_SERVER])
            _bridge_singleton = b if _SEARCH in b.tools else None
        except Exception:
            log.debug("memory bridge unavailable (server %r)", _SERVER, exc_info=True)
            _bridge_singleton = None
        _bridge_ready = True
        return _bridge_singleton


def available():
    """True if mcp-memory is connected and usable."""
    return _bridge() is not None


def recall(query, k=4, min_score=0.35):
    """Up to k relevant memories from the localagent namespace (list of strings; [] on failure).

    The server (via MCP) returns a direct JSON list; we also tolerate {"result": [...]}.
    """
    b = _bridge()
    if not b or not (query or "").strip():
        return []
    try:
        raw = b.call(_SEARCH, {"query": query, "limit": k, "namespace": NAMESPACE}, timeout=20)
        data = json.loads(raw)
        items = data.get("result", []) if isinstance(data, dict) else data
    except Exception:
        log.debug("memory recall failed for query %r", query, exc_info=True)
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        score = item.get("score")
        if score is not None and score < min_score:
            continue
        content = (item.get("content") or "").strip()
        if content:
            out.append(content)
    return out


def remember(content, tags=None):
    """Save a fact in the localagent namespace (best-effort, never breaks the chat)."""
    b = _bridge()
    content = (content or "").strip()
    if not b or len(content) < 8:
        return False
    try:
        res = b.call(_SAVE, {"content": content, "namespace": NAMESPACE,
                             "tags": tags or ["localagent"]}, timeout=20)
        return not str(res).startswith("Error del tool")
    except Exception:
        log.debug("memory save failed", exc_info=True)
        return False


def remember_from_exchange(user_msg, assistant_msg, extractor_model):
    """Extract durable facts from the exchange with a local model and save them.

    Returns the list of saved facts (to show in the UI). Never breaks on failure.
    """
    import clients
    if not available():
        return []
    template = prompts.load("memory_extract.txt")
    prompt = template.format(u=(user_msg or "")[:2000], a=(assistant_msg or "")[:2000])
    try:
        raw, _, _ = clients.chat_with_tools(
            extractor_model, [{"role": "user", "content": prompt}],
            temperature=0.2, use_tools=False, think=False)
    except Exception:
        log.debug("memory extraction call failed", exc_info=True)
        return []
    if not raw or raw.strip().upper().startswith("NADA"):
        return []
    saved = []
    for line in raw.splitlines():
        fact = line.strip("-•* \t")
        if len(fact) >= 8 and "NADA" not in fact.upper() and remember(fact):
            saved.append(fact)
    return saved
