"""Núcleo compartido del agente — lo que TODO gateway (UI, bot, futuros) hace igual
en cada turno: recall de memoria, armado del system prompt, auto-save y traza.

Mantener esto acá (y no duplicado en cada canal) es lo que hace al gateway mantenible:
un solo lugar para la lógica de un turno, muchos frontends.
"""
import memory
import skills
import trace


def build_system(soul_text, prompt, use_memory=True, k=4):
    """Arma el system prompt del turno: soul + skills disponibles + memorias recordadas.

    Devuelve (system_text, recalled) donde recalled es la lista de memorias usadas.
    """
    recalled = memory.recall(prompt, k=k) if use_memory else []
    system = soul_text + skills.catalog()
    if recalled:
        system += ("\n\n## Lo que recuerdo de vos (memoria persistente)\n"
                   + "\n".join(f"- {m}" for m in recalled))
    return system, recalled


def finalize(channel, prompt, reply, calls, usage, secs, model,
             use_memory=True, recalled=None, error=None):
    """Post-turno común a todos los canales: auto-save de memoria + traza.

    Devuelve (saved_facts, meta). meta = {gen, total, secs, tps} para mostrar en la UI/bot.
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
