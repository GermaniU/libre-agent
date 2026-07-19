"""Skills — reusable procedures the agent invokes when applicable.

Each skill is a .md in skills/ with frontmatter (name, description) + the procedure.
The catalog (name+description) goes into the system prompt; the model calls use_skill("name")
to load the step-by-step and follow it. Claude Code style, but lightweight.
"""
import logging
import os
import re

log = logging.getLogger("localagent.skills")

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)


def _parse(text):
    """Returns (name, description, body) of a .md with optional frontmatter."""
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
    """[(name, description, body)] for each skill in the directory."""
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
            log.debug("could not read skill %r", fn, exc_info=True)
    return out


def list_skills():
    """[(name, description)] for displaying the catalog."""
    return [(n, d) for n, d, _ in _all()]


def load_skill(name):
    """The procedure (body) of a skill by name, or None if it doesn't exist."""
    for n, _, b in _all():
        if n.lower() == (name or "").lower():
            return b
    return None


def catalog():
    """Block for the system prompt with available skills (or '' if none)."""
    sk = list_skills()
    if not sk:
        return ""
    return ('\n\n## Skills disponibles (procedimientos reutilizables)\n'
            'Cuando la tarea encaje con una, invocá `use_skill("nombre")` para traer el paso '
            'a paso y seguilo. No inventes el procedimiento si hay una skill que lo cubre.\n'
            + "\n".join(f"- **{n}**: {d}" for n, d in sk))
