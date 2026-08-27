#!/usr/bin/env bash
# One-command quickstart: copies the example configs (only if they don't
# already exist — never touches a real setup) and brings up Qdrant, the
# backend, and the frontend, all in Docker. No Node/npm needed on the
# host. See README.md for what each step does, and for running the
# backend/frontend outside Docker instead.
set -euo pipefail
cd "$(dirname "$0")"

for pair in \
  ".env.example:.env" \
  "config/global.yaml.example:config/global.yaml" \
  "config/tenants.yaml.example:config/tenants.yaml"
do
  src="${pair%%:*}"
  dst="${pair##*:}"
  if [ ! -f "$dst" ]; then
    cp "$src" "$dst"
    echo "Created $dst"
  fi
done

docker compose up -d --build

echo -n "Waiting for the backend to come up"
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8766/healthz > /dev/null 2>&1; then
    echo
    echo "Aegis is ready → http://localhost:3000"
    exit 0
  fi
  echo -n "."
  sleep 1
done

echo
echo "The backend didn't come up in time — check 'docker compose logs backend'."
exit 1
