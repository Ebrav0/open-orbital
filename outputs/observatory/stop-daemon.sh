#!/bin/sh
# Unload the observatory LaunchAgent. The server SIGTERMs workers so they checkpoint.
# Also stops a leftover :8766 observatory listener started by start.sh's session fallback.
set -eu
LABEL=com.openorbital.observatory
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
URL='http://127.0.0.1:8766'
uid=$(id -u)
if command -v launchctl >/dev/null 2>&1; then
  if launchctl print "gui/${uid}/${LABEL}" >/dev/null 2>&1; then
    launchctl bootout "gui/${uid}/${LABEL}" || launchctl unload "$PLIST" || true
    echo "Stopped ${LABEL}."
  else
    echo "LaunchAgent ${LABEL} is not loaded."
  fi
else
  echo "launchctl is not available." >&2
fi

ready() {
  curl -sf -m 2 "$URL/api/jobs" >/dev/null 2>&1
}

i=0
while [ "$i" -lt 25 ]; do
  if ! ready; then
    exit 0
  fi
  i=$((i + 1))
  sleep 0.1
done

if ! command -v lsof >/dev/null 2>&1; then
  echo "Observatory API is still on 8766; install lsof or stop it manually." >&2
  exit 1
fi
pid=$(lsof -nP -iTCP:8766 -sTCP:LISTEN -t 2>/dev/null | head -1 || true)
if [ -n "${pid:-}" ]; then
  echo "Stopping leftover observatory listener PID ${pid}."
  kill -TERM "$pid" 2>/dev/null || true
fi
