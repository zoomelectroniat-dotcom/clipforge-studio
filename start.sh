#!/bin/bash
# Boot both the web server and the job worker in one container (free-tier layout).
set -e

PORT="${PORT:-8901}"

cd /srv/clipforge/app

# init_db() runs on import in main.py; seed.py is idempotent (demo login for testing)
python seed.py || echo "[start] seed skipped/failed, continuing"

# Worker in background; web server in background; shell stays PID 1 and waits.
python worker.py &
WORKER_PID=$!

_term() {
  echo "[start] shutting down worker ($WORKER_PID)"
  kill -TERM "$WORKER_PID" 2>/dev/null || true
}
trap _term SIGTERM SIGINT

python -m uvicorn main:app --host 0.0.0.0 --port "$PORT" &
WEB_PID=$!

wait $WEB_PID
