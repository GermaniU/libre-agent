"""Shared agent core — what EVERY gateway (UI, bot, future ones) does the same way on
each turn: memory recall, system-prompt assembly, auto-save and tracing.

Keeping this here (instead of duplicated per channel) is what makes the gateways
maintainable: one place for a turn's logic, many frontends.
"""
import os
import time
import trace

import clients
import memory
import prompts
import skills

_DIR = os.path.dirname(os.path.abspath(__file__))


def load_soul() -> str:
    """Load the system prompt from prompts/soul.md, falling back to soul_fallback.md.

    Single source of truth for the soul so every gateway (UI, API, bot) stays in sync.
    """
    soul = prompts.load("soul.md")
    return soul or prompts.load("soul_fallback.md")


def compact_messages(messages, summary, keep=4):
    """Collapse an old conversation tail into a single summary message.

    Returns a new list: one assistant message carrying ``summary`` followed by the
    last ``keep`` messages of ``messages`` (kept verbatim for immediate context).
    If there aren't more than ``keep`` messages, returns ``messages`` unchanged
    (nothing to compact). Pure function: no I/O, no network.
    """
    if len(messages) <= keep:
        return messages
    recent = messages[-keep:] if keep > 0 else []
    summary_msg = {"role": "assistant", "content": "📝 Resumen de lo conversado antes:\n" + summary}
    return [summary_msg] + recent


def build_system(soul_text, prompt, use_memory=True, k=4):
    """Assemble the turn's system prompt: soul + available skills + recalled memories.

    Returns (system_text, recalled) where ``recalled`` is the list of memories used.
    """
    recalled = memory.recall(prompt, k=k) if use_memory else []
    system = soul_text + skills.catalog()
    if recalled:
        header = prompts.load("memory_recall_header.txt", "## Memory")
        system += "\n\n" + header + "\n" + "\n".join(f"- {m}" for m in recalled)
    return system, recalled


def run_turn(model, history, prompt, soul, *, channel="web", temperature=0.4,
             options=None, use_tools=True, think=None, use_memory=True,
             bridge=None, stream=True, on_tool=None):
    """Run one full agent turn as a generator of events. THE shared turn loop.

    Every gateway (SPA, Streamlit UI, Telegram bot) consumes these events and only
    handles its own transport (NDJSON / widgets / messages) and persistence. The core
    — system-prompt assembly, memory recall, the tool loop and auto-save/trace — lives
    here so the channels never diverge.

    ``history`` is the conversation so far (role/content dicts) INCLUDING the new user
    message. ``soul`` is the system prompt (the caller may override it per session).

    Yields event dicts by ``type``:
      {"type": "recall", "count": N, "facts": [...]}
      {"type": "token", "token": "..."}            (only when stream=True)
      {"type": "tool", "name": "...", "args": {...}}
      {"type": "error", "text": "..."}             (before the final done, on failure)
      {"type": "done", "reply", "calls", "usage", "meta", "saved_facts", "error"}
    """
    system, recalled = build_system(soul, prompt, use_memory)
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    yield {"type": "recall", "count": len(recalled), "facts": recalled}

    reply, calls_log = "", []
    usage = {"total": 0, "gen": 0, "ctx": 0}
    err_msg = None
    saved_ok = False
    t0 = time.time()
    try:
        if stream:
            for kind, pl in clients.chat_stream_with_tools(
                    model, messages, temperature=temperature, bridge=bridge,
                    use_tools=use_tools, think=think, options=options):
                if kind == "token":
                    yield {"type": "token", "token": pl}
                elif kind == "tool":
                    name, args = pl
                    yield {"type": "tool", "name": name, "args": args}
                elif kind == "done":
                    reply, calls_log, usage = pl["reply"], pl["calls"], pl["usage"]
        else:
            reply, calls_log, usage = clients.chat_with_tools(
                model, messages, temperature=temperature, bridge=bridge,
                use_tools=use_tools, think=think, on_tool=on_tool)
        saved_ok = True
    except Exception as e:
        err_msg = str(e)
        reply = f"⚠️ Error del modelo local: {e}"
        yield {"type": "error", "text": reply}

    secs = time.time() - t0
    saved_facts, meta = finalize(channel, prompt, reply, calls_log, usage, secs, model,
                                 use_memory=use_memory and saved_ok, recalled=recalled,
                                 error=err_msg)
    yield {"type": "done", "reply": reply, "calls": calls_log, "usage": usage,
           "meta": meta, "saved_facts": saved_facts, "error": err_msg}


def finalize(channel, prompt, reply, calls, usage, secs, model,
             use_memory=True, recalled=None, error=None):
    """Post-turn work common to all channels: memory auto-save + tracing.

    Returns (saved_facts, meta). meta = {gen, total, secs, tps} to show in the UI/bot.
    """
    gen = usage.get("gen", usage.get("total", 0))
    meta = {"gen": gen, "total": usage.get("total", 0), "secs": round(secs, 1),
            "tps": round(gen / secs, 1) if secs > 0 else 0}
    saved = []
    if use_memory and not error:
        saved = memory.remember_from_exchange(prompt, reply, model)
    trace.log("turn", channel=channel, model=model, prompt=(prompt or "")[:300],
              recalled=len(recalled or []),
              tools=[{"tool": t["tool"], "args": t["args"], "out": (t.get("result") or "")[:120]}
                     for t in (calls or [])],
              gen=meta["gen"], total=meta["total"], secs=meta["secs"], tps=meta["tps"],
              saved=len(saved), reply=(reply or "")[:300], error=error)
    return saved, meta
