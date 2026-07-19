"""Shared agent core — what EVERY gateway (UI, bot, future ones) does the same way on
each turn: memory recall, system-prompt assembly, auto-save and tracing.

Keeping this here (instead of duplicated per channel) is what makes the gateways
maintainable: one place for a turn's logic, many frontends.
"""
import os

import memory
import prompts
import skills
import trace

_DIR = os.path.dirname(os.path.abspath(__file__))


def load_soul() -> str:
    """Load the system prompt from prompts/soul.md, falling back to soul_fallback.md.

    Single source of truth for the soul so every gateway (UI, API, bot) stays in sync.
    """
    soul = prompts.load("soul.md")
    return soul or prompts.load("soul_fallback.md")


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
