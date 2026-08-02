"""_run_tool's repeat guard (`seen`) — protects a round loop's tool budget from a model
stuck re-issuing the exact same failing call (root cause of a real "Corté el loop: máximo
de rondas de tools" incident: vault_search down + the model retrying list_dir with wrong
paths until max_rounds ran out).

Tools execution itself is mocked out (via tools.execute) since these tests only cover the
guard's own logic, not any particular tool's behavior.
"""
import clients
import tools


def _fake_execute(monkeypatch):
    calls = []

    def fake(name, args):
        calls.append((name, args))
        return "ok"

    monkeypatch.setattr(tools, "execute", fake)
    return calls


def test_sin_seen_ejecuta_siempre(monkeypatch):
    calls = _fake_execute(monkeypatch)
    clients._run_tool("run_cmd", {"command": "true"}, bridge=None)
    clients._run_tool("run_cmd", {"command": "true"}, bridge=None)
    assert len(calls) == 2  # comportamiento previo intacto cuando no se pasa seen


def test_con_seen_primera_vez_ejecuta(monkeypatch):
    calls = _fake_execute(monkeypatch)
    seen = set()
    result = clients._run_tool("run_cmd", {"command": "true"}, bridge=None, seen=seen)
    assert result == "ok"
    assert len(calls) == 1
    assert ("run_cmd", '{"command": "true"}') in seen


def test_con_seen_repeticion_exacta_no_reejecuta(monkeypatch):
    calls = _fake_execute(monkeypatch)
    seen = set()
    clients._run_tool("run_cmd", {"command": "true"}, bridge=None, seen=seen)
    repeated = clients._run_tool("run_cmd", {"command": "true"}, bridge=None, seen=seen)
    assert len(calls) == 1  # la segunda no llegó a ejecutar
    assert "Ya llamaste a run_cmd" in repeated
    assert "no lo repitas" in repeated.lower()


def test_con_seen_args_distintos_no_se_bloquea(monkeypatch):
    calls = _fake_execute(monkeypatch)
    seen = set()
    clients._run_tool("run_cmd", {"command": "true"}, bridge=None, seen=seen)
    other = clients._run_tool("run_cmd", {"command": "false"}, bridge=None, seen=seen)
    assert len(calls) == 2
    assert "Ya llamaste" not in other


def test_con_seen_orden_de_claves_no_importa(monkeypatch):
    calls = _fake_execute(monkeypatch)
    seen = set()
    clients._run_tool("write_file", {"path": "a.txt", "content": "x"}, bridge=None, seen=seen)
    repeated = clients._run_tool(
        "write_file", {"content": "x", "path": "a.txt"}, bridge=None, seen=seen)
    assert len(calls) == 1
    assert "Ya llamaste" in repeated
