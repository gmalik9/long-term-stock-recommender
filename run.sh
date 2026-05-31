#!/usr/bin/env bash
# Helper for managing the stock-recommender Streamlit container.
# Usage: ./run.sh <command>

set -euo pipefail

SERVICE="dashboard"
CONTAINER="stock-recommender"
URL="http://localhost:8501"
HEALTH="${URL}/_stcore/health"
COMPOSE=(docker compose)

cd "$(dirname "$0")"

c_red()   { printf "\033[31m%s\033[0m\n" "$*"; }
c_grn()   { printf "\033[32m%s\033[0m\n" "$*"; }
c_ylw()   { printf "\033[33m%s\033[0m\n" "$*"; }
c_cyn()   { printf "\033[36m%s\033[0m\n" "$*"; }

wait_healthy() {
  c_cyn "Waiting for ${HEALTH} ..."
  for i in {1..30}; do
    if curl -fsS "${HEALTH}" >/dev/null 2>&1; then
      c_grn "Healthy. Open ${URL}"
      return 0
    fi
    sleep 1
  done
  c_red "App did not become healthy in 30s. Recent logs:"
  "${COMPOSE[@]}" logs --tail=30 "${SERVICE}" || true
  return 1
}

cmd_start() {
  c_cyn "Starting container (no rebuild)..."
  "${COMPOSE[@]}" up -d
  wait_healthy
}

cmd_stop() {
  c_cyn "Stopping container..."
  "${COMPOSE[@]}" stop
  c_grn "Stopped."
}

cmd_down() {
  c_cyn "Tearing down container (keeps image)..."
  "${COMPOSE[@]}" down
  c_grn "Down."
}

cmd_restart() {
  c_cyn "Restarting container..."
  "${COMPOSE[@]}" restart
  wait_healthy
}

cmd_rebuild() {
  c_cyn "Rebuilding image and recreating container..."
  "${COMPOSE[@]}" up -d --build
  wait_healthy
}

cmd_refresh() {
  # The flow you want after any code change: down → rebuild --no-cache → up → wait.
  c_cyn "Refreshing app from scratch..."
  "${COMPOSE[@]}" down --remove-orphans || true
  "${COMPOSE[@]}" build --no-cache
  "${COMPOSE[@]}" up -d
  wait_healthy
}

cmd_hard_reset() {
  c_ylw "Hard reset: stop, remove container + image + volumes, rebuild from scratch."
  read -r -p "Continue? [y/N] " ans
  case "${ans:-N}" in
    y|Y|yes|YES) ;;
    *) c_red "Aborted."; return 1 ;;
  esac
  "${COMPOSE[@]}" down -v --rmi local --remove-orphans || true
  docker image prune -f --filter "label=com.docker.compose.project=$(basename "$PWD")" || true
  "${COMPOSE[@]}" build --no-cache --pull
  "${COMPOSE[@]}" up -d
  wait_healthy
}

cmd_logs() {
  "${COMPOSE[@]}" logs -f --tail=100 "${SERVICE}"
}

cmd_status() {
  "${COMPOSE[@]}" ps
  echo
  if curl -fsS "${HEALTH}" >/dev/null 2>&1; then
    c_grn "Health: OK (${HEALTH})"
  else
    c_red "Health: FAIL (${HEALTH})"
  fi
}

cmd_shell() {
  "${COMPOSE[@]}" exec "${SERVICE}" /bin/bash
}

cmd_test() {
  c_cyn "Running pytest inside container..."
  "${COMPOSE[@]}" exec "${SERVICE}" python -m pytest tests/ -v
}

cmd_open() {
  if command -v open >/dev/null 2>&1; then
    open "${URL}"
  else
    c_cyn "Visit ${URL}"
  fi
}

cmd_mcp_stdio() {
  c_cyn "Starting MCP server on stdio (Ctrl-C to exit)..."
  "${COMPOSE[@]}" exec "${SERVICE}" python -m mcp_server.server
}

usage() {
  cat <<EOF
$(c_cyn "stock-recommender control script")

Usage: ./run.sh <command>

Commands:
  start         Start container (no rebuild)
  stop          Stop container (keep it)
  down          Stop and remove container (keep image)
  restart       Restart running container
  rebuild       Rebuild image (with cache) and recreate container
  refresh       Full refresh: down → build --no-cache → up   [use after code changes]
  hard-reset    Nuclear option: remove container + image + volumes, then rebuild
  logs          Tail container logs
  status        Show container + health status
  shell         Open a bash shell inside the container
  test          Run pytest test suite inside the container
  mcp-stdio     Start the MCP agent server (stdio) inside the container
  open          Open the app in the default browser
  help          Show this message
EOF
}

case "${1:-help}" in
  start)       cmd_start ;;
  stop)        cmd_stop ;;
  down)        cmd_down ;;
  restart)     cmd_restart ;;
  rebuild)     cmd_rebuild ;;
  refresh)     cmd_refresh ;;
  hard-reset|hard_reset|reset) cmd_hard_reset ;;
  logs)        cmd_logs ;;
  status|ps)   cmd_status ;;
  shell|sh|bash) cmd_shell ;;
  test|tests|pytest) cmd_test ;;
  mcp-stdio|mcp) cmd_mcp_stdio ;;
  open)        cmd_open ;;
  help|-h|--help) usage ;;
  *) c_red "Unknown command: $1"; echo; usage; exit 1 ;;
esac
