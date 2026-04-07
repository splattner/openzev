#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ "${1:-}" = "--help" ]; then
    cat <<'EOF'
Usage: scripts/start-demo-environment.sh

Starts the local demo stack and seeds the reusable demo dataset.

Environment variables:
  COMPOSE_CMD  Override compose command, e.g. "docker compose" or "docker-compose"
  DOCKER_HOST  Optional container socket override (useful with Podman)

Examples:
  scripts/start-demo-environment.sh
  DOCKER_HOST=unix:///run/user/1000/podman/podman.sock scripts/start-demo-environment.sh
EOF
    exit 0
fi

if [ -n "${COMPOSE_CMD:-}" ]; then
    COMPOSE_CMD_RESOLVED=$COMPOSE_CMD
elif command -v docker >/dev/null 2>&1; then
    COMPOSE_CMD_RESOLVED="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD_RESOLVED="docker-compose"
else
    echo "No compose command found. Install 'docker compose' or 'docker-compose', or set COMPOSE_CMD." >&2
    exit 1
fi

echo "Using compose command: $COMPOSE_CMD_RESOLVED"
echo "Starting OpenZEV demo stack..."
(cd "$ROOT_DIR" && sh -lc "$COMPOSE_CMD_RESOLVED up -d --build")

echo "Seeding demo data..."
(cd "$ROOT_DIR" && sh -lc "$COMPOSE_CMD_RESOLVED exec -T backend python manage.py seed_demo")

echo
echo "OpenZEV demo environment is ready."
echo "Frontend: http://localhost:8080"
echo "Backend API: http://localhost:8001/api/v1"
