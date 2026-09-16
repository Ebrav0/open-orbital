# Agent handoff — Open Orbital

## Local Git setup (2026-09-16)

Initialized a local repository on `main` and captured the current revision-3 project as the initial baseline. Earlier agent edit history is unavailable; archived run sources and historical benchmark files remain the older evidence. No remote was created. Source, documentation, helper scripts, bundled assets, and benchmark evidence are tracked; installed runtimes, live experiment data, logs, caches, and local environment secrets are ignored and remain on disk. See `outputs/GIT_GUIDE.md` for handoff and recovery commands.

Validation: inspected the staged file list, checked ignored runtime/data paths with `git check-ignore`, checked staged whitespace (one pre-existing indentation warning in bundled `three.core.js`, left unchanged; project-owned files passed), and verified the initial commit and clean working tree. No application code changed or numerical tests ran. The server was not restarted and no simulation controls were sent. The preceding read-only review found `cee19b92a783` paused at 36 frames; older running-state notes below are historical.

## Private GitHub remote (2026-09-16)

Created the private repository https://github.com/Ebrav0/open-orbital and connected it as `origin`. Push commits to share changes across agents and computers; saving a file alone does not sync it. Live simulation data and installed runtimes remain ignored. No simulation code or running process changed.

## Durable experiment queue — Codex (2026-09-16)

Added a persistent sequential queue with mixed galaxy/planet runs, Add to queue, Move up/down, Start queue, Hold queue, and confirmed removal. Saved configs are immutable drafts once queued. Queue current work pauses the batch; unrelated old paused runs do not. Failures and server restarts hold dispatch for review. One scheduler thread uses the HTTP mutation lock and waits for worker exit before advancing. Queue state is atomically saved in the data directory; queued jobs count toward 12 saved runs, and free-space checks account for waiting work. See observatory README for endpoints and recovery semantics. Physics is unchanged.

Validation: existing `validate_api.py` passed with `OBSERVATORY_TEST_REPORT="$PWD/outputs/observatory/api_validation_queue.json"` and `PYTHONPATH="$PWD/work/openmp"`; historical reports were preserved. `validate_queue.py` passed all nine assertions recorded in `queue_validation.json`: durable order, reordering, restart hold, pause barrier, hold while finishing, sequential completion, cancellation, failure hold, explicit continue. The first failure fixture used an empty mass list (valid fallback); corrected it to an invalid mass string and reran successfully. Browser tests on isolated port 8768 added three planetary runs, reordered and completed them, checked a 700px layout without horizontal overflow and desktop at 1920px, and reported no console errors. Screenshots: queue-mobile.png / queue-desktop.png. Removed sticky action positioning because it covered queue controls when scrolled.

Production server restarted gracefully only after active run ef1911feb4ff completed (168 frames). Saved checkpoint jobs were preserved; 60f9f09c5698 becomes interrupted after the normal server shutdown, available to resume. No production experiments were queued or deleted. Queue starts empty and held. A later live check showed a newly created production run f747e062e82e computing (31 frames); this agent did not create or alter that run. Ten experiments are now saved, leaving two queue slots under the existing cap. Remaining limitations: server must remain running; restart requires explicit continuation; queue does not bypass the 12-run cap or add a RAM cap. Test run data is isolated under ignored work/queue-ui-data.

## Current state
A functioning local observatory with a Python HTTP server, CPU REBOUND workers and a Three.js browser viewer. Both requested modes are implemented and tested. The latest galaxy is **model revision 3** (parameterized structure + optional stellar lifecycle); revision 2 remains the comparison run. There are four protected saved experiments (`0e45a855ba11` revision-1 galaxy, `44c528079f88` revision-2 galaxy, `ff56d195ce89` original Solar System, `58ab7c268cdd` 3× Jupiter) plus one revision-3 example (`ce051010c143`, 10,000 particles, lifecycle speed 40, central black hole — created from the Compute page during UI verification; removable). No simulation should need to run merely to view them.

**Server state (2026-09-15 ~22:43 local).** Port 8766 is running (`run.sh` PID 553). The 200,000-particle run `cee19b92a783` was resumed from checkpoint frame 11 and is **running** (worker PID 794, 14 threads). Measured after resume: frame 12 saved at 5.06 model time / ~124 Myr, ~48 s for that chunk. Remaining **prediction** from that rate: ~226 frames × ~48–54 s ≈ 3.0–3.4 h wall (the pre-start estimator of ~1.66 h total is faster than this measured 200k+lifecycle pace). Do not treat that as a calibrated ETA. Ctrl+C on the server terminal is a graceful shutdown and would interrupt this job again.

## Overnight resume of `cee19b92a783` (2026-09-15 ~22:43)
Before resume: `PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py` on isolated port 8767 (9.3 s) → `api_validation_r3.json`. Pause/recovery, 24-byte frames, planets energy 4.17e-16, `/lab` Start+Stop. Physics tests were not re-run (no IC change). Disk 311 GiB free. No other active job.

Then `POST /api/jobs/cee19b92a783/control` `{"action":"run"}`. Worker loaded `checkpoint-000010.bin` + `baryons-000010.npz`. Phase went interrupted → running; frames 11 → 12 in 48.3 s. control.json is `run`. Leave it running overnight.

## Compute dashboard: live estimates, even split, cooperative stop (2026-09-15)
Requested: wall-time estimate should follow the sliders; pause should actually stop the integrator; if pause is commanded, show how long until it takes effect; Start and Stop on the right; the two Compute columns split evenly.

**Layout.** `/lab` is `grid-template-columns: 1fr 1fr` (measured 960 px / 960 px at 1920). Left: sliders, notes, Reset. Right: sticky **Start computation** and **Stop computation** (label becomes Resume / Cancel pause / Writing checkpoint). Below 1100 px the columns stack; Start/Stop stay in the status column.

**Live estimator.** Dragging N, threads, duration, dt or lifecycle updates a large “estimated wall” readout on the right from the existing scaling (`157.84 s × n/1e5 × ln n / ln 1e5 × steps/500 × 10/threads × 1.15 if lifecycle`). The duration slider’s max shrinks with the 120 h cap (measured: 200k × 1 thread → max 1,122 model units, matching the API over-budget text). θ and softening are **not** in the timing model.

**Pause.** The worker used to honor pause only between saved frames (~54 s at 200k). It now checks `control.json` about four times a second between single leapfrog steps, then writes phase `pausing` and a checkpoint. `POST /api/jobs/:id/control` returns `{ok, status}` including `pause_pending` and `pause_eta_seconds` (upper bound: last chunk wall / steps per frame). The right pane shows a countdown, then “Writing a checkpoint”. Browser: a 30k disposable run went Computing → Pausing (banner visible) → Paused in <1 s and frames stopped at 4; that run was then deleted. Pause does not interrupt a leapfrog step already inside REBOUND C; at 200k one step can still take ~1 s (prediction from the 54 s / ~46-step chunk). Checkpoint I/O is extra.

**Tests.** `PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py` → `outputs/observatory/api_validation_r3.json` (9 s, port 8767): pause_pending on control, frames freeze while paused, restart+resume identical first frame, 24-byte xyzsmt, summary 3,158 bytes, planets energy 4.17e-16, `/lab` has Start and Stop and no Three.js. Historical `api_validation.json` / `validation.json` were not modified. Physics tests were not re-run (no IC change).

**Browser (Cursor Chromium).** Desktop 1920: even split, Start/Stop on the right, estimate 3.8 min → 18 s (10k) → 8.0 min (200k) → 1.07 h (200k × 1 thread) as sliders moved; JS heap 2 MB. Narrow 700: columns stack. No console errors observed during these checks.

## Revision 3 — galaxy parameter lab (From Cursor, Claude Fable 5.1, 2026-09-15)
Plan: `~/.cursor/plans/galaxy_parameter_lab_1093fc9f.plan.md` (not edited). Everything below is implemented and measured unless marked as a prediction.

**Two pages.** `/` (and `/observe`) is the Three.js viewer, unchanged in role. `/lab` (and `/compute`) is the new **Compute** page: `static/lab.html`, `static/lab.js`, `static/shared.js`. The Compute page has no import map, no canvas, no Three.js, no `requestAnimationFrame` loop and never requests `/api/jobs/:id/frames`; it polls `GET /api/jobs?view=summary` every 2 s while visible (paused when `document.hidden`). Both topbars carry **Observe | Compute** page tabs. Switching pages is a full navigation, so the WebGL context and frame cache are destroyed when leaving Observe.

**Sliders (all visible, no disclosure).** Schema in `static/shared.js` (`GALAXY_SLIDERS`, `PLANET_SLIDERS`); the validation authority is `SCHEMA` in `server.py` (`GET /api/schema` exposes it). Galaxy: `n` {10k, 30k, 100k, 200k}, `threads` {1,4,8,10,14}, `duration` (model time units; max from the 120 h estimator), `seed`, `disk_mass`, `halo_mass`, `disk_fraction`, `disk_scale`, `disk_thickness`, `halo_scale`, `warmth`, `smbh_mass`, `lifecycle_enabled`, `gas_fraction`, `t_sf`, `lifecycle_speed`, `sf_density_bias`, `imf_mmin`, `imf_mmax`, `grow_rate`, `sn_kick_kms`, `theta`, `softening`, `dt`. Planets: `duration` 1–50 yr, `jupiter_mass` {1,3,10}, eight `planet_mass_scale` sliders 0.25–10, `perturber_mass` 0–0.01 M☉ (0 = off; adds a tenth body), `perturber_a`. Plus a free-text `notes` field saved in `config.json`. Draft persists in `localStorage["orbital-lab-draft-v1"]` (debounced 200 ms, <8 KB) and is cleared on a successful Start.

**Start computation** always creates a new job (`POST /api/jobs`). Sliders never touch a live integrator. Pause/Resume use the existing control endpoint. **Remove** (`DELETE /api/jobs/:id`) shows a confirm dialog with id, mode, N and "This deletes frames and checkpoints on disk."; paused jobs add "This will stop the paused worker, then delete." The server refuses (400) for the four protected ids and for `running|initializing|queued`; for paused it SIGTERMs, waits ≤20 s, then `rmtree`. Unknown ids return 404.

**Physics (`physics.py`).** `galaxy(n, seed, theta, dt, **knobs)` now returns `(sim, meta, baryons|None)`; `GALAXY_DEFAULTS` reproduce revision 2 **bit-for-bit** when `lifecycle_enabled=False` (measured: max |Δstate| = 0.0 vs the archived `44c528079f88/model_source.py` at N=2048). Rotation curve, Jeans support, vertical frequency and asymmetric drift recompute from `disk_mass`, `halo_mass`, `disk_scale`, `disk_thickness`, `halo_scale`, `warmth`, `smbh_mass`. The SMBH replaces the last halo particle so N is unchanged. `planets()` takes `planet_mass_scale`, `perturber_mass`, `perturber_a`. `MODEL_REVISION=3`.

**Stellar lifecycle (`stellar.py`).** Types (uint8): 0 gas, 1 protostar, 2 MS, 3 giant, 4 WD, 5 NS, 6 stellar BH, 7 halo, 8 SMBH. Only disk slots lifecycle. Birth: `sfr = M_gas / t_sf` per lifecycle-Myr, fractional slot debt carried; slots chosen by `sf_density_bias` × grid-cell occupancy rank + (1−bias) × random (O(N) grid, cell 0.15 length units; never all-pairs). Kroupa IMF sets the clock mass `m_star`; the slot's gravitational mass is unchanged at birth. Protostars (m_star ≥ 2 M☉) accrete from same/neighbouring-cell gas at `grow_rate` per Myr until `clip(0.05 t_ms, 0.1, 3)` Myr. `t_ms = clip(10⁴ m⁻²·⁵, 3, 20000)` Myr; MS until 0.9 t_ms, giant until t_ms. Death: <8 M☉ WD, 8–20 NS, >20 BH; the **remnant fraction** of slot mass is kept, the rest goes to nearby gas (counted in `mass_return_failed` if no gas within the 27-cell neighbourhood). Optional `sn_kick_kms` on NS/BH. RNG is `default_rng([seed, sim.steps_done])`, so resume reproduces the same rolls (measured: identical masses and types after checkpoint/reload + 20 steps). The worker calls `stellar.step` **after every leapfrog step** when enabled. Gravity uses REBOUND's live masses via `set_serialized_particle_data`.

**Data format.** New runs write `frame_layout: "xyzsmt"`, `bytes_per_particle: 24` (x, y, z, speed, mass, type as float32). Legacy runs stay 16-byte; the server seeks with `meta.get('bytes_per_particle', 16)` and the viewer picks the stride from meta (`InterleavedBuffer` with stride 4 or 6). Checkpoints are `checkpoint-NNNNNN.bin` + `baryons-NNNNNN.npz` (type, age, m_star, birth_time, counters); `checkpoint.json` carries `baryons`; the last two pairs are kept. New run folders archive `model_source.py` and `stellar_source.py`.

**Budget.** Estimator (server and client): `157.84 s × (n/1e5) × ln n / ln 1e5 × (steps/500) × (10/threads) × 1.15 if lifecycle`; planets `0.25 s × duration/12 × (bodies/9)²`. Jobs whose estimate exceeds **120 h** are rejected with the maximum span. The worker stops with phase `interrupted` and `wall_capped: true` when accumulated `wall_seconds ≥ 120 h`; a manual Resume grants another 120 h window (recorded in `status.wall_cap_at`). This estimator is a scaling from one measured revision-2 point; 200k and lifecycle timings are **predictions**, not measurements. Disk check: 1.5 × frames + two checkpoint pairs + 2 GiB floor. Still one active job and at most 12 runs.

**Measured results (this session).**
- `tests/validate_physics.py` → `outputs/observatory/validation_r3.json` (13 s): lifecycle-off 2048 runs match the historical bounds (energy change 4.40e-5 at dt 0.02/θ 0.4, 5.69e-6 at dt 0.01; disk radius +10.7%); revision-2 reproduction difference 0.0; heavier disk (3×) rotates 1.19× faster; lifecycle speed 40 over 500 steps: total-mass drift 0.0, baryon-mass drift 2.2e-16, 307 births, 61 deaths, 3 supernovae, WD/NS/BH present, N fixed, halo slots untouched; lifetimes monotonic; Kroupa sample median 0.24 M☉, 0.6% above 8 M☉; resume RNG difference 0.0.
- `tests/validate_api.py` → `outputs/observatory/api_validation_r3.json` (9 s, port 8767, temp dir): `/lab` has no canvas/three; `lab.js`/`shared.js` contain no three import and no `/frames` call; bad knob 400; 200k×1-thread×5000 rejected ("Estimated 535 h exceeds the 120-hour compute cap"); full-knob lifecycle job with SMBH: 24-byte frames, mass column sums to disk+halo+SMBH, summary job JSON 3,096 bytes with no `times`; baryon npz present in the checkpoint pair; server restart → interrupted → resume → complete with identical first frame; log tail; preview returns 8000×24 bytes in a subprocess; scaled-planet + perturber run (10 bodies) energy change 4.2e-16; DELETE running → 400, protected → 400, unknown → 404, finished → folder gone then 404.
- Browser (Cursor embedded Chromium, 1920 px and 700 px): all 24 galaxy controls visible without disclosure; Start created `ce051010c143`; status, ETA, diagnostics and events updated live; Pause → Resume → Pause → Remove-while-paused worked with the specified confirm text; protected runs show "Preserved" with no Remove; Observe plays the revision-3 run (stage legend, "Energy change (lifecycle on; not an error bound)") and the revision-2 and Solar System runs; no console errors on either page. **Compute memory soak:** 30 s of polling with 600 programmatic slider changes → `performance.memory.usedJSHeapSize` 5 MB (total 6 MB), zero frame requests, only `lab.js` loaded. The Chrome Task Manager per-tab figure could not be read from the embedded browser; with a 5 MB heap and no GPU context, the tab is expected to sit at browser-shell baseline (~50–100 MB), a **prediction** until checked in the user's Chrome.
- Historical `validation.json`, `api_validation.json`, `test_instance_results.json` and the four saved runs were not modified (mtimes unchanged).

**Outstanding / honest limits.** The lifecycle is collisionless bookkeeping (no SPH, cooling, feedback energy or chemistry); `lifecycle_speed ≠ 1` is a laboratory clock, never calibrated. Energy is not a conservation test when the lifecycle is on. The 120 h estimator has one measured anchor. Multi-galaxy encounters, isochrones and a worker RAM cap are not implemented. The embedded browser reports ~1–2 FPS for WebGL playback (software rendering); the user's Chrome/Safari was not measured this session. The Observe sidebar "Compute new experiment" button posts defaults for everything except N, threads, span and Jupiter mass; full editing is on Compute.

**Server state at handoff.** Port 8766 was serving the revision-3 code with all jobs complete. `Start OpenOrbital` is a zsh function plus `~/.local/bin/Start-OpenOrbital` → `outputs/observatory/start.sh`. Measured: with the existing listener, the command reused PID 97425 (did not restart) and opened `/lab`. New shells need a fresh Terminal tab so `~/.zshrc` is loaded.

## Files and responsibilities
- `outputs/observatory/physics.py`: parameterized initial conditions and scientific diagnostics. Galaxy uses a warm exponential stellar disk and live Plummer halo with approximate Jeans support, optional central black hole and optional lifecycle arrays. Planets use JPL approximate J2000 elements, not current ephemerides; masses can be scaled and a perturber added.
- `outputs/observatory/stellar.py`: collisionless stellar lifecycle (IMF, birth, accretion, aging, death/remnants, mass return, kicks) operating on REBOUND masses in place; baryon checkpoint save/load.
- `outputs/observatory/worker.py`: one isolated integration process; lifecycle after every leapfrog step when enabled; publishes versioned frames, polls control.json, saves checkpoint + baryon pairs, enforces the 120 h wall cap and handles termination.
- `outputs/observatory/server.py`: loopback HTTP API, `SCHEMA` validation, 120 h estimator, one-active-job scheduling, protected-run DELETE rules, summary view, log tail, subprocess preview and static assets (`/` viewer, `/lab` Compute). No authentication or cloud dependencies; keep the listener on loopback.
- `outputs/observatory/static/app.js`: Observe page — scene creation, GPU frame interpolation with stride from meta, stage coloring, cache, controls and API polling. Geometry buffers are reused to avoid GPU buffer growth.
- `outputs/observatory/static/lab.html`, `lab.js`, `shared.js`: Compute page — slider schema, estimator, Start computation, status polling, Remove, heap footer. Must never import three or fetch frames.
- `outputs/observatory/static/style.css`, `index.html`: responsive layout, accessible controls and labels for both pages.
- `outputs/observatory/run.sh`: derives the project root from its own location; uses the existing Python environment and native library.
- `outputs/observatory/start.sh`: terminal launcher used by `Start OpenOrbital`; reuses a healthy :8766 server, otherwise starts `run.sh` and opens the Compute dashboard.
- `outputs/observatory/tests/`: numerical checks and an isolated server-restart test.
- `outputs/observatory/validation.json`, `api_validation.json`, `test_instance_results.json`: revision-2 recorded evidence, not configuration. `validation_r3.json`, `api_validation_r3.json`: revision-3 evidence. Tests write only the `_r3` files.
- `outputs/`: earlier benchmark source, figures and raw results. Keep them as provenance.
- `work/observatory-data/<id>/`: saved experiments. `config.json` is the input, `meta.json` describes units/times/components, `status.json` is worker progress. `model_source.py` archives the generator for new runs.

## Data and checkpoint contract
`frames.bin` is a sequence of fixed-size frames. Legacy runs (no `meta.bytes_per_particle`) store N records of four little-endian float32 values: x, y, z, speed (N*16 bytes per frame). Revision-3 runs store six: x, y, z, speed, mass, type (`frame_layout: xyzsmt`, N*24 bytes). Always read the stride from meta. `meta.times` provides the time of each frame. Frames are appended and flushed before status advertises their availability. The browser converts axes for display and interpolates between saved frames; it does not integrate physics.

New checkpoints use a numbered binary and an atomically replaced checkpoint.json pointer. The pointer records the frame index and diagnostics. Resume truncates frames beyond the committed checkpoint and integrates forward. The prior checkpoint is retained. Older saved runs may use checkpoint.bin; backward compatibility remains in worker.py.

## Launch and validation

From any directory in a new Terminal window:

```sh
Start OpenOrbital
```

That command is a zsh function in `~/.zshrc`. It runs `outputs/observatory/start.sh`: if http://127.0.0.1:8766/api/jobs already answers, it only opens the Compute dashboard; otherwise it starts the server in the foreground (Ctrl+C is still a graceful shutdown) and opens http://127.0.0.1:8766/lab when the API is ready. Equivalents: `Start-OpenOrbital` on PATH, or double-click `Start Open Orbital.command`.

To start the server without opening a browser:

```sh
cd "/Users/emmanuelbravo/Desktop/Open Orbital"
sh outputs/observatory/run.sh
```

In another terminal, as needed:

```sh
PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_physics.py
PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py
```

The API test creates temporary data and uses port 8767. It verifies pause, rejection of a second active job, graceful server restart, checkpoint recovery and unchanged initial frame bytes. The first attempt used an unnecessarily long run and exceeded its test timeout; the final bounded test passed. It does not alter the viewer's saved runs.

## Verified evidence and limits
The revised 100,000-particle run used 10 threads, took 157.84 active seconds, saved 168 frames and covered 245 Myr. Disk half-radius changed +1.93%; angular momentum changed 0.0536%. The large-run energy estimate has substantial Monte Carlo uncertainty and must not be presented as a precision conservation check. The small 2,048-particle numerical tests are separate evidence. The 12-year Solar System run saved 2,401 frames with relative energy change 1.17e-15. Browser checks covered both modes, new experiment creation, layers, timeline, cameras and desktop/mobile layouts; console was clean.

Galaxy limitations: approximate distribution function; no gas, stellar evolution, relativity or close-binary model; long-term equilibrium unproven. Original revision-1 run contracted about 12% and remains for comparison. The disk was improved using its rotation curve, warmer velocities and Jeans support, not artificial damping.

## Runtime portability
All files were moved from the Codex task directory into this folder. Compatibility symlinks remain at the old path so prior chat links work. Launchers are root-relative; virtualenv text scripts were repointed. Historical logs/JSON may retain old absolute paths as provenance.

The Python executable ultimately depends on this Mac's Homebrew installation, and the native OpenMP build links to `/opt/homebrew/opt/libomp/lib/libomp.dylib`. For another machine, create a new venv and install outputs/observatory/requirements.txt; rebuild REBOUND for that platform rather than copying its binary. `outputs/build_openmp.sh` records this Mac's compiler/SDK flags. It also runs benchmarks when invoked, so inspect it before reuse. macOS 26.5 SDK was selected to avoid a local SDK 27 linker mismatch.

## Sensible next work, not yet implemented
Improve disk equilibrium over multiple orbital periods; add a validated second-galaxy encounter (two–five galaxies); SPH or a feedback-energy model; isochrone-based stages; inspector comparison charts across runs; a worker RAM hard cap; measure the 120 h estimator at 200k and with lifecycle on. First preserve the working two-page, two-mode observatory. Do not imply those future features already exist.
