---
name: nuevo-proyecto-python
description: Scaffoldea un proyecto Python nuevo en el workspace (estructura + venv + deps) listo para correr
---

# Skill: nuevo proyecto Python

Cuando el usuario pida arrancar un proyecto/script Python, seguí estos pasos con las tools
(todo confinado a `WORKSPACE_DIR`):

1. **Elegí un nombre** en kebab-case (ej: `mi-scraper`). Confirmá con el usuario si no lo dio.
2. **Creá la estructura** con `make_dir`:
   - `nombre/` y `nombre/src/`
3. **Escribí los archivos base** con `write_file`:
   - `nombre/README.md` — qué hace, cómo correrlo.
   - `nombre/requirements.txt` — una dependencia por línea (solo las que de verdad usa).
   - `nombre/src/main.py` — el código, con un bloque `if __name__ == "__main__":`.
4. **Creá el venv e instalá deps** con `run_cmd` (una línea):
   `python3 -m venv nombre/.venv && nombre/.venv/bin/pip install -q -r nombre/requirements.txt`
5. **Verificá** con `run_cmd`: `nombre/.venv/bin/python nombre/src/main.py` (si es seguro correrlo).
6. **Cerrá** diciéndole al usuario la ruta y el comando exacto para ejecutarlo a mano.

Reglas: código real y mínimo (nada de placeholders inútiles). No metas dependencias que no se usan. Si el script hace algo con red o archivos del usuario, avisá qué va a hacer antes de correrlo.
