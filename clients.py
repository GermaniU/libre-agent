"""Clientes HTTP para ollama (modelos locales) y el corpus (RAG del vault)."""
import json
import requests
import config


# ---------------------------------------------------------------- Ollama
def list_local_models():
    """Devuelve TODOS los modelos locales (excluye solo :cloud).

    Cada item: {name, size, gb, kind, fits}  kind in {chat, vision, embed};
    fits=False si no entra en la VRAM (correría parcialmente en CPU, lento).
    """
    r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=8)
    r.raise_for_status()
    out = []
    for m in r.json().get("models", []):
        name = m["name"]
        size = m.get("size", 0)
        if name.endswith(":cloud") or "cloud" in name:
            continue  # solo local
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
    return out


def chat_stream(model, messages, temperature=0.4):
    """Genera la respuesta del modelo local en streaming (yield de tokens)."""
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
    """Ventana de contexto del modelo: la cargada en runtime si está corriendo, si no la del modelfile."""
    try:
        for m in requests.get(f"{config.OLLAMA_URL}/api/ps", timeout=5).json().get("models", []):
            if m.get("name") == model and m.get("context_length"):
                return m["context_length"]
    except Exception:
        pass
    try:
        info = requests.post(f"{config.OLLAMA_URL}/api/show",
                             json={"model": model}, timeout=8).json().get("model_info", {})
        for k, v in info.items():
            if k.endswith(".context_length"):
                return v
    except Exception:
        pass
    return None


def _ctx_estimate(msgs, measured):
    # con kv-cache caliente prompt_eval_count solo cuenta tokens nuevos;
    # cubrimos ese caso estimando por caracteres (~4 chars/token)
    by_chars = sum(len(str(m.get("content") or "")) for m in msgs) // 4
    return max(measured, by_chars)


def _err_text(resp):
    """Texto del error de ollama en minúsculas (o '' si la respuesta fue OK)."""
    if resp.status_code < 400:
        return ""
    try:
        return (resp.json().get("error") or "").lower()
    except Exception:
        return resp.text.lower()


def chat_with_tools(model, messages, temperature=0.4, max_rounds=6, on_tool=None, bridge=None,
                    use_tools=True, think=None):
    """Loop de agente: el modelo pide tools, las ejecutamos y le devolvemos el resultado.

    Devuelve (respuesta_final, log_de_tool_calls, usage). usage = {"total": tokens
    procesados en todas las rondas, "ctx": contexto ocupado al final, "rounds": n}.
    on_tool(name, args) se llama antes de ejecutar cada tool. bridge es un
    MCPBridge opcional cuyas tools se suman a las locales.

    use_tools=False → chat puro: no se ofrecen tools, el modelo responde solo con su
    conocimiento. think: None=default del modelo, True/False fuerza el modo razonamiento
    (think=False acelera modelos de razonamiento). Si el modelo no
    soporta tools o thinking, se quita esa opción y se reintenta (fallback sin romper).
    """
    import tools
    specs = (tools.SPECS + (bridge.specs if bridge else [])) if use_tools else None
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
        # degradación elegante: si el modelo no soporta tools o thinking, quitamos esa
        # opción (para ésta y las próximas rondas) y reintentamos, sin tirar error.
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
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return msg.get("content", ""), calls_log, usage
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
                           use_tools=True, think=None):
    """Igual que chat_with_tools pero en STREAMING: es un generador de eventos.

    Yields tuplas (kind, payload):
      ("token", str)        -> un pedazo de la respuesta final (para pintar en vivo)
      ("tool",  (name,args))-> se va a ejecutar una tool
      ("done",  {"reply","calls","usage"}) -> fin, con el resultado completo
    Resuelve las rondas de tools en streaming; los tokens del texto final salen en vivo.
    """
    import tools
    specs = (tools.SPECS + (bridge.specs if bridge else [])) if use_tools else None
    msgs = list(messages)
    calls_log = []
    usage = {"total": 0, "ctx": 0, "rounds": 0, "gen": 0}
    for _ in range(max_rounds):
        payload = {"model": model, "messages": msgs, "stream": True, "keep_alive": "30m",
                   "options": {"temperature": temperature}}
        if specs:
            payload["tools"] = specs
        if think is not None:
            payload["think"] = think

        # abrir el stream, con degradación elegante si el modelo no soporta tools/thinking
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
        usage["ctx"] = _ctx_estimate(msgs + [{"role": "assistant", "content": content}], usage["total"])

        if not tool_calls:
            yield ("done", {"reply": content, "calls": calls_log, "usage": usage})
            return
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
    """Busca en Qdrant (vía API del corpus) y normaliza los hits."""
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
    """Arma el bloque de contexto citado que se inyecta al modelo local."""
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
        return False
