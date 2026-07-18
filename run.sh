#!/usr/bin/env bash
# Arranca LocalCowork. Crea venv la primera vez.
set -e
cd "$(dirname "$0")"
# venv sin pip = creación interrumpida (falta python3.12-venv) -> bootstrap con get-pip
if [ ! -x .venv/bin/pip ]; then
  rm -rf .venv
  python3 -m venv --without-pip .venv
  curl -sS https://bootstrap.pypa.io/get-pip.py | ./.venv/bin/python - -q
fi
./.venv/bin/python -c 'import streamlit' 2>/dev/null || ./.venv/bin/pip install -q -r requirements.txt
exec ./.venv/bin/streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --server.enableStaticServing true
