#!/usr/bin/env bash
# Start the Scheduler Agent. Creates the shared platform network if it doesn't exist.
set -euo pipefail

NETWORK_NAME="${MULTI_AGENT_NETWORK:-multi_agent_platform_net}"

if ! docker network inspect "$NETWORK_NAME" > /dev/null 2>&1; then
  echo "[up.sh] Network '$NETWORK_NAME' not found — creating it."
  docker network create "$NETWORK_NAME"
fi

exec docker compose "$@"
