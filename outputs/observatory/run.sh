#!/bin/sh
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TASK_DIR=$(CDPATH= cd -- "$APP_DIR/../.." && pwd)
export PYTHONPATH="$TASK_DIR/work/openmp${PYTHONPATH:+:$PYTHONPATH}"
export OMP_WAIT_POLICY=PASSIVE
exec "$TASK_DIR/work/venv/bin/python" "$APP_DIR/server.py" "$@"
