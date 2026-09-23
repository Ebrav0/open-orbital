# Open Orbital Linux compute-node validation and benchmark — 2026-09-22 EDT

## Scope and machines

The node is `computenode1` (Ubuntu x86_64, Intel N150, 4 physical cores / 4 logical CPUs, 10 GiB RAM). The Mac comparison is Apple M4 Pro (14 logical CPUs, 24 GiB RAM). Both measurements requested and verified **4 OpenMP threads**, used REBOUND 5.1.1, and ran model revision 4 with two live galaxies, Barnes–Hut tree gravity, lifecycle off. The Python benchmark used the same source and settings on both hosts; only the platform-specific OpenMP library differs. The Mac checkout is commit `33709a5`; the node port is commit `3e9cd15` plus the Linux UI wording follow-up. Physics initial conditions were not changed in the Linux port.

Each count starts in a fresh process, builds the galaxies, runs one cold step, then times 8, 5, 4, 3, 2, and 2 steps respectively.

```sh
for spec in 10000:8 30000:5 100000:4 200000:3 500000:2 1000000:2; do
    n=${spec%%:*}; steps=${spec##*:}
    PYTHONPATH="$PWD/work/openmp" OMP_NUM_THREADS=4 \
      work/venv/bin/python outputs/observatory/tests/benchmark_galaxy.py \
      --n "$n" --threads 4 --steps "$steps"
done
```

These are **short-run integration measurements**, not complete simulation wall times. All measured states were finite.

| Particles | Mac s/step | N150 s/step | N150 / Mac | N150 setup s | N150 peak RSS MiB |
|---:|---:|---:|---:|---:|---:|
| 10,000 | 0.0204 | 0.0822 | 4.02× | 0.086 | 98 |
| 30,000 | 0.0944 | 0.3926 | 4.16× | 0.244 | 104 |
| 100,000 | 0.4410 | 2.6273 | 5.96× | 0.809 | 129 |
| 200,000 | 1.1054 | 6.7536 | 6.11× | 1.640 | 166 |
| 500,000 | 3.4994 | 21.9626 | 6.28× | 4.076 | 256 |
| 1,000,000 | 8.2690 | 51.3611 | 6.21× | 8.147 | 414 |

The node's CPU-time/wall-time ratio rose from 3.55 at 10k to 3.80 at 1M, showing active use of nearly all four cores in the timed portion. The Mac ratios were 3.76–3.85 on the same four-thread setting. Neither machine's electrical energy or wattage was measured; the node exposed no readable RAPL energy counter. A node CPU-package temperature sample during the sustained million-particle test was about 82–83 °C. Do not use this to infer watts or energy efficiency.

As an **illustration only**, multiplying the 1M two-galaxy short-step rate by 500 steps gives roughly 7.1 hours of integration on the N150 versus 1.15 hours on the Mac. Density evolution, lifecycle work, saved frames, diagnostics, thermal behavior, and checkpoints can change a full-run wall time. This is not a measured 500-step result or evidence of long-term model stability.

## Validation

All tests used `PYTHONPATH="$PWD/work/openmp"` with the Linux source-built REBOUND linked to `libgomp.so.1`. Reports were directed to new files under `work/linux-benchmarks`; historical benchmark JSON files were not overwritten.

- `validate_threads.py`: PASS; effective team and `omp_get_max_threads()` both 4.
- `validate_physics.py`: PASS; isolated and one-galaxy initial states matched exactly, revision-3 isolated state matched exactly, checkpoint state matched exactly, 2,048-particle energy change was `4.395e-5` at dt 0.02 and `5.695e-6` at dt 0.01, two-galaxy lifecycle mass drift was `1.69e-16`.
- `validate_api.py`: PASS after the Linux server changes; planetary energy change `2.78e-16`, first saved frame preserved across restart, concurrent-job and protected-delete safeguards passed.
- `validate_queue.py`: PASS after fixing live process handle preservation and Linux zombie detection; all ten queue/recovery assertions passed. The first attempt timed out when a paused worker's `Popen` handle was replaced by PID-only tracking; the corrected attempt passed.
- `validate_million.py`: PASS with `OBSERVATORY_MAX_STEP_SECONDS=120` to allow the slower host through the test's machine-specific speed gate (the default remains 15 seconds). One isolated 1M galaxy completed 20 sustained steps in 1,033.68 seconds, **51.68 s/step**, all finite. The real checkpointed worker completed 20 steps in 981.90 seconds, saved 21 frames / 504,000,000 bytes, and reported no error. This was a temporary test run; it was removed when the test ended.

`/api/system` on the running node reports 4 cores, a 120-hour wall cap, a 24-run save limit, and the data directory `/home/edb/open-orbital/work/observatory-data`. `/api/jobs` is empty. The service is a systemd user unit with linger enabled, listening only on `127.0.0.1:8766`. A Tailscale SSH forward returned HTTP 200 for `/api/system`, `/lab`, and `/`. Browser checks switched Galaxy and Planetary Compute modes, loaded Observe, found no horizontal overflow at 1920 or 700 pixels, and found zero console errors or warnings on the final tunnel check.

## Evidence and limits

Node benchmark JSON and validation reports: `work/linux-benchmarks/`. Mac same-script JSON: `work/node-comparison/galaxy_n*_t4.json` in the Mac checkout. Node evidence was also copied without changing originals to `work/node-comparison/compute-node-evidence/` on the Mac.

The exploratory galaxy remains an approximate collisionless model. These short integrations establish that the Linux engine runs and completes the tested steps; they do not calibrate the galaxy or prove long-term stability. Resource safeguards, checkpointing, source archiving, and the protected-run rules remain in the application.
