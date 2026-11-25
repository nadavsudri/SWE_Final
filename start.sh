#!/bin/sh
# Start the LEG data fetcher: builds the UI when needed, then serves UI + API on http://127.0.0.1:8000
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -q -e ".[ui]"; }
.venv/bin/python -c "import fastapi, uvicorn" 2>/dev/null || .venv/bin/pip install -q -e ".[ui]"
if [ ! -d ui/node_modules ]; then npm --prefix ui install --no-fund --no-audit; fi
if [ ! -f ui/dist/index.html ] || [ -n "$(find ui/src ui/index.html ui/public -newer ui/dist/index.html 2>/dev/null | head -1)" ]; then
  npm --prefix ui run build
fi
PYTHONPATH=src exec .venv/bin/python -m leg.api "$@"
