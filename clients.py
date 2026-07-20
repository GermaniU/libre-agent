"""HTTP clients for ollama (local models) and the corpus (vault RAG)."""
import json
import logging

import requests

import config

log = logging.getLogger("localagent.clients")


def _parse_text_tool_calls(text):
    """Rescue tool calls that a model emitted as TEXT instead of ollama's structured field.

    Hermes/Qwen-style models write e.g. ``<tool_call>{"name": "...", "arguments": {...}}
    </tool_call>`` (sometimes only the closing tag). Returns them in ollama's structured
    shape, or [] if there are none. Gated on a ``<tool_call>`` / ``</tool_call>`` marker so
    plain JSON inside a normal answer is never misread as a tool call. Uses the JSON decoder
    (not a regex) so nested objects and braces inside strings parse correctly.
    """
    text = text or ""
    if "tool_call>" not in text:
        return []
    out = []
    decoder = json.JSONDecoder()
    parts = text.split("</tool_call>")
    for i, segment in enumerate(parts):
        ended_with_close = i < len(parts) - 1
        if not ended_with_close and "<tool_call>" not in segment:
            continue
        chunk = segment.rsplit("<tool_call>", 1)[-1]
        start = chunk.find("{")
        if start < 0:
            continue
        try:
            obj, _ = decoder.raw_decode(chunk[start:].strip())
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("name"):
            args = obj.get("arguments", obj.get("parameters", {}))
            out.append({"function": {"name": obj["name"], "arguments": args}})
    return out


# Model id -> OpenAI base URL, for models served by an extra OpenAI-compatible backend
# (llama.cpp). Populated by list_local_models(); used to route chat to the right backend.
_openai_models = {}


def _list_openai_models():
    """Models exposed by the OpenAI-compatible backend (llama.cpp), or [] if unreachable.

    Also (re)populates the _openai_models registry so chat can route to it.
    """
    base = config.LLAMACPP_URL
    if not base:
        return []
    try:
        r = requests.get(f"{base}/models", timeout=3)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception:
        log.debug("OpenAI backend not reachable at %s", base, exc_info=True)
        return []
    out = []
    for m in data:
        mid = m.get("id")
        if not mid:
            continue
        _openai_models[mid] = base
        # fits=True: llama.cpp already loaded it in the configured VRAM budget
        out.append({"name": mid, "size": 0, "gb": 0, "kind": "chat",
                    "fits": True, "backend": "llama.cpp"})
    return out


# ---------------------------------------------------------------- Ollama
def list_local_models():
    """Returns ALL local models (ollama + any OpenAI-compatible backend; excludes :cloud).

    Each item: {name, size, gb, kind, fits}  kind in {chat, vision, embed};
    fits=False if it does not fit in VRAM (would run partially on CPU, slow).
    """
    r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=8)
    r.raise_for_status()
    out = []
    for m in r.json().get("models", []):
        name = m["name"]
        size = m.get("size", 0)
        if name.endswith(":cloud") or "cloud" in name:
            continue  # local only
        low = name.lower()
        if any(h in low for h in config.EMBED_HINT):
            kind = "embed"
        elif any(h in low for h in config.VISION_HINT):
            kind = "vision"
        else:
            kind = "chat"
        out.append({"name": name, "size": size, "gb": round(size / 1024**3, 1),
                    "kind": kind, "fits": size <= config.FIT_BYTES})
    out.sort(key=lambda x: x["name"])
    return out + _list_openai_models()


def chat_stream(model, messages, temperature=0.4):
    """Generates the local model's response in streaming (yields tokens)."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temperature},
    }
    with requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload, stream=True, timeout=300) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            tok = data.get("message", {}).get("content", "")
            if tok:
                yield tok
            if data.get("done"):
                break


def context_limit(model):
    """Model's context window: the one loaded at runtime if running, otherwise the modelfile's."""
    try:
        for m in requests.get(f"{config.OLLAMA_URL}/api/ps", timeout=5).json().get("models", []):
            if m.get("name") == model and m.get("context_length"):
                return m["context_length"]
    except Exception:
        log.debug("could not read running context length for %r", model, exc_info=True)
    try:
        info = requests.post(f"{config.OLLAMA_URL}/api/show",
                             json={"model": model}, timeout=8).json().get("model_info", {})
        for k, v in info.items():
            if k.endswith(".context_length"):
                return v
    except Exception:
        log.debug("could not read modelfile context length for %r", model, exc_info=True)
    return config.DEFAULT_CTX  # backend didn't report one (e.g. llama.cpp) -> sane default


def _ctx_estimate(msgs, measured):
    # with a warm kv-cache prompt_eval_count only counts new tokens;
    # we cover that case by estimating from characters (~4 chars/token)
    by_chars = sum(len(str(m.get("content") or "")) for m in msgs) // 4
    return max(measured, by_chars)


def _err_text(resp):
    """Ollama's error text in lowercase (or '' if the response was OK)."""
    if resp.status_code < 400:
        return ""
    try:
        return (resp.json().get("error") or "").lower()
    except Exception:
        return resp.text.lower()


# ---------------------------------------------------------------- OpenAI-compatible backend (llama.cpp)
def _is_openai(model):
    """True if `model` is served by the OpenAI-compatible backend (llama.cpp)."""
    if model in _openai_models:
        return True
    if config.LLAMACPP_URL and not _openai_models:  # registry not populated yet
        _list_openai_models()
    return model in _openai_models


def _openai_payload(model, messages, temperature, options, think=None):
    payload = {"model": model, "messages": messages, "temperature": temperature}
    opts = options or {}
    if opts.get("top_p") is not None:
        payload["top_p"] = opts["top_p"]
    if opts.get("num_predict"):
        payload["max_tokens"] = opts["num_predict"]
    # snappy assistant by default: disable the model's verbose reasoning unless the
    # user turned Thinking on. Qwen reads this via its chat template.
    if think is not True:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return payload


def _run_tool(name, args, bridge):
    """Execute a tool (MCP bridge or local) and return its string result."""
    import tools as tools_mod
    if isinstance(args, dict) and "__invalid_json__" in args:
        raw = args["__invalid_json__"]
        return (f"Error: los arguments de {name} llegaron como JSON inválido o truncado "
                f"({len(raw)} chars; cola: …{raw[-120:]}). Probablemente la generación se "
                "cortó por max_tokens. Reintenta con un contenido más corto o en partes.")
    if bridge and name in bridge.tools:
        try:
            return bridge.call(name, args)
        except Exception as e:
            return f"Error ejecutando {name}: {e}"
    return tools_mod.execute(name, args)


def _openai_collect_calls(streamed, content, specs):
    """[{name, args}] from streamed OpenAI tool_calls; falls back to <tool_call> text."""
    calls = []
    for idx in sorted(streamed):
        slot = streamed[idx]
        if not slot["name"]:
            continue
        try:
            args = json.loads(slot["args"]) if slot["args"].strip() else {}
        except ValueError:
            # truncated (max_tokens) or malformed JSON: never execute with {} — tag it so
            # _run_tool can tell the model what happened and it can retry sensibly
            args = {"__invalid_json__": slot["args"]}
        calls.append({"name": slot["name"], "args": args})
    if not calls and specs:  # some models write the tool call as text instead
        calls = [{"name": tc["function"]["name"], "args": tc["function"]["arguments"]}
                 for tc in _parse_text_tool_calls(content)]
    return calls


def _openai_assistant_turn(calls):
    """OpenAI-style tool_calls list for the assistant message that requested them."""
    return [{"id": f"call_{i}", "type": "function",
             "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
            for i, c in enumerate(calls)]


def _openai_stream(base, model, messages, temperature=0.4, options=None, think=None,
                   specs=None, bridge=None, max_rounds=6):
    """Stream a chat from an OpenAI-compatible backend, WITH tool support.

    Yields ("token", str), ("tool", (name, args)) and a final ("done", {reply, calls, usage}).
    """
    msgs = list(messages)
    calls_log = []
    usage = {"total": 0, "ctx": 0, "rounds": 0, "gen": 0}
    for _ in range(max_rounds):
        payload = _openai_payload(model, msgs, temperature, options, think)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        if specs:
            payload["tools"] = specs
        r = requests.post(f"{base}/chat/completions", json=payload, stream=True, timeout=600)
        r.raise_for_status()
        parts, reasoning, streamed = [], [], {}
        for raw in r.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            choices = obj.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                # reasoning models split thinking into reasoning_content; stream it for
                # live feedback, but the final reply is the answer (content)
                rtok = delta.get("reasoning_content")
                if rtok:
                    reasoning.append(rtok)
                    yield ("token", rtok)
                token = delta.get("content")
                if token:
                    parts.append(token)
                    yield ("token", token)
                for tc in (delta.get("tool_calls") or []):  # arrive fragmented, by index
                    slot = streamed.setdefault(tc.get("index", 0), {"name": "", "args": ""})
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]
            u = obj.get("usage")
            if u:
                usage["total"] = usage["ctx"] = u.get("total_tokens", 0)
                usage["gen"] += u.get("completion_tokens", 0)
        usage["rounds"] += 1
        content = "".join(parts)
        calls = _openai_collect_calls(streamed, content, specs)
        if not calls:
            yield ("done", {"reply": content or "".join(reasoning), "calls": calls_log, "usage": usage})
            return
        oai = _openai_assistant_turn(calls)
        msgs.append({"role": "assistant", "content": content, "tool_calls": oai})
        for i, c in enumerate(calls):
            yield ("tool", (c["name"], c["args"]))
            result = _run_tool(c["name"], c["args"], bridge)
            calls_log.append({"tool": c["name"], "args": c["args"], "result": result})
            msgs.append({"role": "tool", "tool_call_id": oai[i]["id"], "content": str(result)})
    yield ("done", {"reply": "⚠️ Corté el loop: máximo de rondas de tools.",
                    "calls": calls_log, "usage": usage})


def _openai_call(base, model, messages, temperature=0.4, options=None, think=None,
                 specs=None, bridge=None, on_tool=None, max_rounds=6):
    """Non-streaming chat from an OpenAI-compatible backend, WITH tool support.

    Returns (reply, tool_calls_log, usage).
    """
    msgs = list(messages)
    calls_log = []
    usage = {"total": 0, "ctx": 0, "rounds": 0, "gen": 0}
    for _ in range(max_rounds):
        payload = _openai_payload(model, msgs, temperature, options, think)
        if specs:
            payload["tools"] = specs
        r = requests.post(f"{base}/chat/completions", json=payload, timeout=600)
        r.raise_for_status()
        d = r.json()
        u = d.get("usage", {})
        usage["total"] = usage["ctx"] = u.get("total_tokens", 0)
        usage["gen"] += u.get("completion_tokens", 0)
        usage["rounds"] += 1
        msg = d["choices"][0]["message"]
        content = msg.get("content") or ""
        calls = []
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            if not fn.get("name"):
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append({"name": fn["name"], "args": args})
        if not calls and specs:
            calls = [{"name": tc["function"]["name"], "args": tc["function"]["arguments"]}
                     for tc in _parse_text_tool_calls(content)]
        if not calls:
            return content, calls_log, usage
        oai = _openai_assistant_turn(calls)
        msgs.append({"role": "assistant", "content": content, "tool_calls": oai})
        for i, c in enumerate(calls):
            if on_tool:
                on_tool(c["name"], c["args"])
            result = _run_tool(c["name"], c["args"], bridge)
            calls_log.append({"tool": c["name"], "args": c["args"], "result": result})
            msgs.append({"role": "tool", "tool_call_id": oai[i]["id"], "content": str(result)})
    return "⚠️ Corté el loop: máximo de rondas de tools.", calls_log, usage


def chat_with_tools(model, messages, temperature=0.4, max_rounds=6, on_tool=None, bridge=None,
                    use_tools=True, think=None):
    """Agent loop: the model requests tools, we execute them and return the result.

    Returns (final_response, tool_calls_log, usage). usage = {"total": tokens
    processed across all rounds, "ctx": context used at the end, "rounds": n}.
    on_tool(name, args) is called before executing each tool. bridge is an
    optional MCPBridge whose tools are added to the local ones.

    use_tools=False → pure chat: no tools are offered, the model responds only with its
    own knowledge. think: None=model default, True/False forces reasoning mode
    (think=False speeds up reasoning models). If the model does not
    support tools or thinking, that option is removed and it retries (fallback without breaking).
    """
    import tools
    specs = (tools.SPECS + (bridge.specs if bridge else [])) if use_tools else None
    if _is_openai(model):  # OpenAI-compatible backend (llama.cpp)
        return _openai_call(_openai_models[model], model, messages, temperature,
                            think=think, specs=specs, bridge=bridge, on_tool=on_tool)
    msgs = list(messages)
    calls_log = []
    usage = {"total": 0, "ctx": 0, "rounds": 0, "gen": 0}
    for _ in range(max_rounds):
        payload = {"model": model, "messages": msgs, "stream": False, "keep_alive": "30m",
                   "options": {"temperature": temperature}}
        if specs:
            payload["tools"] = specs
        if think is not None:
            payload["think"] = think
        r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=600)
        # graceful degradation: if the model does not support tools or thinking, we remove that
        # option (for this and the next rounds) and retry, without raising an error.
        for _attempt in range(2):
            err = _err_text(r)
            if not err:
                break
            changed = False
            if specs and "support tools" in err:
                specs, changed = None, True
                payload.pop("tools", None)
            if think is not None and "think" in err:
                think, changed = None, True
                payload.pop("think", None)
            if not changed:
                break
            r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=600)
        r.raise_for_status()
        data = r.json()
        msg = data["message"]
        step = data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
        usage["total"] += step
        usage["gen"] += data.get("eval_count", 0)
        usage["rounds"] += 1
        usage["ctx"] = _ctx_estimate(msgs + [msg], step)
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            parsed = _parse_text_tool_calls(content) if specs else []
            if not parsed:
                return content, calls_log, usage
            # model wrote the tool call as text; rescue it and run it
            tool_calls = parsed
            msgs.append({"role": "assistant", "content": content})
        else:
            msgs.append(msg)
        for tc in tool_calls:
            fn = tc.get("function", {})
            name, args = fn.get("name", "?"), fn.get("arguments") or {}
            if on_tool:
                on_tool(name, args)
            if bridge and name in bridge.tools:
                try:
                    result = bridge.call(name, args)
                except Exception as e:
                    result = f"Error ejecutando {name}: {e}"
            else:
                result = tools.execute(name, args)
            calls_log.append({"tool": name, "args": args, "result": result})
            msgs.append({"role": "tool", "tool_name": name, "content": result})
    return "⚠️ Corté el loop: se alcanzó el máximo de rondas de tools.", calls_log, usage


def chat_stream_with_tools(model, messages, temperature=0.4, max_rounds=6, bridge=None,
                           use_tools=True, think=None, options=None):
    """Same as chat_with_tools but STREAMING: it's an event generator.

    Yields tuples (kind, payload):
      ("token", str)        -> a chunk of the final response (to render live)
      ("tool",  (name,args))-> a tool is about to be executed
      ("done",  {"reply","calls","usage"}) -> end, with the complete result
    Resolves the tool rounds in streaming; the final text tokens come out live.
    """
    import tools
    specs = (tools.SPECS + (bridge.specs if bridge else [])) if use_tools else None
    if _is_openai(model):  # OpenAI-compatible backend (llama.cpp)
        yield from _openai_stream(_openai_models[model], model, messages, temperature,
                                  options, think, specs=specs, bridge=bridge)
        return
    msgs = list(messages)
    calls_log = []
    usage = {"total": 0, "ctx": 0, "rounds": 0, "gen": 0}
    for _ in range(max_rounds):
        payload = {"model": model, "messages": msgs, "stream": True, "keep_alive": "30m",
                   "options": {"temperature": temperature, **(options or {})}}
        if specs:
            payload["tools"] = specs
        if think is not None:
            payload["think"] = think

        # open the stream, with graceful degradation if the model does not support tools/thinking
        r = None
        for _attempt in range(3):
            r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload, stream=True, timeout=600)
            if r.status_code < 400:
                break
            err = _err_text(r)
            changed = False
            if specs and "support tools" in err:
                specs, changed = None, True
                payload.pop("tools", None)
            if think is not None and "think" in err:
                think, changed = None, True
                payload.pop("think", None)
            if not changed:
                break
        r.raise_for_status()

        content_parts, tool_calls, step, gen = [], [], 0, 0
        for line in r.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            if data.get("error"):
                raise RuntimeError(f"Ollama: {data['error']}")
            msg = data.get("message", {})
            tok = msg.get("content", "")
            if tok:
                content_parts.append(tok)
                yield ("token", tok)
            if msg.get("tool_calls"):
                tool_calls.extend(msg["tool_calls"])
            if data.get("done"):
                step = data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
                gen = data.get("eval_count", 0)
        content = "".join(content_parts)
        usage["total"] += step
        usage["gen"] += gen
        usage["rounds"] += 1
        usage["ctx"] = _ctx_estimate(msgs + [{"role": "assistant", "content": content}], step)

        if not tool_calls:
            parsed = _parse_text_tool_calls(content) if specs else []
            if not parsed:
                yield ("done", {"reply": content, "calls": calls_log, "usage": usage})
                return
            # model wrote the tool call as text; rescue it and run it
            tool_calls = parsed
            msgs.append({"role": "assistant", "content": content})
        else:
            msgs.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function", {})
            name, args = fn.get("name", "?"), fn.get("arguments") or {}
            yield ("tool", (name, args))
            if bridge and name in bridge.tools:
                try:
                    result = bridge.call(name, args)
                except Exception as e:
                    result = f"Error ejecutando {name}: {e}"
            else:
                result = tools.execute(name, args)
            calls_log.append({"tool": name, "args": args, "result": result})
            msgs.append({"role": "tool", "tool_name": name, "content": result})
    yield ("done", {"reply": "⚠️ Corté el loop: máximo de rondas de tools.",
                    "calls": calls_log, "usage": usage})


# ---------------------------------------------------------------- Corpus / RAG
def corpus_search(query, limit=6):
    """Searches in Qdrant (via the corpus API) and normalizes the hits."""
    r = requests.post(
        f"{config.CORPUS_URL}/corpus/search",
        headers={"X-API-Key": config.CORPUS_KEY, "Content-Type": "application/json"},
        json={"q": query, "limit": limit},
        timeout=20,
    )
    r.raise_for_status()
    hits = r.json().get("hits", [])
    res = []
    for h in hits:
        p = h.get("payload", {})
        res.append({
            "file": p.get("filename", "?"),
            "page": p.get("page", "?"),
            "score": round(h.get("score", 0), 3),
            "text": (p.get("text") or "").strip(),
            "summary": (p.get("summary") or "").strip(),
        })
    return res


def build_rag_context(hits):
    """Builds the cited context block that gets injected into the local model."""
    blocks = []
    for i, h in enumerate(hits, 1):
        body = h["text"] or h["summary"]
        blocks.append(f"[{i} · {h['file']} · p.{h['page']}]\n{body}")
    return "\n\n".join(blocks)


def corpus_ok():
    try:
        requests.get(
            f"{config.CORPUS_URL}/health",
            headers={"X-API-Key": config.CORPUS_KEY},
            timeout=5,
        ).raise_for_status()
        return True
    except Exception:
        log.debug("corpus health check failed", exc_info=True)
        return False
