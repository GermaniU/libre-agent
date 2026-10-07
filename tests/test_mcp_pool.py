"""mcp_bridge pool — MCP connections are reused across turns instead of rebuilt per message.

MCPBridge is replaced by a fake (no processes, no network) that counts connections and
closes, so these tests cover only the pool's own bookkeeping: reuse, not caching failed
connections, evicting dead ones, and resetting after mcp.json changes.
"""
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

import mcp_bridge


class FakeBridge:
    created, closed = [], []
    down = set()  # servers that fail to connect

    def __init__(self, servers):
        (name,) = servers
        self.name = name
        self.errors = {name: "ConnectionError: nope"} if name in FakeBridge.down else {}
        self.tools = {} if self.errors else {f"{name}__ping": (None, "ping")}
        self.specs = [] if self.errors else [{"function": {"name": f"{name}__ping"}}]
        self.fail_with = None
        FakeBridge.created.append(name)

    def call(self, qname, args, timeout=300):
        if self.fail_with:
            raise self.fail_with
        return f"pong de {self.name}"

    def close(self):
        FakeBridge.closed.append(self.name)


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    FakeBridge.created, FakeBridge.closed, FakeBridge.down = [], [], set()
    monkeypatch.setattr(mcp_bridge, "MCPBridge", FakeBridge)
    monkeypatch.setattr(mcp_bridge, "_pool", {})
    return FakeBridge


def test_reusa_la_conexion_entre_turnos(fake):
    mcp_bridge.pooled(["a"])
    mcp_bridge.pooled(["a"])
    assert fake.created == ["a"]
    assert fake.closed == []


def test_combina_tools_de_varios_servers_y_despacha(fake):
    b = mcp_bridge.pooled(["b", "a", "a"])
    assert sorted(b.tools) == ["a__ping", "b__ping"]
    assert len(b.specs) == 2
    assert b.connected == ["a", "b"]
    assert b.call("b__ping", {}) == "pong de b"


def test_server_caido_no_se_cachea_y_se_reintenta(fake):
    fake.down = {"x"}
    b = mcp_bridge.pooled(["x", "a"])
    assert "x" in b.errors and b.connected == ["a"]
    assert "x__ping" not in b.tools
    assert "x" in fake.closed
    fake.down = set()
    assert "x__ping" in mcp_bridge.pooled(["x"]).tools  # came up later → connects now
    assert fake.created.count("x") == 2


def test_llamada_que_revienta_desaloja_y_reconecta(fake):
    b = mcp_bridge.pooled(["a"])
    mcp_bridge._pool["a"].fail_with = BrokenPipeError("server muerto")
    with pytest.raises(BrokenPipeError):
        b.call("a__ping", {})
    assert "a" not in mcp_bridge._pool and fake.closed == ["a"]
    mcp_bridge.pooled(["a"])
    assert fake.created == ["a", "a"]


def test_error_de_protocolo_no_desaloja(fake):
    b = mcp_bridge.pooled(["a"])
    mcp_bridge._pool["a"].fail_with = McpError(ErrorData(code=-32602, message="bad params"))
    with pytest.raises(McpError):
        b.call("a__ping", {})
    assert "a" in mcp_bridge._pool and fake.closed == []


def test_desalojo_viejo_no_borra_la_conexion_nueva(fake):
    viejo = mcp_bridge.pooled(["a"])
    viejo_bridge = mcp_bridge._pool["a"]
    mcp_bridge.reset_pool("a")
    mcp_bridge.pooled(["a"])  # a new live connection
    viejo_bridge.fail_with = BrokenPipeError()
    with pytest.raises(BrokenPipeError):
        viejo.call("a__ping", {})
    assert mcp_bridge._pool["a"] is not viejo_bridge  # the new one survives


def test_reset_pool(fake):
    mcp_bridge.pooled(["a", "b"])
    mcp_bridge.reset_pool("a")
    assert set(mcp_bridge._pool) == {"b"}
    mcp_bridge.reset_pool()
    assert mcp_bridge._pool == {}
    assert sorted(fake.closed) == ["a", "b"]
