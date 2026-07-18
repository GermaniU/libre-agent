"""Persistencia de conversaciones en SQLite (sobreviven reinicios de la app).

Cada 'espacio' (sesión de chat) se guarda como un blob JSON keyed por nombre.
Liviano a propósito: abrir/cerrar conexión por llamada + lock para los reruns de Streamlit.
"""
import json
import os
import sqlite3
import threading
import time

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libreagent.db")
_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB, check_same_thread=False, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS sessions "
              "(name TEXT PRIMARY KEY, data TEXT, updated REAL)")
    return c


def load_sessions():
    """Devuelve {nombre: session_dict} de todas las sesiones guardadas (más viejas primero)."""
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
    """Persiste (o actualiza) una sesión. Best-effort: no rompe el chat si falla."""
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
    try:
        with _lock, _conn() as c:
            c.execute("UPDATE sessions SET name=? WHERE name=?", (new, old))
            c.commit()
    except Exception:
        pass
