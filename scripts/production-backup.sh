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

lock_path="runtime/research.lock"
mkdir -p runtime
exec 9>>"$lock_path"

if ! command -v flock >/dev/null 2>&1; then
  echo "ERROR: flock is required to coordinate backups with Research" >&2
  exit 1
fi

if ! flock -w 2700 9; then
  echo "ERROR: timed out waiting for the active Research run to finish" >&2
  exit 1
fi

trap restart_services EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

compose stop frontend backend
compose run --rm --no-deps --entrypoint python backend /workspace/scripts/backup.py
