#!/bin/sh
set -eu

compose() {
  docker compose --env-file .env -f docker-compose.production.yml "$@"
}

restart_services() {
  status=$?
  trap - EXIT
  if ! compose up -d backend frontend >/dev/null; then
    echo "ERROR: failed to restart production services after backup" >&2
    if [ "$status" -eq 0 ]; then
      status=1
    fi
  fi
  exit "$status"
}

trap restart_services EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

compose stop frontend backend
compose run --rm --no-deps --entrypoint python backend /workspace/scripts/backup.py
