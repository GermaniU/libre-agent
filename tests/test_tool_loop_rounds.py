"""Tool-loop invariants shared by every backend loop in clients.py.

- The LAST round never offers tools, so the model must synthesize an answer instead of
  ending the turn with "Corté el loop" (was only enforced on the llama.cpp loops).
- Truncated/malformed tool-call JSON is never executed with {} (was only enforced on the
  llama.cpp streaming loop).
- ``options`` (num_ctx, top_p…) and ``max_rounds`` reach every backend.

The network (requests.post) and tool execution (tools.execute) are mocked.
"""
import json

import pytest

import clients
import config
import tools

_dumps = json.dumps  # fake_post's `json=` kwarg shadows the module


class _Resp:
    def __init__(self, body=None, lines=None):
        self.status_code = 200
        self._body = body
        self._lines = lines or []

    def json(self):
        return self._body

    def iter_lines(self):
        yield from self._lines

    def raise_for_status(self):
        pass


@pytest.fixture
def ollama_only(monkeypatch):
    """Route every model to ollama (no llama.cpp backend)."""
    monkeypatch.setattr(config, "LLAMACPP_URL", "")
    monkeypatch.setattr(clients, "_openai_models", {})


@pytest.fixture
def executed(monkeypatch):
    calls = []

    def fake(name, args):
        calls.append((name, args))
        return "ok"

    monkeypatch.setattr(tools, "execute", fake)
    return calls


def _ollama_msg(payload, n):
    """A model that calls a tool whenever tools are offered, and answers otherwise."""
    if payload.get("tools"):
        return {"role": "assistant", "content": "",
                "tool_calls": [{"function": {"name": "list_dir", "arguments": {"path": str(n)}}}]}
    return {"role": "assistant", "content": "respuesta final"}


def test_ollama_ultima_ronda_sin_tools(ollama_only, executed, monkeypatch):
    payloads = []

    def fake_post(url, json=None, **kw):
        payloads.append(json)
        return _Resp({"message": _ollama_msg(json, len(payloads)),
                      "prompt_eval_count": 1, "eval_count": 1})

    monkeypatch.setattr(clients.requests, "post", fake_post)
    reply, calls_log, usage = clients.chat_with_tools(
        "m", [{"role": "user", "content": "hi"}], max_rounds=3)
    assert reply == "respuesta final"
    assert len(executed) == 2
    assert usage["rounds"] == 3
    assert "tools" in payloads[0] and "tools" in payloads[1]
    assert "tools" not in payloads[-1]


def test_ollama_stream_ultima_ronda_sin_tools(ollama_only, executed, monkeypatch):
    payloads = []

    def fake_post(url, json=None, **kw):
        payloads.append(json)
        msg = _ollama_msg(json, len(payloads))
        line = {"message": msg, "done": True, "prompt_eval_count": 1, "eval_count": 1}
        return _Resp(lines=[_dumps(line)])

    monkeypatch.setattr(clients.requests, "post", fake_post)
    events = list(clients.chat_stream_with_tools(
        "m", [{"role": "user", "content": "hi"}], max_rounds=3))
    kind, done = events[-1]
    assert kind == "done"
    assert done["reply"] == "respuesta final"
    assert len(executed) == 2
    assert "tools" not in payloads[-1]


def test_ollama_options_llegan_sin_streaming(ollama_only, monkeypatch):
    payloads = []

    def fake_post(url, json=None, **kw):
        payloads.append(json)
        return _Resp({"message": {"role": "assistant", "content": "ok"}})

    monkeypatch.setattr(clients.requests, "post", fake_post)
    clients.chat_with_tools("m", [{"role": "user", "content": "hi"}],
                            use_tools=False, options={"num_ctx": 8192})
    assert payloads[0]["options"]["num_ctx"] == 8192


def _openai_post(responses, payloads):
    it = iter(responses)

    def fake_post(url, json=None, **kw):
        payloads.append(json)
        return _Resp(next(it))
    return fake_post


def _openai_body(content="", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg}], "usage": {"total_tokens": 1, "completion_tokens": 1}}


def test_openai_json_truncado_no_ejecuta_con_args_vacios(executed, monkeypatch):
    payloads = []
    truncated = [{"function": {"name": "write_file", "arguments": '{"path": "a.txt", "conte'}}]
    monkeypatch.setattr(clients.requests, "post", _openai_post(
        [_openai_body(tool_calls=truncated), _openai_body("listo")], payloads))
    reply, calls_log, _ = clients._openai_call(
        "http://x/v1", "m", [{"role": "user", "content": "hi"}], specs=tools.SPECS, max_rounds=3)
    assert reply == "listo"
    assert executed == []  # never ran write_file with {}
    assert "JSON inválido" in calls_log[0]["result"]


def test_openai_recibe_options_y_max_rounds(monkeypatch):
    payloads = []
    monkeypatch.setattr(clients, "_openai_models", {"m": "http://x/v1"})
    call = [{"function": {"name": "list_dir", "arguments": _dumps({"path": "."})}}]
    monkeypatch.setattr(clients.requests, "post", _openai_post(
        [_openai_body(tool_calls=call), _openai_body("fin")], payloads))
    monkeypatch.setattr(tools, "execute", lambda n, a: "ok")
    reply, _, usage = clients.chat_with_tools(
        "m", [{"role": "user", "content": "hi"}], max_rounds=2, options={"top_p": 0.9})
    assert reply == "fin"
    assert payloads[0]["top_p"] == 0.9
    assert "tools" in payloads[0]
    assert "tools" not in payloads[1]  # max_rounds=2 honored: round 2 is the last one


def test_max_rounds_por_defecto_sale_de_config(ollama_only, executed, monkeypatch):
    payloads = []

    def fake_post(url, json=None, **kw):
        payloads.append(json)
        return _Resp({"message": _ollama_msg(json, len(payloads))})

    monkeypatch.setattr(config, "MAX_TOOL_ROUNDS", 2)
    monkeypatch.setattr(clients.requests, "post", fake_post)
    reply, _, usage = clients.chat_with_tools("m", [{"role": "user", "content": "hi"}])
    assert reply == "respuesta final"
    assert usage["rounds"] == 2
    assert "tools" not in payloads[-1]
