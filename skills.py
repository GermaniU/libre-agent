"""Skills — procedimientos reutilizables que el agente invoca cuando aplica.

Cada skill es un .md en skills/ con frontmatter (name, description) + el procedimiento.
El catálogo (name+description) va al system prompt; el modelo llama use_skill("nombre")
para cargar el paso a paso y seguirlo. Estilo Claude Code, pero liviano.
"""
import os
import re

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)


def _parse(text):
    """Devuelve (name, description, body) de un .md con frontmatter opcional."""
    name = desc = None
    body = text
    m = _FM.match(text)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            low = line.lower()
            if low.startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif low.startswith("description:"):
                desc = line.split(":", 1)[1].strip()
    return name, desc, body.strip()


def _all():
    """[(name, description, body)] de cada skill del directorio."""
    out = []
    if not os.path.isdir(SKILLS_DIR):
        return out
    for fn in sorted(os.listdir(SKILLS_DIR)):
        if not fn.endswith(".md"):
            continue
        try:
            with open(os.path.join(SKILLS_DIR, fn), encoding="utf-8") as f:
                n, d, b = _parse(f.read())
            out.append((n or fn[:-3], d or "", b))
        except Exception:
            pass
    return out


def list_skills():
    """[(name, description)] para mostrar el catálogo."""
    return [(n, d) for n, d, _ in _all()]


def load_skill(name):
    """El procedimiento (body) de una skill por nombre, o None si no existe."""
    for n, _, b in _all():
        if n.lower() == (name or "").lower():
            return b
    return None


def catalog():
    """Bloque para el system prompt con las skills disponibles (o '' si no hay)."""
    sk = list_skills()
    if not sk:
        return ""
    return ('\n\n## Skills disponibles (procedimientos reutilizables)\n'
            'Cuando la tarea encaje con una, invocá `use_skill("nombre")` para traer el paso '
            'a paso y seguilo. No inventes el procedimiento si hay una skill que lo cubre.\n'
            + "\n".join(f"- **{n}**: {d}" for n, d in sk))
