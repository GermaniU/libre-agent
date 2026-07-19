"""Traceability: structured log (JSONL) of every agent turn, for debugging and improving.

One event per line: what the user asked, what it recalled, which tools it fired (args + result),
tokens, time and errors. Meant for `tail -f`, `grep`, or the sidebar viewer.
"""
import datetime
import json
import logging
import os
import threading

_logger = logging.getLogger("localagent.trace")  # not 'log': this module exports log()

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace.jsonl")
_lock = threading.Lock()


def log(event, **fields):
    """Appends an event to the trace (best-effort, never breaks the chat)."""
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "event": event}
    rec.update(fields)
    try:
        with _lock, open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        _logger.debug("could not append trace event", exc_info=True)


def recent(n=10):
    """Last n events (list of dicts, oldest to newest)."""
    try:
        with _lock, open(LOG, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        return [json.loads(x) for x in lines if x.strip()]
    except Exception:
        _logger.debug("could not read trace", exc_info=True)
        return []
