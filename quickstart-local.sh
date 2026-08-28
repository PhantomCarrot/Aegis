#!/usr/bin/env bash
# One-command quickstart for the no-Docker path: backend and frontend run
# as plain host processes (Qdrant still runs in Docker — there's no good
# reason to hand-install a vector DB for local dev). Use this instead of
# quickstart.sh when a tenant needs an SSH key/certificate path the Docker
# container can't see (e.g. a short-lived cert from `az ssh config`) — see
# docs/execution-model.md#the-two-modes.
#
# Usage:
#   ./quickstart-local.sh          start backend + frontend, wait until ready
#   ./quickstart-local.sh stop     stop both (reads the PID file this script writes)
set -euo pipefail
cd "$(dirname "$0")"

PID_FILE=".aegis-local.pids"
BACKEND_LOG="/tmp/aegis-backend-host.log"
FRONTEND_LOG="/tmp/aegis-frontend-host.log"

if [ "${1:-}" = "stop" ]; then
  if [ ! -f "$PID_FILE" ]; then
    echo "No $PID_FILE — nothing tracked by this script is running."
    exit 0
  fi
  # shellcheck disable=SC1090
  source "$PID_FILE"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "Stopped."
  exit 0
fi

for pair in \
  ".env.example:.env" \
  "config/global.yaml.example:config/global.yaml" \
  "config/tenants.yaml.example:config/tenants.yaml" \
  "frontend/.env.example:frontend/.env.local"
do
  src="${pair%%:*}"
  dst="${pair##*:}"
  if [ ! -f "$dst" ]; then
    cp "$src" "$dst"
    echo "Created $dst"
  fi
done

# Only the token is read out of the root .env — the rest of that file
# (OLLAMA_URL=host.docker.internal, QDRANT_URL=http://qdrant:6333) is
# Docker-specific and would break local resolution if sourced wholesale.
# The backend's own defaults (localhost:11434, config/*.yaml relative to
# cwd) are already correct for this mode.
AEGIS_BACKEND_TOKENS="$(grep -m1 '^AEGIS_BACKEND_TOKENS=' .env | cut -d= -f2-)"
if [ -z "$AEGIS_BACKEND_TOKENS" ]; then
  echo "AEGIS_BACKEND_TOKENS is empty in .env — set it first." >&2
  exit 1
fi

echo "Starting Qdrant..."
docker compose up -d qdrant

echo "Starting backend (log: $BACKEND_LOG)..."
AEGIS_BACKEND_TOKENS="$AEGIS_BACKEND_TOKENS" \
  nohup uv run --project backend uvicorn app.main:app --app-dir backend --reload --port 8766 \
  > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

echo -n "Waiting for the backend"
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8766/healthz > /dev/null 2>&1; then
    echo
    break
  fi
  echo -n "."
  sleep 1
done
if ! curl -sf http://localhost:8766/healthz > /dev/null 2>&1; then
  echo
  echo "Backend didn't come up in time — check $BACKEND_LOG."
  kill "$BACKEND_PID" 2>/dev/null || true
  exit 1
fi

if [ ! -d frontend/node_modules ]; then
  echo "Installing frontend dependencies (first run only)..."
  (cd frontend && npm install)
fi

echo "Starting frontend (log: $FRONTEND_LOG)..."
(cd frontend && nohup npm run dev > "$FRONTEND_LOG" 2>&1 &)
# npm run dev backgrounds inside a subshell above — find its PID via the port instead.
sleep 1
FRONTEND_PID="$(lsof -tiTCP:3000 -sTCP:LISTEN 2>/dev/null | head -1)"

echo -n "Waiting for the frontend"
for _ in $(seq 1 30); do
  if curl -sf http://localhost:3000 > /dev/null 2>&1; then
    echo
    echo "Aegis is ready → http://localhost:3000"
    break
  fi
  echo -n "."
  sleep 1
done

{
  echo "BACKEND_PID=$BACKEND_PID"
  echo "FRONTEND_PID=$FRONTEND_PID"
} > "$PID_FILE"

echo "Stop with: ./quickstart-local.sh stop"
