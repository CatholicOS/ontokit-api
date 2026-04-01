#!/bin/bash
set -euo pipefail

# Only run migrations once per container start (uvicorn --reload re-invokes
# the entrypoint on each file change; the marker prevents repeated runs).
# Set RUN_MIGRATIONS=0 to skip (e.g. for replica instances where only
# a single leader should run migrations).
MARKER="/tmp/.migrations_done"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
if [ "$RUN_MIGRATIONS" = "1" ] && [ ! -f "$MARKER" ]; then
    echo "Running database migrations..."
    python -m alembic upgrade head
    touch "$MARKER"
elif [ "$RUN_MIGRATIONS" != "1" ]; then
    echo "Skipping migrations (RUN_MIGRATIONS=$RUN_MIGRATIONS)"
fi

echo "Starting application..."
exec "$@"
