"""Trazabilidad: log estructurado (JSONL) de cada turno del agente, para depurar y mejorar.

Un evento por línea: qué preguntó el usuario, qué recordó, qué tools disparó (args + resultado),
tokens, tiempo y errores. Pensado para `tail -f`, `grep`, o el visor del sidebar.
"""
import datetime
import json
import os
import threading

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace.jsonl")
_lock = threading.Lock()


def log(event, **fields):
    """Agrega un evento al trace (best-effort, nunca rompe el chat)."""
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "event": event}
    rec.update(fields)
    try:
        with _lock, open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def recent(n=10):
    """Últimos n eventos (lista de dicts, del más viejo al más nuevo)."""
    try:
        with _lock, open(LOG, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        return [json.loads(x) for x in lines if x.strip()]
    except Exception:
        return []
