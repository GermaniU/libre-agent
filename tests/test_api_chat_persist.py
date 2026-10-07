"""/api/chat persistence — the turn is saved even if the client disconnects mid-stream.

When the browser goes away, the NDJSON generator is closed at a pending yield. Before,
persisting happened after the loop, so the user's message and the partial reply were
lost. StreamingResponse is patched to hand back the raw generator so the test can drive
(and close) it directly; run_turn is faked, and the store points to a temp DB.
"""
import json

import agent
import api
import store


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(api, "StreamingResponse", lambda gen, media_type=None: gen)
    monkeypatch.setattr(agent, "load_soul", lambda: "soul")

    def fake_turn(*a, **k):
        yield {"type": "recall", "count": 0, "facts": []}
        yield {"type": "token", "token": "hola "}
        yield {"type": "token", "token": "mundo"}
        yield {"type": "done", "reply": "hola mundo", "calls": [], "usage": {"total": 7},
               "meta": {}, "saved_facts": [], "error": None}

    monkeypatch.setattr(agent, "run_turn", fake_turn)
    return api.chat(api.ChatRequest(session="s", message="hi", model="m"))


def test_turno_completo_se_persiste(tmp_path, monkeypatch):
    events = [json.loads(line) for line in _setup(tmp_path, monkeypatch)]
    assert events[-1]["type"] == "done"
    sess = store.load_session("s")
    assert sess["messages"] == [{"role": "user", "content": "hi"},
                                {"role": "assistant", "content": "hola mundo"}]
    assert sess["tokens"] == 7


def test_desconexion_a_mitad_persiste_lo_parcial(tmp_path, monkeypatch):
    gen = _setup(tmp_path, monkeypatch)
    next(gen)  # recall
    next(gen)  # first token, then the client goes away
    gen.close()
    sess = store.load_session("s")
    assert sess["messages"][0] == {"role": "user", "content": "hi"}
    assert sess["messages"][1]["content"].startswith("hola")
    assert "interrumpida" in sess["messages"][1]["content"]


def test_desconexion_antes_de_tokens(tmp_path, monkeypatch):
    gen = _setup(tmp_path, monkeypatch)
    next(gen)  # recall only
    gen.close()
    msgs = store.load_session("s")["messages"]
    assert msgs[0]["content"] == "hi"
    assert msgs[1]["content"] == "⚠️ Respuesta interrumpida."
