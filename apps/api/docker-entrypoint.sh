#!/bin/sh
# Entry point for the API image: `api` (default), `worker` or `migrate`.
set -eu
role="${1:-api}"

migrate() {
  alembic upgrade head
  nexus-seed
}

case "$role" in
  api)
    if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ]; then migrate; fi
    exec uvicorn nexus.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"
    ;;
  worker)
    exec nexus-worker
    ;;
  migrate)
    migrate
    ;;
  *)
    exec "$@"
    ;;
esac
