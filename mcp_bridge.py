"""MCP bridge: connects the servers from the project's mcp.json and exposes their tools to the local model.

By default there is NO MCP: LocalAgent only uses the ones you declare in its own
mcp.json (same {"mcpServers": {...}} format as Claude). Override with MCP_CONFIG.

Connections live in their own thread with its event loop (streamlit is sync).
Each tool is namespaced as  <server>__<tool>  to avoid clashing between servers.
"""
import asyncio
import json
import logging
import os
import re
import threading
from contextlib import AsyncExitStack

import config

log = logging.getLogger("localagent.mcp")

CONFIG_PATH = os.getenv(
    "MCP_CONFIG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp.json"),
)


def list_configured_servers():
    """Names of MCPs registered in mcp.json (without connecting). No file = none."""
    try:
        with open(CONFIG_PATH) as f:
            return sorted(json.load(f).get("mcpServers", {}).keys())
    except Exception:
        log.debug("could not read mcp config at %s", CONFIG_PATH, exc_info=True)
        return []


def _safe(name):
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


class MCPBridge:
    """Connects a set of MCP servers and offers .specs (ollama format) and .call()."""

    def __init__(self, servers, connect_timeout=45):
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self._stack = None
        self.tools = {}      # "server__tool" -> (session, real_tool)
        self.specs = []      # specs in ollama/openai format
        self.errors = {}     # server -> connection error
        self.connected = []  # servers OK
        self._run(self._connect(servers), timeout=connect_timeout * max(1, len(servers)))

    def _run(self, coro, timeout=60):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def _connect(self, servers):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        with open(CONFIG_PATH) as f:
            cfg = json.load(f).get("mcpServers", {})
        self._stack = AsyncExitStack()
        for name in servers:
            s = cfg.get(name)
            if not s:
                self.errors[name] = "no está en mcp.json"
                continue
            try:
                if s.get("type") == "http" or "url" in s:
                    read, write, _ = await self._stack.enter_async_context(
                        streamablehttp_client(s["url"], headers=s.get("headers") or None))
                else:
                    params = StdioServerParameters(
                        command=s["command"], args=s.get("args", []),
                        env={**os.environ, **s.get("env", {})})
                    read, write = await self._stack.enter_async_context(stdio_client(params))
                sess = await self._stack.enter_async_context(ClientSession(read, write))
                await asyncio.wait_for(sess.initialize(), 30)
                for t in (await sess.list_tools()).tools:
                    qname = f"{_safe(name)}__{t.name}"
                    self.tools[qname] = (sess, t.name)
                    if t.name in config.MCP_TOOLS_HIDDEN:  # ops bulk/mantenimiento: no ofrecer al modelo (revientan el ctx)
                        continue
                    self.specs.append({"type": "function", "function": {
                        "name": qname,
                        "description": (t.description or "")[:config.MCP_TOOL_DESC_MAX],
                        "parameters": t.inputSchema or {"type": "object", "properties": {}},
                    }})
                self.connected.append(name)
            except Exception as e:
                self.errors[name] = f"{type(e).__name__}: {e}"

    def close(self):
        """Close MCP sessions and subprocesses (best-effort)."""
        try:
            self._run(self._stack.aclose(), timeout=15)
        except Exception:
            log.debug("error closing MCP bridge", exc_info=True)

    def call(self, qname, args, timeout=300):
        sess, tool = self.tools[qname]
        res = self._run(sess.call_tool(tool, args or {}), timeout=timeout)
        parts = []
        for c in res.content:
            if getattr(c, "type", "") == "text":
                parts.append(c.text)
            else:
                parts.append(f"[{getattr(c, 'type', 'contenido')} no textual]")
        out = "\n".join(parts).strip() or "(sin salida)"
        return ("Error del tool: " + out) if res.isError else out


# ---------------------------------------------------------------- pool (reuse across turns)
# One live bridge per server, shared by every turn that selects it: connecting a stdio MCP
# means spawning its process + handshake (seconds), too slow to repeat on every message.
_pool = {}
_pool_lock = threading.Lock()


class PooledBridge:
    """Same surface clients.py uses (.tools/.specs/.call) over pooled per-server bridges.

    Never close it per turn: the connections outlive it. A call that raises evicts its
    server, so a dead process is reconnected on the next turn instead of failing forever.
    """

    def __init__(self, servers):
        self.tools, self.specs, self.errors, self.connected = {}, [], {}, []
        self._owner = {}  # "server__tool" -> (server name, its pooled bridge)
        for name in servers:
            b = _get(name)
            if name in b.errors:
                self.errors[name] = b.errors[name]
                continue
            self.connected.append(name)
            self.tools.update(b.tools)
            self.specs += b.specs
            self._owner.update(dict.fromkeys(b.tools, (name, b)))

    def call(self, qname, args, timeout=300):
        from mcp.shared.exceptions import McpError
        name, b = self._owner[qname]
        try:
            return b.call(qname, args, timeout=timeout)
        except McpError:
            raise  # the server answered (e.g. bad params): connection is fine, keep it
        except Exception:
            _evict(name, b)
            raise


def _get(name):
    """Pooled bridge for one server; failed connections are returned but not kept."""
    with _pool_lock:
        b = _pool.get(name)
        if b is None:
            b = MCPBridge([name])
            if name in b.errors:
                b.close()  # retry on the next turn (the server may come up later)
            else:
                _pool[name] = b
        return b


def pooled(servers):
    """A bridge over `servers` reusing live connections (see PooledBridge)."""
    return PooledBridge(sorted(set(servers)))


def _evict(name, bridge):
    """Drop `bridge` from the pool if it is still the live one for `name`."""
    with _pool_lock:
        if _pool.get(name) is not bridge:
            return
        del _pool[name]
    bridge.close()


def reset_pool(name=None):
    """Drop (and close) one pooled server, or all of them — e.g. after mcp.json changes."""
    with _pool_lock:
        names = [name] if name else list(_pool)
        dropped = [_pool.pop(n) for n in names if n in _pool]
    for b in dropped:
        b.close()
