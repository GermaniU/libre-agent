"""The shared turn loop (agent.run_turn) — event contract, used by all 3 gateways.

clients (network/ollama) and finalize (memory/trace) are mocked so this is a pure
unit test of the orchestration and its event sequence.
"""
import agent
import clients


def _fake_finalize(*a, **k):
    return [], {"gen": 5, "total": 10, "secs": 1.0, "tps": 5.0}


def test_streaming_event_sequence(monkeypatch):
    monkeypatch.setattr(agent, "finalize", _fake_finalize)

    def fake_stream(model, messages, **kw):
        yield ("token", "ho")
        yield ("tool", ("web_search", {"query": "x"}))
        yield ("done", {"reply": "hola", "calls": [{"tool": "web_search", "args": {}, "result": "r"}],
                        "usage": {"total": 10, "gen": 5, "ctx": 10}})

    monkeypatch.setattr(clients, "chat_stream_with_tools", fake_stream)
    events = list(agent.run_turn("m", [{"role": "user", "content": "hi"}], "hi", "soul",
                                 use_memory=False, stream=True))
    assert [e["type"] for e in events] == ["recall", "token", "tool", "done"]
    done = events[-1]
    assert done["reply"] == "hola"
    assert done["error"] is None
    assert done["calls"][0]["tool"] == "web_search"
    assert done["meta"]["tps"] == 5.0


def test_non_streaming_has_no_tokens(monkeypatch):
    monkeypatch.setattr(agent, "finalize", lambda *a, **k: (["un hecho"], {"gen": 1, "total": 2, "secs": 0.5, "tps": 2.0}))
    monkeypatch.setattr(clients, "chat_with_tools",
                        lambda model, messages, **kw: ("respuesta", [], {"total": 2, "gen": 1, "ctx": 2}))
    events = list(agent.run_turn("m", [{"role": "user", "content": "hi"}], "hi", "soul",
                                 use_memory=False, stream=False))
    assert [e["type"] for e in events] == ["recall", "done"]
    assert events[-1]["saved_facts"] == ["un hecho"]


def test_model_error_yields_error_and_done(monkeypatch):
    monkeypatch.setattr(agent, "finalize", _fake_finalize)

    def boom(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(clients, "chat_stream_with_tools", boom)
    events = list(agent.run_turn("m", [{"role": "user", "content": "hi"}], "hi", "soul",
                                 use_memory=False, stream=True))
    types = [e["type"] for e in events]
    assert types == ["recall", "error", "done"]
    assert events[-1]["error"] == "ollama down"
    assert "Error del modelo" in events[-1]["reply"]
