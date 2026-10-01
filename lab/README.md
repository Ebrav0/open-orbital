# Lab

Lab schedules Open Orbital experiments. The observatory on port 8766 still owns interactive runs, frames, and the Compute page. Lab does not integrate physics and does not write into `work/observatory-data`.

`computenode1` is the control plane. SQLite there is the only job database. Checkpoint bytes go through a `CheckpointStore`. The first store is Google Drive, folder `Open Orbital Compute`, via rclone. A checkpoint becomes current only after the coordinator downloads it and the SHA-256 matches. Workers cannot set that pointer.

## Layout

- `lab submit`, `lab status`, `lab cancel`, `lab workers`, `lab serve`, `lab worker`
- Jev (`typesafe/jev-1.13`) on OpenRouter decides whether a request states the required physics and which implemented backend to use.
- GPT-6 Luna (`openai/gpt-6-luna`) writes the spec or the questions only when Jev cannot close the request.
- `lab/safety.py` rejects anything outside the observatory schema, including a sixth galaxy, a run whose estimate exceeds 120 hours, and a protected observatory id.
- Local workers run on the coordinator. GitHub workers are one `workflow_dispatch` each, capped at 5 hours, on `ubuntu-latest`.
- Oracle, Modal, Codespaces, and Google Spot implement the same backend interface and raise a clear not-configured error.

Merger numbers stored with a job are integrator diagnostics. They are not astronomical observations, and a short run is not evidence of long-term stability.

## Install the coordinator

On `computenode1`, from the repository root:

```sh
mkdir -p work/lab-data
cp lab/env.example work/lab-data/lab.env
cp lab/config.example.toml work/lab-data/lab.toml
```

Set `tailscale_host` in `work/lab-data/lab.toml` to this machine's Tailscale IPv4. Leave the port at 8770.

```sh
work/venv/bin/python -m lab serve
```

The first launch writes `LAB_WORKER_TOKEN` into `work/lab-data/lab.env` when that line is empty. The process listens on `127.0.0.1:8770` and, when `tailscale_host` is set, on that address too. It does not bind the observatory port.

A user service, with linger so it survives logout:

```ini
[Unit]
Description=Open Orbital Lab coordinator

[Service]
WorkingDirectory=/home/edb/open-orbital
ExecStart=/home/edb/open-orbital/work/venv/bin/python -m lab serve
Restart=on-failure

[Install]
WantedBy=default.target
```

```sh
systemctl --user daemon-reload
systemctl --user enable --now lab.service
loginctl enable-linger "$USER"
```

## Secrets

Do not commit these and do not paste them into chat.

Coordinator, gitignored:

| File | What goes in it |
|---|---|
| `work/lab-data/lab.env` | `OPENROUTER_API_KEY` (Luna and Jev), `LAB_GITHUB_TOKEN` (Actions read/write, Contents read), `LAB_WORKER_TOKEN` (generated on first `lab serve`) |
| `work/lab-data/rclone.conf` | rclone remote named `labdrive`, scoped to the Drive folder `Open Orbital Compute` |

`lab/env.example` lists the variable names only.

GitHub Actions secrets on `Ebrav0/open-orbital`, set in the repository settings:

- `LAB_WORKER_TOKEN` — the same value as in `lab.env`
- `TS_AUTHKEY` — a reusable, ephemeral, pre-authorized Tailscale auth key tagged `tag:lab-worker`
- `RCLONE_CONFIG` — the contents of `work/lab-data/rclone.conf`

The Tailscale ACL should allow `tag:lab-worker` to reach `computenode1` on TCP 8770 and nothing else. JSON specs and the unit tests do not need any of these. Natural-language submit needs the OpenRouter key. A GitHub runner needs all three secrets plus the ACL.

Create the Drive remote on the coordinator:

```sh
rclone config --config work/lab-data/rclone.conf
```

Name it `labdrive`. The workflow and the coordinator both expect that name.

## Commands

```sh
work/venv/bin/python -m lab submit --spec experiment.json --backend local
work/venv/bin/python -m lab submit "Run 20 three-galaxy experiments varying impact parameter from 0-20 and compare merger outcomes"
work/venv/bin/python -m lab status
work/venv/bin/python -m lab status JOB_ID
work/venv/bin/python -m lab cancel JOB_ID
work/venv/bin/python -m lab workers
work/venv/bin/python -m lab worker --once --backend local
```

A natural-language submit that is missing particle count, duration, timestep, lifecycle, seed, or galaxy count prints questions and stores nothing. Repeat with `--confirm-defaults` only after those required values are in the request and you accept observatory defaults for the fields you did not name.

An explicit spec may include a matrix:

```json
{
  "mode": "galaxy",
  "n": 10000,
  "n_galaxies": 3,
  "duration": 0.2,
  "dt": 0.02,
  "lifecycle_enabled": false,
  "seed": 1,
  "threads": 4,
  "backend": "github",
  "matrix": {"parameter": "g2_impact", "start": 0, "stop": 20, "count": 20}
}
```

Checked-in GitHub concurrency is 1. Raise `github_concurrency` in `work/lab-data/lab.toml` up to 20. The loader clamps it there. The repository stays private; this does not switch it to public-runner pricing.

## What a worker does

1. Join Tailscale with an ephemeral auth key (GitHub) or run on the coordinator (local).
2. Claim one pending shard. The lease is 5 hours and heartbeats cannot extend it.
3. Fetch the current archive from the store, if there is one, and resume `outputs/observatory/worker.py`.
4. Every checkpoint interval, pack `config.json`, `meta.json`, `checkpoint.json`, the rebound binary, baryons, status, and frames truncated to the committed index into `jobs/<job>/shards/<shard>/<seq>.tar.gz`.
5. Upload with rclone's resumable Drive upload. The coordinator hashes the object. The previous current row stays current until the hash and size match.
6. About 10 minutes before the lease deadline, pause the integrator, publish that checkpoint, release the shard, and exit. The workflow timeout is 330 minutes, inside the hosted runner's 6 hour kill.
7. The scaler starts another runner. A runner that stops heartbeating loses the lease. The shard becomes pending at the last current checkpoint, or held after `max_attempts`.

GitHub artifact storage is not used.

## Recovery

- Expired or killed runner: the shard returns to `pending` with the last verified checkpoint. Attempts are counted. At `max_attempts` the job is held for review.
- Hash mismatch: that version is `rejected`. The pointer does not move.
- Upload interrupted: the object is not current. The next attempt writes the next sequence after the current one.
- Coordinator restart: SQLite and Drive still hold the pointer and the bytes. `lab serve` again and the scaler dispatches workers for pending shards.
- Cancel: pending shards stop. A running worker sees `cancel` on its next heartbeat, publishes a checkpoint, and exits.
- Observatory port 8766 is a different process. Stopping Lab does not stop it. Do not point both at the same experiment directory.

## Tests

```sh
work/venv/bin/python -m unittest discover -s lab/tests -v
PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_physics.py
OBSERVATORY_TEST_REPORT="$PWD/work/lab-data/api_validation_lab.json" PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py
```

The unit tests use an in-memory store. `LAB_STORAGE=directory` uses a shared folder under `work/lab-data/scratch/objects` when two processes on one machine need to rehearse the verify step before Drive is configured. Production stays on `drive`.
