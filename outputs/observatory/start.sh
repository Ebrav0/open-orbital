#!/bin/sh
# Open the Compute dashboard. Prefers the LaunchAgent daemon; does not own a 120 h process.
# If the API already answers, only opens the browser. Terminal may close afterwards.
set -eu
SOURCE=$0
while [ -L "$SOURCE" ]; do
  DIR=$(CDPATH= cd -- "$(dirname -- "$SOURCE")" && pwd)
  SOURCE=$(readlink "$SOURCE")
  case "$SOURCE" in
    /*) ;;
    *) SOURCE="$DIR/$SOURCE" ;;
  esac
done
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$SOURCE")" && pwd)
TASK_DIR=$(CDPATH= cd -- "$APP_DIR/../.." && pwd)
DATA_DIR="${OBSERVATORY_DATA:-$TASK_DIR/work/observatory-data}"
URL='http://127.0.0.1:8766'
DASHBOARD="$URL/lab"

ready() {
  curl -sf -m 2 "$URL/api/jobs" >/dev/null 2>&1
}

wait_ready() {
  i=0
  while [ "$i" -lt 75 ]; do
    if ready; then
      return 0
    fi
    i=$((i + 1))
    sleep 0.2
  done
  return 1
}

open_dashboard() {
  echo "Observatory: $URL"
  echo "Compute dashboard: $DASHBOARD"
  echo "Observe: $URL/"
  echo "The engine is a background daemon. This window can close."
  if command -v open >/dev/null 2>&1; then
    open "$DASHBOARD"
  else
    echo "Open $DASHBOARD in your browser." >&2
  fi
}

start_session_process() {
  mkdir -p "$DATA_DIR"
  echo "Starting the observatory from this session instead."
  nohup /bin/sh "$APP_DIR/run.sh" >>"$DATA_DIR/server.log" 2>&1 </dev/null &
}

if ready; then
  echo "Observatory is already running."
  open_dashboard
  exit 0
fi

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:8766 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 8766 is in use, but it is not the observatory API. Leave that process alone and free the port, then try again." >&2
  exit 1
fi

if command -v launchctl >/dev/null 2>&1; then
  if ! sh "$APP_DIR/install-daemon.sh"; then
    echo "LaunchAgent install did not succeed." >&2
  fi
  if wait_ready; then
    open_dashboard
    exit 0
  fi
  echo "Daemon did not become ready on $URL. Unloading it and retrying from this window." >&2
  sh "$APP_DIR/stop-daemon.sh" >/dev/null 2>&1 || true
  start_session_process
  if wait_ready; then
    open_dashboard
    exit 0
  fi
  echo "Server did not become ready on $URL. See $DATA_DIR/server.log" >&2
  exit 1
fi

echo "launchctl is unavailable. Starting in the foreground — this window must stay open."
(
  i=0
  while [ "$i" -lt 75 ]; do
    if ready; then
      open_dashboard
      exit 0
    fi
    i=$((i + 1))
    sleep 0.2
  done
  echo "Server did not become ready on $URL." >&2
  exit 1
) &
exec sh "$APP_DIR/run.sh" "$@"
