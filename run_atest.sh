#!/usr/bin/env bash
# Start the acceptance test server, run the suites against it, then stop it again.
set -euo pipefail

PORT="${GRAPHQL_TEST_PORT:-8099}"
poetry run python atest/server/graphql_server.py "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
    if curl -sf -X POST "http://localhost:$PORT/reset" -d '{}' >/dev/null; then break; fi
    sleep 0.2
done

poetry run robot --outputdir atest-results \
    --variable "GRAPHQL_URL:http://localhost:$PORT/graphql" "$@" atest
