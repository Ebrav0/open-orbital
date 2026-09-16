#!/bin/sh
# Launch the local observatory and open the Compute dashboard in the default browser.
# Reuses port 8766 when the server is already healthy. Ctrl+C is a graceful shutdown.
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
URL='http://127.0.0.1:8766'
DASHBOARD="$URL/lab"

ready() {
  curl -sf -m 2 "$URL/api/jobs" >/dev/null 2>&1
}

open_dashboard() {
  echo "Observatory: $URL"
  echo "Compute dashboard: $DASHBOARD"
  echo "Observe: $URL/"
  if command -v open >/dev/null 2>&1; then
    open "$DASHBOARD"
  else
    echo "Open $DASHBOARD in your browser." >&2
  fi
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

# Open the browser as soon as the listener answers, then keep the server in the foreground
# so Ctrl+C remains a graceful shutdown (checkpoints active jobs).
(
  i=0
  while [ "$i" -lt 50 ]; do
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
