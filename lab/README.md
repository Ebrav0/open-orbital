# Open Orbital Lab

Lab turns a research request into a typed experiment plan, validates decisions, freezes an immutable manifest, expands it into reproducible runs, and schedules workers. The observatory on port 8766 continues to own interactive runs, frames, and its Compute page. Lab does not integrate physics itself and never writes into `work/observatory-data`.

`computenode1` is the intended control plane. Its SQLite database owns experiments, revisions, jobs, leases, checkpoint pointers, results, and accounting. Checkpoint and result blobs use the `CheckpointStore` interface. Google Drive via rclone is the shared GitHub-worker transport; the directory provider is for local runs. SQLite decides which verified checkpoint is current.

## Natural-language workflow

```sh
work/venv/bin/python -m lab ask \
  "Study three-galaxy collisions over 10 Gyr with 20 groups and 20 simulations per group, varying speeds and galaxy sizes."
```

GPT-6 Luna (`openai/gpt-6-luna` by default) returns a versioned `ExperimentPlan` JSON candidate. The plan keeps the objective, supplied fields, inferences, unresolved decisions, fixed values, sweep dimensions, outputs, and estimates separate. Jev (`typesafe/jev-1.13`) returns structured field decisions. Deterministic code then enforces Open Orbital's schema, capabilities, run count, sampling requirements, resource caps, and budget; Jev cannot waive those rules.

When required choices remain, Luna asks a small set of grouped questions. Lab stores the plan and dialogue in SQLite. Answer later without restarting:

```sh
work/venv/bin/python -m lab answer CONVERSATION_ID "Use 100k particles and sweep ..."
```

A ready plan goes through a disposable Open Orbital validation run and resource/storage preflight before scheduling. Without `--yes`, Lab asks before freezing; non-interactive mode prints a resumable command. A generated base seed is saved in the conversation before matrix expansion.

The typed model is `lab/planner/models.py`. Galaxy duration may be supplied in Gyr and is converted using the current model revision. Galaxy time is model time (1 unit = 24.50 Myr); planetary duration is years. Galaxy experiments require an explicit resolution and design choices that materially affect the stated objective. Existing simulator defaults are recorded as defaults in the manifest.

## Reproducibility and limits

Each frozen manifest records the original request, clarification dialogue, final parameters, safe defaults, explicit sweep method and dimensions, generated per-run configs and seeds, model revision, source commit and source-tree fingerprint, planner/decision models, creation time, requested outputs, and resource estimate. Its SHA-256 is verified after upload. Manifests are immutable. `lab revise EXPERIMENT_ID "..."` asks Luna to update a stopped experiment and creates a new revision while preserving prior manifest, jobs, and results. Revise only after the current revision is complete, held, or cancelled and all workers have released leases. The configured worker-hour limit applies cumulatively across revisions. Workers validate their assigned run against that revision's manifest hash and run configuration.

The matrix builder supports `grid`, `random`, `latin_hypercube`, and `user_defined`. Continuous ranges default to a recorded Latin-hypercube design when Luna does not specify a method; discrete explicit value lists use a grid. Every group gets the requested number of replicate simulations with a distinct deterministic seed. For example, 20 groups × 20 replicates creates 400 runs. A vague request to “vary” a parameter is not executable until the plan resolves its numeric values/ranges and sampling method.

Before scheduling, Lab runs a temporary smoke computation, estimates runtime from node benchmark history and the Observatory estimator, and estimates retained-checkpoint plus final-result storage. These are predictions, not measured full-run durations. GitHub estimates are cross-host projections. The configured run, storage, per-run time, and worker-hour caps reject oversized work before the manifest is scheduled. The galaxy model is exploratory and collisionless, not a calibrated equilibrium model; a small preflight or short run does not demonstrate long-term stability.

## Backends and worker handoff

`LocalBackend` and `GitHubActionsBackend` are implemented. Other backends are explicit unconfigured stubs. The control plane may run up to 20 GitHub workers; the configuration loader clamps the ceiling to 20. A hosted run has a 330-minute workflow timeout and a lease capped at five hours. Workers stop at a valid checkpoint before the lease drain margin, verify checkpoint and result hashes, then release the shard for another generation. Unexpected runner loss expires its lease and requeues the shard from the latest verified checkpoint. Planned handoffs do not consume the failure retry count.

GitHub Actions workers check out the exact manifest commit, verify it is reachable from the workflow's trusted branch, build a Linux OpenMP REBOUND runtime, join the private tailnet, claim one shard, and use Drive only for immutable blobs. Actions are pinned to full commit SHAs. Protect the configured `github.ref` against unreviewed changes because its workflow code receives the worker and Tailscale secrets. The workflow is `.github/workflows/lab-worker.yml`. `computenode1` should be reachable only over Tailscale on port 8770; do not expose the coordinator publicly. GitHub Actions are not dispatched until the workflow and its exact commit are pushed and the manifest points to that commit.

## Setup on computenode1

From the repository root:

```sh
mkdir -p work/lab-data
[ -e work/lab-data/lab.toml ] || cp lab/config.example.toml work/lab-data/lab.toml
[ -e work/lab-data/lab.env ] || cp lab/env.example work/lab-data/lab.env
```

Use the node's existing `work/venv` and native `work/openmp` runtime for local workers. Add `OPENROUTER_API_KEY` to the gitignored `work/lab-data/lab.env`. Set `server.tailscale_host` to the node's Tailscale IP for GitHub workers. Keep the listener on loopback plus that Tailscale address.

For local-only use, configure `[storage] backend = "directory"`; this stores blobs under `work/lab-data/scratch/objects` for coordinator and local workers on the same node. For the GitHub backend, configure rclone with a private remote named `labdrive` and the folder `Open Orbital Compute`, then use `[storage] backend = "drive"`. The rclone config is `work/lab-data/rclone.conf`; it must never be committed.

Start the coordinator and in-process scheduler:

```sh
work/venv/bin/python -m lab serve
```

The first start generates `LAB_WORKER_TOKEN` in `work/lab-data/lab.env` when absent. For a persistent user service, use a systemd unit with `WorkingDirectory=/home/edb/open-orbital` and `ExecStart=/home/edb/open-orbital/work/venv/bin/python -m lab serve`. Do not point it at the existing Observatory data folder or restart the Observatory service to deploy Lab.

### Secrets

Never commit secrets or paste them into chat.

- `work/lab-data/lab.env`: `OPENROUTER_API_KEY` for both models, `LAB_GITHUB_TOKEN` for coordinator workflow dispatch, and the generated `LAB_WORKER_TOKEN` for authenticated worker/coordinator API calls.
- `work/lab-data/rclone.conf`: private `labdrive` credential with access only to the shared folder.
- GitHub repository Actions secrets: `LAB_WORKER_TOKEN`, `TS_AUTHKEY` scoped to `tag:lab-worker`, and `RCLONE_CONFIG` containing the rclone config.
- Tailscale ACL: allow `tag:lab-worker` to reach only the coordinator on TCP 8770.

The current node setup has no OpenRouter key or GitHub token and no configured rclone remote, so remote models and the GitHub/Drive backend require local secret setup before use.

## CLI

```sh
work/venv/bin/python -m lab ask "..." [--backend local|github] [--yes] [--no-interactive]
work/venv/bin/python -m lab answer CONVERSATION_ID "..." [--backend local|github] [--yes]
work/venv/bin/python -m lab schedule CONVERSATION_ID [--backend local|github] [--yes]
work/venv/bin/python -m lab revise EXPERIMENT_ID "..." [--backend local|github] [--yes]
work/venv/bin/python -m lab experiments
work/venv/bin/python -m lab show EXPERIMENT_ID
work/venv/bin/python -m lab jobs EXPERIMENT_ID
work/venv/bin/python -m lab results EXPERIMENT_ID
work/venv/bin/python -m lab analyze EXPERIMENT_ID
work/venv/bin/python -m lab workers
work/venv/bin/python -m lab status [ID]
work/venv/bin/python -m lab pause EXPERIMENT_ID
work/venv/bin/python -m lab resume EXPERIMENT_ID
work/venv/bin/python -m lab cancel EXPERIMENT_ID
work/venv/bin/python -m lab quotas
```

`lab serve` automatically scales local processes and GitHub workflow runs to configured concurrency. `lab worker --once` is mainly for debugging or the GitHub workflow. Legacy explicit configs remain available as `lab submit --spec path.json --backend local`.

## Validation

```sh
work/venv/bin/python -m unittest discover -s lab/tests -v
PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_physics.py
OBSERVATORY_TEST_REPORT="$PWD/work/lab-data/api_validation_lab.json" PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py
```

The API validator uses isolated port 8767 and the report path above, not historical benchmark evidence. The Lab end-to-end test uses a disposable temporary store/database and runs a real small Open Orbital computation through the authenticated coordinator API, then verifies checkpoint, log, and result uploads locally.
