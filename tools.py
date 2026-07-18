"""Tools locales que el modelo puede ejecutar vía tool calling de ollama.

Cada tool devuelve SIEMPRE un string (lo que el modelo ve como resultado).
"""
import json
import re

import requests

import clients
import config

UA = {"User-Agent": "Mozilla/5.0 (LocalAgent; +local)"}


# ---------------------------------------------------------------- impls
def web_search(query, max_results=5):
    """Busca en DuckDuckGo y devuelve título, URL y snippet de cada hit.

    DuckDuckGo suele rate-limitear el scraping, así que reintentamos con backoff
    y devolvemos un mensaje claro si falla (en vez de romper el chat).
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
    """Descarga una página y devuelve su texto plano (sin HTML)."""
    from bs4 import BeautifulSoup
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        t.decompose()
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    return text[: int(max_chars)] or "(página vacía)"


def vault_pull():
    """git pull del vault físico (desde WSL, que es el lado que mergea bien)."""
    import subprocess
    r = subprocess.run(["git", "-C", config.VAULT_DIR, "pull", "--no-rebase"],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr).strip()
    return out[:1500] or "pull sin salida"


def vault_recent(days=7):
    """Qué se trabajó últimamente: notas del vault modificadas en los últimos N días.

    Usa git (log + status) en vez de os.walk sobre /mnt/c: el FS de Windows desde WSL
    es lentísimo con 1000+ archivos; git resuelve lo mismo al instante y capta tanto
    commits recientes como cambios sin commitear.
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
    # las daily notes van por nombre de archivo (fecha), que es más confiable que mtime
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
    """Lee una nota del vault físico por ruta relativa (ej: 'Daily Notes/2026-07-10.md')."""
    import os
    p = os.path.realpath(os.path.join(config.VAULT_DIR, path))
    if not p.startswith(os.path.realpath(config.VAULT_DIR)):
        return "Error: ruta fuera del vault."
    if not os.path.exists(p):
        return f"No existe: {path}"
    with open(p, errors="replace") as f:
        return f.read()[:12000]


def write_html(filename, content, title=""):
    """Guarda una página HTML en static/ y devuelve las URLs para abrirla."""
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
        ip = "localhost"
    return (f"Página guardada. Abrila en: http://localhost:8501/app/static/{name}.html"
            f" (desde otra máquina de la LAN: http://{ip}:8501/app/static/{name}.html)")


def vault_search(query, limit=6):
    """Busca pasajes en el vault (corpus/Qdrant) y los devuelve citados."""
    hits = clients.corpus_search(query, limit=int(limit))
    if not hits:
        return "Sin pasajes relevantes en el vault."
    return clients.build_rag_context(hits)


def use_skill(name):
    """Carga el procedimiento de una skill (por nombre) para seguirlo paso a paso."""
    import skills
    body = skills.load_skill(name)
    if not body:
        avail = ", ".join(n for n, _ in skills.list_skills()) or "(ninguna)"
        return f"No existe la skill '{name}'. Disponibles: {avail}"
    return f"PROCEDIMIENTO de la skill '{name}' — seguilo paso a paso con las tools:\n\n{body}"


# ---------------------------------------------------------------- filesystem (workspace)
def _in_workspace(path):
    """Resuelve `path` dentro de WORKSPACE_DIR y valida que no se escape (anti traversal).

    Devuelve (ruta_absoluta, None) si es válida, o (None, mensaje_error) si no.
    """
    import os
    root = os.path.realpath(config.WORKSPACE_DIR)
    full = os.path.realpath(os.path.join(root, path))
    if full != root and not full.startswith(root + os.sep):
        return None, f"Error: ruta fuera del workspace ({config.WORKSPACE_DIR})."
    return full, None


def make_dir(path):
    """Crea una carpeta (y sus padres) dentro del workspace (C:\\Sites)."""
    import os
    full, err = _in_workspace(path)
    if err:
        return err
    os.makedirs(full, exist_ok=True)
    return f"Carpeta lista: {full}"


def write_file(path, content):
    """Escribe un archivo de texto dentro del workspace, creando carpetas padre si faltan."""
    import os
    full, err = _in_workspace(path)
    if err:
        return err
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Archivo escrito ({len(content)} chars): {full}"


def list_dir(path="."):
    """Lista el contenido de una carpeta del workspace (para ver qué hay antes de escribir)."""
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


# patrones claramente destructivos → se bloquean siempre (defensa, no exhaustiva)
_BLOCKED_CMD = re.compile(
    r"\brm\s+-rf?\s+(/|~|\$HOME|\*)"          # rm -rf de raíz/home/todo
    r"|\bmkfs|\bdd\s+if=|\bshred\b"            # formateo / borrado de disco
    r"|>\s*/dev/(sd|nvme|null/)"               # escribir a dispositivos
    r"|:\(\)\s*\{.*\};:"                       # fork bomb
    r"|\b(shutdown|reboot|halt|poweroff)\b"    # apagar la máquina
    r"|\bchmod\s+-R\s+777\s+/"                 # abrir permisos de raíz
    r"|\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh)\b"  # pipe a shell
    r"|\bsudo\s+rm\b",
    re.I,
)


def run_cmd(command, timeout=60):
    """Ejecuta un comando de shell dentro del workspace (C:\\Sites) y devuelve su salida.

    Guardas: bloquea patrones claramente destructivos, corre confinado a WORKSPACE_DIR,
    y corta a los `timeout` segundos. Pensada para tareas de dev (pip, python, git, ls…).
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
SPECS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Busca en la web (DuckDuckGo). Úsala para info actual o externa al vault.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Términos de búsqueda"},
            "max_results": {"type": "integer", "description": "Cantidad de resultados (default 5)"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "web_fetch",
        "description": "Descarga una URL y devuelve su texto. Úsala para leer un resultado de web_search.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "URL completa (http/https)"},
            "max_chars": {"type": "integer", "description": "Máximo de caracteres (default 5000)"},
        }, "required": ["url"]},
    }},
    {"type": "function", "function": {
        "name": "vault_pull",
        "description": "Actualiza el vault físico con git pull. Usala antes de vault_recent si el usuario pregunta por trabajo muy reciente.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "vault_recent",
        "description": "Qué trabajó el usuario últimamente: lista notas modificadas y devuelve las daily notes de los últimos N días.",
        "parameters": {"type": "object", "properties": {
            "days": {"type": "integer", "description": "Días hacia atrás (default 7)"},
        }},
    }},
    {"type": "function", "function": {
        "name": "vault_read",
        "description": "Lee una nota completa del vault por ruta relativa, ej: 'Daily Notes/2026-07-10.md'.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Ruta relativa dentro del vault"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write_html",
        "description": "Guarda una página HTML y devuelve la URL para abrirla en el navegador. "
                       "Úsala cuando el usuario pida un documento, reporte, tabla o página visual. "
                       "Pasá el HTML completo del body (CSS inline permitido).",
        "parameters": {"type": "object", "properties": {
            "filename": {"type": "string", "description": "Nombre del archivo, ej: reporte-ventas"},
            "content": {"type": "string", "description": "El HTML completo de la página"},
            "title": {"type": "string", "description": "Título de la pestaña"},
        }, "required": ["filename", "content"]},
    }},
    {"type": "function", "function": {
        "name": "vault_search",
        "description": "Busca en las notas personales del vault del usuario (Obsidian). Úsala para preguntas sobre sus notas, libros o proyectos.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Búsqueda semántica"},
            "limit": {"type": "integer", "description": "Cantidad de pasajes (default 6)"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "make_dir",
        "description": "Crea una carpeta (y sus padres) para un proyecto nuevo dentro de C:\\Sites. "
                       "Úsala al iniciar un proyecto, ej: 'mi-scraper' o 'mi-scraper/src'.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Ruta relativa dentro del workspace"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Escribe un archivo de texto (script Python, HTML, requirements.txt, README, "
                       "config, etc.) dentro de C:\\Sites, creando carpetas padre si faltan. "
                       "Úsala para materializar el código de un proyecto que el usuario luego ejecuta a mano.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Ruta relativa, ej: 'mi-scraper/main.py'"},
            "content": {"type": "string", "description": "Contenido completo del archivo"},
        }, "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "Lista el contenido de una carpeta del workspace (C:\\Sites). "
                       "Úsala para ver qué existe antes de crear o sobrescribir.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Ruta relativa (default la raíz del workspace)"},
        }},
    }},
    {"type": "function", "function": {
        "name": "run_cmd",
        "description": "Ejecuta un comando de shell en el workspace (C:\\Sites) y devuelve su salida "
                       "(exit code + stdout/stderr). Úsalo para tareas de dev: instalar deps "
                       "(pip install), correr un script (python x.py), git, ls, etc. Bloquea "
                       "comandos destructivos. Preferí comandos no interactivos y de una sola línea.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "El comando de shell a ejecutar"},
            "timeout": {"type": "integer", "description": "Segundos máx antes de cortar (default 60)"},
        }, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "use_skill",
        "description": "Carga el procedimiento paso a paso de una skill (procedimiento reutilizable) "
                       "para seguirlo. Úsalo cuando la tarea encaje con una skill del catálogo del "
                       "system prompt, en vez de improvisar el procedimiento.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Nombre de la skill (ej: nuevo-proyecto-python)"},
        }, "required": ["name"]},
    }},
]

_IMPLS = {"web_search": web_search, "web_fetch": web_fetch,
          "vault_search": vault_search, "write_html": write_html,
          "vault_pull": vault_pull, "vault_recent": vault_recent, "vault_read": vault_read,
          "make_dir": make_dir, "write_file": write_file, "list_dir": list_dir,
          "run_cmd": run_cmd, "use_skill": use_skill}


def execute(name, args):
    """Ejecuta una tool por nombre; el error va como texto para que el modelo se recupere."""
    fn = _IMPLS.get(name)
    if not fn:
        return f"Error: tool desconocida '{name}'."
    try:
        if isinstance(args, str):
            args = json.loads(args or "{}")
        return str(fn(**args))
    except Exception as e:
        return f"Error ejecutando {name}: {e}"
