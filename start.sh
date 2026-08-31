#!/usr/bin/env bash
# Grounded — restore, start both servers, health-check (macOS / Linux).
#   ./start.sh          start both
#   ./start.sh test     run the test suite
set -euo pipefail
cd "$(dirname "$0")"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

[ -d .venv ] || python3 -m venv .venv
PY=.venv/bin/python
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r requirements.txt

if [ "${1:-}" = "test" ]; then exec "$PY" -m pytest app/tests -q; fi

if [ ! -f .env ]; then
  echo "No .env found. Run:  cp .env.example .env   then add your Anthropic key." >&2
  exit 1
fi

echo "window.GROUNDED_API = 'http://127.0.0.1:${API_PORT}';" > app/frontend/config.js

# --reload: without it uvicorn holds the old code in memory after an edit.
"$PY" -m uvicorn app.backend.main:app --host 127.0.0.1 --port "$API_PORT" --reload --reload-dir app &
API_PID=$!
"$PY" -m http.server "$WEB_PORT" --bind 127.0.0.1 --directory app/frontend >/dev/null 2>&1 &
WEB_PID=$!
trap 'kill $API_PID $WEB_PID 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:${API_PORT}/api/health" >/dev/null && break
  sleep 0.5
done
echo ""
echo "  Grounded is running:  http://127.0.0.1:${WEB_PORT}"
echo "  API docs:             http://127.0.0.1:${API_PORT}/docs"
echo ""
wait $API_PID
