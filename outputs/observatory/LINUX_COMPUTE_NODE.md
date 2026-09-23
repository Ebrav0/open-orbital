# Open Orbital on computenode1 (Linux)

This checkout is `/home/edb/open-orbital`, cloned from `https://github.com/Ebrav0/open-orbital`. The observatory binds to `127.0.0.1:8766`. Saved experiments remain under `work/observatory-data`; timing and validation evidence is separate under `work/linux-benchmarks`. Do not copy a Mac venv or native library here.

## Runtime build

Ubuntu x86_64, Python 3.14.4, GCC 15, 4-core Intel N150. The venv is `work/venv`. `work/openmp` contains a Linux source build of REBOUND 5.1.1 linked to `libgomp.so.1`. `outputs/observatory/run.sh` prepends `work/openmp` to `PYTHONPATH`.

To rebuild the same runtime from this checkout:

```sh
sudo apt-get install build-essential python3-venv python3-dev
cd ~/open-orbital
python3 -m venv work/venv
work/venv/bin/python -m pip install -r outputs/observatory/requirements.txt
CFLAGS='-O3 -fopenmp -DOPENMP' LDFLAGS='-fopenmp' \
  work/venv/bin/python -m pip install --no-cache-dir --no-deps --no-binary=rebound \
  --target work/openmp rebound==5.1.1
ldd work/openmp/librebound*.so
PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_threads.py
```

The benchmark script is `outputs/observatory/tests/benchmark_galaxy.py`. Each invocation writes a new JSON file in that directory. It runs the revision-4 two-galaxy Barnes–Hut physics without lifecycle. Set `OMP_NUM_THREADS` to match `--threads` before Python starts. Do not run competing science jobs while benchmarking.

```sh
cd ~/open-orbital
PYTHONPATH="$PWD/work/openmp" OMP_NUM_THREADS=4 \
  work/venv/bin/python outputs/observatory/tests/benchmark_galaxy.py --n 100000 --threads 4 --steps 4
```

## Start and access

The installed user service is `open-orbital.service`. Linger is enabled so the service can remain active after SSH logout. The service uses the normal `run.sh` launcher and keeps the server on loopback.

On the compute node:

```sh
ssh edb@computenode1
systemctl --user start open-orbital.service
systemctl --user status open-orbital.service
curl http://127.0.0.1:8766/api/system
```

From your Mac, keep this tunnel open in a separate terminal:

```sh
ssh -N -L 8876:127.0.0.1:8766 edb@computenode1
```

Tailscale works through `edb@100.105.242.80` or `edb@computenode1.tail9ebbcf.ts.net` in the same command. Open `http://127.0.0.1:8876/lab` for Compute or `http://127.0.0.1:8876/` for Observe. Port 8876 avoids the Mac's existing local port 8766 server.

To stop gracefully, use `systemctl --user stop open-orbital.service`. Check `/api/jobs` first: stopping an active worker requests a checkpoint. Paused experiments remain paused after restart; jobs marked to run can recover from their saved checkpoint. Do not remove `work/observatory-data` or any historical benchmark JSON.

## Scope

These are live Newtonian N-body REBOUND simulations, not animations. Galaxy model revision 4 remains exploratory; a short benchmark does not establish long-term stability. The Linux node has four cores, so requests for 8, 10, or 14 threads are capped at four and the effective team size is checked. Wall-time caps, run limits, disk-space checks, checkpointing, and source archiving remain in place.
