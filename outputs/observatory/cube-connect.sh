#!/bin/sh
# Mac-side launcher for the Cube-hosted Open Orbital control plane and compute node.
# The Cube runs the Observatory on 127.0.0.1:8766 and the Lab coordinator on 127.0.0.1:8770.
# This script makes sure both are running there, forwards them to this Mac's loopback over
# SSH, opens the dashboard, and closes the tunnel on Ctrl+C. Neither server is exposed
# publicly: both bind loopback on the Cube and the forwards bind loopback here.
#
#   cube-connect.sh [--no-browser]      ensure services, tunnel, open dashboard (default)
#   cube-connect.sh status              print remote service health
#   cube-connect.sh stop-remote [--force]
#                                       stop both remote services; refuses while work is active
#
# Leaving the launcher only closes the tunnel. Remote services and jobs keep running.
# Local ports differ from 8766/8770 so the Mac's own observatory (start.sh) and the
# computenode1 tunnel (8876) keep working alongside this one.
set -eu

HOST="${OPEN_ORBITAL_CUBE_HOST:-cube-swab-siding-harbor}"
REMOTE_DIR="${OPEN_ORBITAL_CUBE_DIR:-/workspace/home/repos/open-orbital}"
OBS_LOCAL="${OPEN_ORBITAL_CUBE_OBS_PORT:-8966}"
LAB_LOCAL="${OPEN_ORBITAL_CUBE_LAB_PORT:-8970}"
OBS_REMOTE=8766
LAB_REMOTE=8770
DASHBOARD="http://127.0.0.1:${OBS_LOCAL}/lab"
OBSERVE="http://127.0.0.1:${OBS_LOCAL}/"
TUNNEL_PID=

remote() {
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" \
    "cd '$REMOTE_DIR' && work/venv/bin/python outputs/observatory/remote_services.py $*"
}

port_busy() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    # Only "connection refused" (curl exit 7) means nothing is listening.
    rc=0
    curl -s -o /dev/null -m 1 "http://127.0.0.1:$1/" || rc=$?
    [ "$rc" -ne 7 ]
  fi
}

http_code() {
  curl -s -o /dev/null -m 2 -w '%{http_code}' "$1" 2>/dev/null || true
}

cleanup() {
  trap - EXIT INT TERM HUP
  if [ -n "$TUNNEL_PID" ] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
    echo "Tunnel closed. Cube services and any running jobs continue on $HOST."
  fi
}

connect() {
  open_browser=1
  [ "${1:-}" = "--no-browser" ] && open_browser=0

  for port in "$OBS_LOCAL" "$LAB_LOCAL"; do
    if port_busy "$port"; then
      echo "Local port $port is already in use. Close that tunnel/app or set OPEN_ORBITAL_CUBE_OBS_PORT / OPEN_ORBITAL_CUBE_LAB_PORT." >&2
      exit 1
    fi
  done

  echo "Checking Open Orbital services on $HOST:$REMOTE_DIR ..."
  if ! remote ensure; then
    echo "Could not start or verify the Cube services. Run: $0 status" >&2
    exit 1
  fi

  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM HUP
  # A dedicated connection (no ControlMaster reuse) so this process owns the forwards
  # and closing it releases them. Forwards bind 127.0.0.1 on this Mac only.
  ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
    -o ControlMaster=no -o ControlPath=none \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -L "127.0.0.1:${OBS_LOCAL}:127.0.0.1:${OBS_REMOTE}" \
    -L "127.0.0.1:${LAB_LOCAL}:127.0.0.1:${LAB_REMOTE}" \
    "$HOST" &
  TUNNEL_PID=$!

  i=0
  until [ "$(http_code "http://127.0.0.1:${OBS_LOCAL}/api/jobs?view=summary")" = 200 ] &&
        [ "$(http_code "http://127.0.0.1:${LAB_LOCAL}/api/health")" = 401 ]; do
    # Lab answers 401 without the worker token; that still proves the forward reaches it.
    if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
      TUNNEL_PID=
      echo "SSH tunnel to $HOST exited before the services answered." >&2
      exit 1
    fi
    i=$((i + 1))
    if [ "$i" -ge 100 ]; then
      echo "Tunnel is up but the services did not answer through it." >&2
      exit 1
    fi
    sleep 0.2
  done

  echo "Compute dashboard: $DASHBOARD"
  echo "Observe:           $OBSERVE"
  echo "Lab coordinator:   http://127.0.0.1:${LAB_LOCAL}  (worker-token API; use the lab CLI on the Cube)"
  echo "Press Ctrl+C to close the tunnel. Cube jobs keep running."
  if [ "$open_browser" = 1 ]; then
    if command -v open >/dev/null 2>&1; then
      open "$DASHBOARD"
    else
      echo "Open $DASHBOARD in your browser."
    fi
  fi

  status=0
  wait "$TUNNEL_PID" || status=$?
  TUNNEL_PID=
  echo "SSH tunnel to $HOST ended (status $status). Run this launcher again to reconnect." >&2
  exit 1
}

command="${1:-connect}"
[ $# -gt 0 ] && shift
case "$command" in
  connect) connect "$@" ;;
  --no-browser) connect --no-browser ;;
  status) remote status ;;
  stop-remote) remote stop "$@" ;;
  -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) echo "Unknown command: $command (try --help)" >&2; exit 2 ;;
esac
