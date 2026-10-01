# Open Orbital on the Cube (Linux control plane and compute node)

The Cube checkout is `/workspace/home/repos/open-orbital` on SSH host `cube-swab-siding-harbor` (Debian 12 x86_64, 12 AMD EPYC vCPUs, 24 GB RAM). It runs the Observatory on `127.0.0.1:8766` and the Lab coordinator on `127.0.0.1:8770`, both on loopback only. The runtime build is the same as `LINUX_COMPUTE_NODE.md`, except that Python 3.14 comes from user-local `uv` (`~/.local/share/uv`) because the node has no sudo. Set `[limits] max_threads = 12` in the gitignored `work/lab-data/lab.toml` so Lab galaxy shards use all 12 CPUs.

## From the Mac

Double-click **Open Orbital on Cube.command** in the repository root, or run:

```sh
sh outputs/observatory/cube-connect.sh            # ensure services, tunnel, open the Compute dashboard
sh outputs/observatory/cube-connect.sh --no-browser
sh outputs/observatory/cube-connect.sh status     # remote health JSON
sh outputs/observatory/cube-connect.sh stop-remote [--force]
```

The launcher:

1. Runs `remote_services.py ensure` on the Cube over SSH. This starts whichever service is not answering, waits for health, and refuses to continue if either listener is bound beyond loopback.
2. Opens one dedicated `ssh -N` connection, without ControlMaster reuse, that forwards Mac `127.0.0.1:8966 → Cube 127.0.0.1:8766` and Mac `127.0.0.1:8970 → Cube 127.0.0.1:8770`. Forwards bind loopback on the Mac; nothing is published.
3. Opens `http://127.0.0.1:8966/lab` (Observe is `http://127.0.0.1:8966/`).
4. On Ctrl+C, closing the window, or tunnel loss, closes the tunnel. **Cube services and jobs keep running.** Run the launcher again to reconnect.

The local ports avoid the Mac's own observatory on 8766 (`Start Open Orbital.command`/`start.sh`) and the computenode1 tunnel on 8876, so all three workflows coexist. Override them with `OPEN_ORBITAL_CUBE_OBS_PORT` and `OPEN_ORBITAL_CUBE_LAB_PORT`. Override the host or checkout path with `OPEN_ORBITAL_CUBE_HOST` and `OPEN_ORBITAL_CUBE_DIR`. The Lab port is the token-authenticated worker API; it answers 401 without `LAB_WORKER_TOKEN`. Run `lab` CLI commands on the Cube.

## On the Cube

```sh
cd /workspace/home/repos/open-orbital
work/venv/bin/python outputs/observatory/remote_services.py status|ensure|stop [--force]
```

`stop` refuses while an Observatory job is running/initializing/pausing or a Lab lease is active. `--force` sends the normal graceful signals anyway: SIGTERM to the Observatory, which checkpoints its worker, and SIGINT to `lab serve`, which drains local workers. A Lab shard interrupted this way resumes from its last verified checkpoint when its lease expires. Services are started in their own session with SIGINT restored, so they survive SSH disconnects and still shut down gracefully. Logs: `work/observatory-data/server.log` and `work/lab-data/serve.log`. The Cube has no systemd user session, so nothing restarts the services after a machine restart; the next launcher run starts them.
