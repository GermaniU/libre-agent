"""Conversation persistence in SQLite (survives app restarts).

Each 'space' (chat session) is stored as a JSON blob keyed by name.
Deliberately lightweight: open/close connection per call + lock for Streamlit reruns.
"""
import json
import os
import sqlite3
import threading
import time

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "localagent.db")
_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB, check_same_thread=False, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS sessions "
              "(name TEXT PRIMARY KEY, data TEXT, updated REAL)")
    return c


def load_sessions():
    """Returns {name: session_dict} for all saved sessions (oldest first)."""
    try:
        with _lock, _conn() as c:
            rows = c.execute("SELECT name, data FROM sessions ORDER BY updated").fetchall()
    except Exception:
        return {}
    out = {}
    for name, data in rows:
        try:
            out[name] = json.loads(data)
        except Exception:
            pass
    return out


def save_session(name, session):
    """Persists (or updates) a session. Best-effort: won't break the chat if it fails."""
    try:
        with _lock, _conn() as c:
            c.execute("INSERT OR REPLACE INTO sessions (name, data, updated) VALUES (?,?,?)",
                      (name, json.dumps(session, ensure_ascii=False), time.time()))
            c.commit()
    except Exception:
        pass


def delete_session(name):
    try:
        with _lock, _conn() as c:
            c.execute("DELETE FROM sessions WHERE name=?", (name,))
            c.commit()
    except Exception:
        pass


def rename_session(old, new):
    """Returns False if the target name already exists or the update fails (won't overwrite sessions)."""
    try:
        with _lock, _conn() as c:
            if c.execute("SELECT 1 FROM sessions WHERE name=?", (new,)).fetchone():
                return False
            c.execute("UPDATE sessions SET name=? WHERE name=?", (new, old))
            c.commit()
            return True
    except Exception:
        return False
