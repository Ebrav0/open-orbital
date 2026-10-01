#!/bin/sh
# Turn a fresh Ubuntu VM (x86_64 or ARM, e.g. an Oracle Cloud Always Free Ampere A1) into an Open Orbital compute node.
# Run it ON THE NODE as the login user (not root):
#   curl -fsSL <raw url of this file> -o bootstrap.sh   # or scp it from the Mac
#   sh bootstrap.sh                                      # optional: TS_AUTHKEY=tskey-... sh bootstrap.sh
# It installs Python + numpy/scipy, builds REBOUND 5.1.1 with OpenMP into ~/open-orbital/work/openmp,
# and joins your tailnet. The Mac pushes the physics engine itself on every run; no repository checkout is needed.
# No passwords are used anywhere: the Mac reaches this node with its SSH key (paste ~/.ssh/id_ed25519.pub
# into the VM's authorized_keys, or into the "SSH keys" box when creating the Oracle instance).
set -eu
ROOT="${OPEN_ORBITAL_ROOT:-$HOME/open-orbital}"
REBOUND_VERSION=5.1.1
echo "== Open Orbital node bootstrap into $ROOT"

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-dev build-essential curl ca-certificates tar coreutils procps
else
  echo "This script expects Ubuntu/Debian (apt-get). Install python3-venv, a C compiler with OpenMP, curl and tar yourself, then rerun." >&2
  exit 1
fi

mkdir -p "$ROOT/work"
cd "$ROOT"
[ -x work/venv/bin/python ] || python3 -m venv work/venv
work/venv/bin/pip install --upgrade pip
work/venv/bin/pip install numpy scipy

# REBOUND's C tree code honours -DOPENMP; gcc links libgomp.
CFLAGS='-O3 -fopenmp -DOPENMP' LDFLAGS='-fopenmp' \
  work/venv/bin/pip install --no-cache-dir --no-deps --no-binary=rebound --upgrade --target work/openmp "rebound==$REBOUND_VERSION"
PYTHONPATH="$ROOT/work/openmp" work/venv/bin/python - <<'PY'
import glob,subprocess,rebound,numpy,scipy,os
lib=rebound.clibrebound._name
linked=subprocess.run(['ldd',lib],capture_output=True,text=True).stdout
print('rebound',rebound.__version__,'numpy',numpy.__version__,'scipy',scipy.__version__)
print('library',lib)
print('OpenMP linked:', 'gomp' in linked or 'omp' in linked)
print('cores',os.cpu_count())
PY
mkdir -p "$ROOT/work/remote-runs"

if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! tailscale status >/dev/null 2>&1; then
  if [ -n "${TS_AUTHKEY:-}" ]; then sudo tailscale up --authkey "$TS_AUTHKEY" --hostname "${TS_HOSTNAME:-oracle-a1}"
  else sudo tailscale up --hostname "${TS_HOSTNAME:-oracle-a1}"   # prints a login URL; open it on any device
  fi
fi
tailscale ip -4 || true

cat <<EOF

== Done. On the Mac, open Orbital → Nodes → Add a node:
   Id: ${TS_HOSTNAME:-oracle-a1}   SSH target: $(id -un)@${TS_HOSTNAME:-oracle-a1}   Remote root: ~/open-orbital
Then Probe and Benchmark it. Runs launched there keep going while the Mac sleeps and sync when it wakes.

Oracle Always Free note: Oracle may reclaim Always Free instances that stay nearly idle for 7 days
(CPU, network and memory all low). Queue real work on it regularly, or check the instance in the console.
EOF
