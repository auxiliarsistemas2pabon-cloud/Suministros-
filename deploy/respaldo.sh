#!/usr/bin/env bash
set -euo pipefail
umask 077
APP_DIR="${SUMINISTROS_APP_DIR:-/srv/suministros/app}"
export DJANGO_ENV_FILE="${DJANGO_ENV_FILE:-/etc/suministros/suministros.env}"
exec 9>"$APP_DIR/../.respaldo.lock"
flock -n 9 || { echo 'Ya hay un respaldo en ejecución.' >&2; exit 1; }
cd -- "$APP_DIR"
exec "$APP_DIR/.venv/bin/python" deploy/respaldo.py "$@"
