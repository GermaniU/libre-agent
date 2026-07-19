"""MCP bridge: connects the servers from the project's mcp.json and exposes their tools to the local model.

By default there is NO MCP: LocalAgent only uses the ones you declare in its own
mcp.json (same {"mcpServers": {...}} format as Claude). Override with MCP_CONFIG.

Connections live in their own thread with its event loop (streamlit is sync).
Each tool is namespaced as  <server>__<tool>  to avoid clashing between servers.
"""
import asyncio
import json
import os
import re
import threading
from contextlib import AsyncExitStack

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
                        streamablehttp_client(s["url"]))
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
                    self.specs.append({"type": "function", "function": {
                        "name": qname,
                        "description": (t.description or "")[:900],
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
            pass

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
