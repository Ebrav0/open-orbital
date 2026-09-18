# CPU utilization diagnosis — 2026-09-17

## Confirmed causes and fixes

1. `effective_threads(14)` was silently reduced to the 10 performance cores. It now honors the requested count up to the machine logical-core count. OpenMP maximum-team verification returns 14. UI captions and timing calculations no longer apply the P-core cap.
2. The installed LaunchAgent omitted `ProcessType`. The local `launchd.plist(5)` documentation says an unspecified ProcessType applies light CPU and I/O resource limits. The service reported `spawn type = daemon (3)`. Both the installer and installed plist now set `ProcessType=Interactive`; launchctl verifies `spawn type = interactive (4)`. This permits the user's requested compute workload to run without the default service throttle. It does not change the laptop's global power mode or fan policy.
3. Forced OpenMP `close` core binding was removed (`OMP_PROC_BIND=false`), allowing macOS to place the team. Small same-checkpoint comparisons favored unbound placement on average, but varied enough that this is not a universal performance claim.

## Evidence

Live job: 67be855d5342, 200,000 particles, two galaxies, stellar lifecycle enabled, 14 requested threads. Correct custom multicore REBOUND and Homebrew libomp confirmed in vmmap. All measurements were on battery amid other apps, not isolated laboratory benchmarks.

- Original worker log: `OpenMP 10 threads (requested 14, 10 performance cores)`.
- Removing background task priority alone: 436.7% CPU before vs 438.5% after, five-second windows; no meaningful improvement.
- Same copied checkpoint, six gravity steps: 10/close 5.131 s at 729%; 14/close 4.446 s at 942%; 14/unbound 4.109 s at 1040%. Production was paused for these measurements; benchmark copies never wrote its checkpoint.
- Eight-step runs including stellar lifecycle: unbound 5.042 / 5.715 s, close 6.177 / 5.421 s. Lifecycle took 0.035–0.040 s (<1%). These short runs exclude frame, checkpoint and diagnostics overhead.
- Resumed service with 14 threads but default ProcessType: 346.4% CPU over ten seconds. Five-second stack sample found most threads inside native gravity, not Python.
- After Interactive service reload: 1038.8% CPU over ten seconds; status reports 14 threads. Later complete frame interval at frame 26: 13.017 s for 20 steps; the original last complete interval was 43.718 s. Approximately 3.4x faster across these particular intervals, not a controlled long-run guarantee.
- New stack sample: 14 threads; worker threads spent approximately 10–21% of samples sleeping in condition-variable waits. This demonstrates real waiting between parallel work, explaining part of the remaining difference from 1400%. It does not identify exact physical-core placement. The 1400% figure is an upper bound, not a requirement for a correct 14-thread run.

Raw structured evidence: thread_profile.json, thread_stages.json, live_thread_profile.json, thread_sample_interactive.json. CPU percentages use process CPU-time delta divided by monotonic wall time. Stack-sample percentages represent sampled stacks, not precise CPU accounting.

## Validation and state

`PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_threads.py` passed; actual OpenMP maximum team equals the requested 14. Existing validate_api.py passed using `OBSERVATORY_TEST_REPORT` directed to api_validation_threads.json; preserved historical reports. Browser checked the 14-thread estimate caption with no console errors. Shell syntax and installed plist validation passed.

The production run was paused/checkpointed, restarted and resumed from its saved state, never reset. It is running with 14 threads under the updated LaunchAgent; the other paused experiment was not resumed. One immediate bootstrap attempt raced service teardown; retry after teardown succeeded. There were pre-existing uncommitted edits by another agent; they were preserved, with the pre-change diff saved in work/pre-thread-fix.log. This fix has not been committed over those edits.
