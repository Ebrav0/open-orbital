#!/bin/sh
# Write ~/Library/LaunchAgents/com.openorbital.observatory.plist and load it.
# --write-only skips launchctl. A healthy listener on 8766 is left alone by start.sh.
# macOS blocks launchd from executing files on Desktop/Documents/Downloads, so the
# agent runs a trampoline under ~/Library/Application Support plus the Homebrew
# CPython that the venv points at — not outputs/observatory/run.sh.
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
LABEL=com.openorbital.observatory
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DATA_DIR="${OBSERVATORY_DATA:-$TASK_DIR/work/observatory-data}"
SUPPORT="${HOME}/Library/Application Support/Open Orbital"
TRAMPOLINE="${SUPPORT}/run-observatory.sh"
VENV_PY="${TASK_DIR}/work/venv/bin/python"
mkdir -p "$HOME/Library/LaunchAgents" "$DATA_DIR" "$SUPPORT"

if [ ! -x "$VENV_PY" ]; then
  echo "Missing $VENV_PY. Create the project venv before installing the daemon." >&2
  exit 1
fi
REAL_PY=$("$VENV_PY" -c "import os,sys; print(os.path.realpath(sys.executable))")
SITE=$("$VENV_PY" -c "import sysconfig; print(sysconfig.get_path('purelib'))")
case "$REAL_PY" in
  "$HOME/Desktop"|"$HOME/Desktop"/*|"$HOME/Documents"|"$HOME/Documents"/*|"$HOME/Downloads"|"$HOME/Downloads"/*)
    echo "The Python interpreter resolves to $REAL_PY, which launchd cannot execute." >&2
    exit 1
    ;;
esac
if [ ! -x "$REAL_PY" ]; then
  echo "Resolved interpreter is not executable: $REAL_PY" >&2
  exit 1
fi

{
  printf '%s\n' '#!/bin/sh'
  printf '%s\n' 'set -eu'
  printf '%s\n' "export PYTHONPATH='${TASK_DIR}/work/openmp:${SITE}'\"\${PYTHONPATH:+:\$PYTHONPATH}\""
  printf '%s\n' 'export OMP_WAIT_POLICY=PASSIVE'
  printf '%s\n' "export VIRTUAL_ENV='${TASK_DIR}/work/venv'"
  printf '%s\n' "exec '${REAL_PY}' '${APP_DIR}/server.py' \"\$@\""
} >"$TRAMPOLINE"
chmod 755 "$TRAMPOLINE"

{
  printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>'
  printf '%s\n' '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
  printf '%s\n' '<plist version="1.0"><dict>'
  printf '%s\n' "  <key>Label</key><string>${LABEL}</string>"
  printf '%s\n' '  <key>ProgramArguments</key><array>'
  printf '%s\n' '    <string>/bin/sh</string>'
  printf '%s\n' "    <string>${TRAMPOLINE}</string>"
  printf '%s\n' '  </array>'
  printf '%s\n' "  <key>WorkingDirectory</key><string>${SUPPORT}</string>"
  printf '%s\n' '  <key>RunAtLoad</key><true/>'
  printf '%s\n' '  <key>KeepAlive</key><true/>'
  printf '%s\n' "  <key>StandardOutPath</key><string>${DATA_DIR}/server.log</string>"
  printf '%s\n' "  <key>StandardErrorPath</key><string>${DATA_DIR}/server.log</string>"
  printf '%s\n' '  <key>EnvironmentVariables</key><dict>'
  printf '%s\n' "    <key>PYTHONPATH</key><string>${TASK_DIR}/work/openmp:${SITE}</string>"
  printf '%s\n' '    <key>OPENORBITAL_DAEMON</key><string>1</string>'
  if [ -n "${OBSERVATORY_DATA:-}" ]; then
    printf '%s\n' "    <key>OBSERVATORY_DATA</key><string>${OBSERVATORY_DATA}</string>"
  fi
  printf '%s\n' '  </dict>'
  printf '%s\n' '</dict></plist>'
} >"$PLIST"
printf '{"label":"%s","plist":"%s","trampoline":"%s","python":"%s","installed":true}\n' "$LABEL" "$PLIST" "$TRAMPOLINE" "$REAL_PY" >"$DATA_DIR/daemon.json"
echo "Wrote $PLIST"
echo "Wrote $TRAMPOLINE"
if [ "${1:-}" = '--write-only' ]; then
  exit 0
fi
uid=$(id -u)
if ! command -v launchctl >/dev/null 2>&1; then
  echo "launchctl is not available. Use start.sh foreground fallback." >&2
  exit 1
fi

ready() {
  curl -sf -m 2 http://127.0.0.1:8766/api/jobs >/dev/null 2>&1
}

if launchctl print "gui/${uid}/${LABEL}" >/dev/null 2>&1; then
  if ready; then
    echo "LaunchAgent ${LABEL} is already loaded."
    exit 0
  fi
  echo "LaunchAgent ${LABEL} is loaded but the API is not answering. Reloading."
  launchctl bootout "gui/${uid}/${LABEL}" || launchctl unload "$PLIST" || true
  sleep 0.3
fi
if launchctl bootstrap "gui/${uid}" "$PLIST"; then
  echo "Loaded ${LABEL}."
  exit 0
fi
launchctl load -w "$PLIST"
echo "Loaded ${LABEL} with launchctl load."
