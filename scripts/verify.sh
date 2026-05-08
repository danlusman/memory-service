#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/6] Rebuilding and starting service"
docker compose -f docker-compose.yml up -d --build

echo "[2/6] Waiting for health"
until curl -sf http://localhost:8080/health >/dev/null; do
  sleep 1
done
echo "health OK"

echo "[3/6] Posting smoke turn"
TURN_ID="$(curl -sS -X POST http://localhost:8080/turns \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id":"smoke-1",
    "user_id":"user-1",
    "messages":[
      {"role":"user","content":"I just moved to Berlin from NYC last month. My dog named Biscuit is loving the parks."},
      {"role":"assistant","content":"Nice update!"}
    ],
    "timestamp":"2025-03-15T10:30:00Z",
    "metadata":{}
  }' | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo "turn id: $TURN_ID"

echo "[4/6] Running recall probe"
RECALL="$(curl -sS -X POST http://localhost:8080/recall \
  -H 'Content-Type: application/json' \
  -d '{
    "query":"Where does this user live and what is their pet name?",
    "session_id":"smoke-2",
    "user_id":"user-1",
    "max_tokens":512
  }')"
echo "$RECALL"

echo "[5/6] Inspecting memories"
curl -sS http://localhost:8080/users/user-1/memories
echo

echo "[6/6] Running internal tests in container"
docker compose -f docker-compose.yml exec memory-service python -m pytest -q

echo "Verification complete."
