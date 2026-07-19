"""Local tools that the model can execute via ollama's tool calling.

Each tool ALWAYS returns a string (what the model sees as the result).
"""
import json
import logging
import re

import requests

import clients
import config
import prompts

log = logging.getLogger("localagent.tools")

UA = {"User-Agent": "Mozilla/5.0 (LocalAgent; +local)"}


# ---------------------------------------------------------------- impls
def web_search(query, max_results=5):
    """Search DuckDuckGo and return title, URL and snippet of each hit.

    DuckDuckGo usually rate-limits scraping, so we retry with backoff
    and return a clear message if it fails (instead of breaking the chat).
    """
    import time

    from ddgs import DDGS
    last_err = None
    for attempt in range(3):
        try:
            rows = list(DDGS().text(query, max_results=int(max_results)))
            if not rows:
                return "Sin resultados."
            out = []
            for r in rows:
                out.append(f"- {r.get('title', '?')}\n  {r.get('href', '')}\n  {r.get('body', '')}")
            return "\n".join(out)
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    return (f"web_search no disponible ahora (DuckDuckGo rate-limita el scraping): {last_err}. "
            "Respondé con tu conocimiento o probá de nuevo en un momento.")


def web_fetch(url, max_chars=5000):
    """Download a page and return its plain text (without HTML)."""
    from bs4 import BeautifulSoup
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        t.decompose()
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    return text[: int(max_chars)] or "(página vacía)"


def vault_pull():
    """git pull of the physical vault (from WSL, which is the side that merges well)."""
    import subprocess
    r = subprocess.run(["git", "-C", config.VAULT_DIR, "pull", "--no-rebase"],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr).strip()
    return out[:1500] or "pull sin salida"


def vault_recent(days=7):
    """What was worked on recently: vault notes modified in the last N days.

    Uses git (log + status) instead of os.walk over /mnt/c: the Windows FS from WSL
    is extremely slow with 1000+ files; git resolves the same thing instantly and captures both
    recent commits and uncommitted changes.
    """
    import datetime
    import os
    import subprocess
    days = int(days)
    root = config.VAULT_DIR
    recent = set()
    try:
        log = subprocess.run(
            ["git", "-C", root, "-c", "core.quotepath=false", "log",
             f"--since={days} days ago", "--name-only", "--pretty=format:", "--", "*.md"],
            capture_output=True, text=True, timeout=30).stdout
        for line in log.splitlines():
            line = line.strip().strip('"')
            if line.endswith(".md"):
                recent.add(line)
        status = subprocess.run(
            ["git", "-C", root, "-c", "core.quotepath=false", "status", "--porcelain"],
            capture_output=True, text=True, timeout=30).stdout
        for line in status.splitlines():
            p = line[3:].strip().strip('"')
            if p.endswith(".md"):
                recent.add(p)
    except Exception as e:
        return f"vault_recent: no pude consultar git ({e}). ¿El vault es un repo git en {root}?"
    # daily notes go by filename (date), which is more reliable than mtime
    today = datetime.date.today()
    dailies = []
    for i in range(days):
        d = today - datetime.timedelta(days=i)
        p = os.path.join(root, "Daily Notes", f"{d.isoformat()}.md")
        if os.path.exists(p):
            with open(p, errors="replace") as f:
                dailies.append(f"### Daily {d.isoformat()}\n{f.read()[:2500]}")
    out = f"Notas modificadas en los últimos {days} días ({len(recent)}):\n"
    out += "\n".join(f"- {p}" for p in sorted(recent)[:40]) or "(ninguna — quizás falte vault_pull)"
    if dailies:
        out += "\n\n" + "\n\n".join(dailies)
    return out[:12000]


def vault_read(path):
    """Read a note from the physical vault by relative path (e.g.: 'Daily Notes/2026-07-10.md')."""
    import os
    p = os.path.realpath(os.path.join(config.VAULT_DIR, path))
    if not p.startswith(os.path.realpath(config.VAULT_DIR)):
        return "Error: ruta fuera del vault."
    if not os.path.exists(p):
        return f"No existe: {path}"
    with open(p, errors="replace") as f:
        return f.read()[:12000]


def write_html(filename, content, title=""):
    """Save an HTML page in static/ and return the URLs to open it."""
    import os
    import socket
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", os.path.splitext(filename)[0]).strip("-") or "pagina"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", f"{name}.html")
    html = content
    if "<html" not in html.lower():
        html = (
            "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{title or name}</title></head><body>\n{content}\n</body></html>"
        )
    with open(path, "w") as f:
        f.write(html)
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        log.debug("could not resolve LAN IP for write_html", exc_info=True)
        ip = "localhost"
    # The SPA (api.py) serves static/ at the root path; PORT is the SPA port (default 8585).
    port = os.getenv("PORT", "8585")
    return (f"Página guardada en static/{name}.html. "
            f"Abrila en http://localhost:{port}/{name}.html "
            f"(desde otra máquina de la LAN: http://{ip}:{port}/{name}.html)")


def vault_search(query, limit=6):
    """Search passages in the vault (corpus/Qdrant) and return them cited."""
    hits = clients.corpus_search(query, limit=int(limit))
    if not hits:
        return "Sin pasajes relevantes en el vault."
    return clients.build_rag_context(hits)


def use_skill(name):
    """Load a skill's procedure (by name) to follow it step by step."""
    import skills
    body = skills.load_skill(name)
    if not body:
        avail = ", ".join(n for n, _ in skills.list_skills()) or "(ninguna)"
        return f"No existe la skill '{name}'. Disponibles: {avail}"
    return f"PROCEDIMIENTO de la skill '{name}' — seguilo paso a paso con las tools:\n\n{body}"


# ---------------------------------------------------------------- filesystem (workspace)
def _in_workspace(path):
    """Resolve `path` inside WORKSPACE_DIR and validate that it does not escape (anti traversal).

    Returns (absolute_path, None) if valid, or (None, error_message) if not.
    """
    import os
    root = os.path.realpath(config.WORKSPACE_DIR)
    full = os.path.realpath(os.path.join(root, path))
    if full != root and not full.startswith(root + os.sep):
        return None, f"Error: ruta fuera del workspace ({config.WORKSPACE_DIR})."
    return full, None


def make_dir(path):
    """Create a folder (and its parents) inside the workspace (C:\\Sites)."""
    import os
    full, err = _in_workspace(path)
    if err:
        return err
    os.makedirs(full, exist_ok=True)
    return f"Carpeta lista: {full}"


def write_file(path, content):
    """Write a text file inside the workspace, creating parent folders if missing."""
    import os
    full, err = _in_workspace(path)
    if err:
        return err
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Archivo escrito ({len(content)} chars): {full}"


def list_dir(path="."):
    """List the contents of a workspace folder (to see what's there before writing)."""
    import os
    full, err = _in_workspace(path)
    if err:
        return err
    if not os.path.isdir(full):
        return f"No es una carpeta: {full}"
    entries = sorted(os.listdir(full))
    if not entries:
        return "(carpeta vacía)"
    return "\n".join(f"{'📁' if os.path.isdir(os.path.join(full, e)) else '📄'} {e}"
                     for e in entries)


def read_file(path, max_chars=10000):
    """Read a text file inside the workspace and return its content (truncated).

    The read-only counterpart of write_file: lets the model inspect what it (or the
    user) wrote before overwriting or modifying it. Confined to WORKSPACE_DIR via
    _in_workspace (same anti-traversal guard as the other filesystem tools).
    """
    import os
    full, err = _in_workspace(path)
    if err:
        return err
    if not os.path.exists(full):
        return f"No existe: {path}"
    if os.path.isdir(full):
        return f"Es una carpeta, no un archivo: {path}"
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return f"Error leyendo {path}: {e}"
    return content[: int(max_chars)] or "(archivo vacío)"


# clearly destructive patterns → always blocked (defense, not exhaustive)
_BLOCKED_CMD = re.compile(
    r"\brm\s+-rf?\s+(/|~|\$HOME|\*)"          # rm -rf of root/home/everything
    r"|\bmkfs|\bdd\s+if=|\bshred\b"            # disk formatting / wiping
    r"|>\s*/dev/(sd|nvme|null/)"               # writing to devices
    r"|:\(\)\s*\{.*\};:"                       # fork bomb
    r"|\b(shutdown|reboot|halt|poweroff)\b"    # power off the machine
    r"|\bchmod\s+-R\s+777\s+/"                 # open root permissions
    r"|\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh)\b"  # pipe to shell
    r"|\bsudo\s+rm\b",
    re.I,
)


def run_cmd(command, timeout=60):
    """Execute a shell command inside the workspace (C:\\Sites) and return its output.

    Safeguards: blocks clearly destructive patterns, runs confined to WORKSPACE_DIR,
    and cuts off after `timeout` seconds. Intended for dev tasks (pip, python, git, ls…).
    """
    import subprocess
    cmd = (command or "").strip()
    if not cmd:
        return "Error: comando vacío."
    if _BLOCKED_CMD.search(cmd):
        return ("BLOQUEADO: el comando coincide con un patrón destructivo y no se ejecuta. "
                "Si es legítimo, reformulalo o corrélo vos a mano.")
    try:
        r = subprocess.run(cmd, shell=True, cwd=config.WORKSPACE_DIR,
                           capture_output=True, text=True, timeout=int(timeout))
    except subprocess.TimeoutExpired:
        return f"Timeout: el comando superó {timeout}s y se cortó."
    except Exception as e:
        return f"Error ejecutando: {e}"
    out = (r.stdout or "")
    if r.stderr:
        out += ("\n[stderr]\n" + r.stderr)
    out = out.strip() or "(sin salida)"
    return f"[exit {r.returncode}] (cwd={config.WORKSPACE_DIR})\n{out[:4000]}"


# ---------------------------------------------------------------- specs
# Tool schemas: shapes live here (code), human descriptions live in prompts/tools.es.json.
# Each entry: (name, {param: type}, [required params]).
_TOOL_SCHEMAS = [
    ("web_search", {"query": "string", "max_results": "integer"}, ["query"]),
    ("web_fetch", {"url": "string", "max_chars": "integer"}, ["url"]),
    ("vault_pull", {}, []),
    ("vault_recent", {"days": "integer"}, []),
    ("vault_read", {"path": "string"}, ["path"]),
    ("write_html", {"filename": "string", "content": "string", "title": "string"},
     ["filename", "content"]),
    ("vault_search", {"query": "string", "limit": "integer"}, ["query"]),
    ("make_dir", {"path": "string"}, ["path"]),
    ("write_file", {"path": "string", "content": "string"}, ["path", "content"]),
    ("read_file", {"path": "string", "max_chars": "integer"}, ["path"]),
    ("list_dir", {"path": "string"}, []),
    ("run_cmd", {"command": "string", "timeout": "integer"}, ["command"]),
    ("use_skill", {"name": "string"}, ["name"]),
]

# Descriptions are externalized (kept in Spanish, the product language) so the code
# stays language-agnostic. If the file is missing, tools still work (empty descriptions).
_DESCRIPTIONS = json.loads(prompts.load("tools.es.json", "{}"))


def _build_specs():
    specs = []
    for name, params, required in _TOOL_SCHEMAS:
        info = _DESCRIPTIONS.get(name, {})
        param_desc = info.get("params", {})
        props = {p: {"type": t, "description": param_desc.get(p, "")} for p, t in params.items()}
        parameters = {"type": "object", "properties": props}
        if required:
            parameters["required"] = required
        specs.append({"type": "function", "function": {
            "name": name,
            "description": info.get("description", ""),
            "parameters": parameters,
        }})
    return specs


SPECS = _build_specs()

_IMPLS = {"web_search": web_search, "web_fetch": web_fetch,
          "vault_search": vault_search, "write_html": write_html,
          "vault_pull": vault_pull, "vault_recent": vault_recent, "vault_read": vault_read,
          "make_dir": make_dir, "write_file": write_file, "read_file": read_file,
          "list_dir": list_dir, "run_cmd": run_cmd, "use_skill": use_skill}


def execute(name, args):
    """Execute a tool by name; the error goes as text so the model can recover."""
    fn = _IMPLS.get(name)
    if not fn:
        return f"Error: tool desconocida '{name}'."
    try:
        if isinstance(args, str):
            args = json.loads(args or "{}")
        return str(fn(**args))
    except Exception as e:
        return f"Error ejecutando {name}: {e}"
