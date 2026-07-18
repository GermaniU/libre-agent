#!/usr/bin/env bash
# Arranca LocalAgent en modo SPA: FastAPI sirve el frontend en web/ y expone /api/.
# El backend reutiliza sin cambios agent.py, clients.py, store.py, memory.py, tools.py, etc.
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/pip ]; then
  rm -rf .venv
  python3 -m venv --without-pip .venv
  curl -sS https://bootstrap.pypa.io/get-pip.py | ./.venv/bin/python - -q
fi

./.venv/bin/python -c 'import fastapi' 2>/dev/null || ./.venv/bin/pip install -q -r requirements.txt
mkdir -p static
exec ./.venv/bin/uvicorn api:app --host 0.0.0.0 --port "${PORT:-8585}"
