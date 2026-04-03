#!/bin/bash
set -e

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    alembic upgrade head
fi

exec "$@"
