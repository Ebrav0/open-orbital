# Agent handoff — Open Orbital

## Two-phase ISM (model revision 5) — 2026-09-18

Added a laboratory two-phase ISM on the existing O(N) density grid. Gas parcels now carry specific internal energy and metallicity. After every leapfrog step they can feel grid pressure, ram drag, CIE-like cooling Λ(T,Z), and Stinson-like delayed supernova heat. Star formation may only consume cold, dense, non-expanding gas. This is **not SPH**. Isolated `n_galaxies=1` collisionless ICs are unchanged (same DF; generator stamped 5). Historical validation JSON was not rewritten.

**Knobs (Compute, group Interstellar medium).** `ism_enabled` (default on with the lifecycle), `metallicity` (Z/Z☉), `cooling_speed`, `sn_feedback`, `ram_pressure`, `n_sf`. Lifecycle-off jobs never run the ISM. Draft key `orbital-lab-draft-v3`. Estimator ×1.12 when ISM+lifecycle (prediction, not a measured point).

**Per-frame peek.** Energy sampling stays on the 40-frame cadence. `stellar.peek` copies T, cold/hot mass, Z and counts after every saved galaxy frame without resetting the SFR window. Compute charts gas temperature; Observe shows T and cold/hot mass. Shock/SN laboratory heat is listed in Compute diagnostics.

**Files.** `ism.py` (new); `stellar.py` type 9 = hot/ionized gas, baryon arrays `u`/`Z`/`cool_delay`/`z_birth`; worker archives `ism_source.py`; Observe paints hot gas rose; Compute shows T, cold/hot mass, Z, and a fourth sparkline.

**Measured physics.** `PYTHONPATH="$PWD/work/openmp:$PWD/outputs/observatory" work/venv/bin/python outputs/observatory/tests/validate_physics.py` → `validation_r5.json` (64 s, pip rebound 5.1.1, no OpenMP tree). Isolated vs `n_galaxies=1` max |Δstate| = 0; vs `origin/main` revision-3 `physics.py` max |Δstate| = 0. Lifecycle-off 2048 energy 4.40e-5 / 5.69e-6 (same bounds as r3/r4). Lifecycle-off-ISM speed-40 500 steps: mass drift 0.0, 307 births, 60 deaths, 5 SN (matches this cloud’s serial r4). Cooling curve metal-line peak at 2.47×10^5 K; delayed parcels stay at 5×10^5 K while undelayed drop to the 8×10^3 K floor. Two approaching clumps: gas momentum drift 0, v_rel 2.4 → 1.02. Hot gas rejected for SF. ISM+lifecycle 80 steps: mass drift 0.0, mean T 9742 K. Two-galaxy ISM 40 steps: mass drift 1.7e-16, finite, hot gas mass 0.007. ISM checkpoint resume max |Δstate| = 0. `peek` leaves `born_mass` untouched; `summary` still zeros the SFR window. Historical `validation.json` / r3 / r4 mtimes unchanged (2026-09-17).

**Measured API.** `PYTHONPATH="$PWD/work/openmp:$PWD/outputs/observatory" work/venv/bin/python outputs/observatory/tests/validate_api.py` → `api_validation_r5.json` (40.5 s, isolated 8767). Revision 5; `ism_enabled` in schema; pause/restart first frame identical; 201 frames; baryon npz has `u`/`Z`/`cool_delay`; over-budget 629 h; summary 6463 B; planets E 2.78e-16; history has gas T with **153** unique rounded kelvin samples (the 40-frame energy cadence would have been ~6). Historical `api_validation.json` / r3 / r4 mtimes unchanged.

**Live 8766.** Tmux `observatory-8766`, `OBSERVATORY_DATA=/workspace/work/observatory-data`, `daemon=false`, `worker_pid=null`. Disposable job `2cc4bf79b375` **complete**: 10,000 particles, 2 galaxies, ISM on, ram 2, lifecycle speed 40, duration 2, 101 frames, 18.5 s wall. Event log: hot ionized gas at 20 Myr; galaxies overlapping. jsonl peak hot mass 0.004 (3 parcels), T up to 3.03×10^4 K; final status T 20628 K, hot mass 0, shock_heat 0.241. That job was integrated **before** per-frame peek, so its T history is the 40-frame staircase. No 1M science job was started. Ctrl+C is a graceful shutdown.

**Browser (embedded Chromium).** Compute desktop: Interstellar medium group shows Two-phase ISM, metallicity 1 Z/Z☉, cooling 1, SN coupling 0.15, ram 1, n_sf 0.1. Lifecycle off dims those rows with “not used unless stellar lifecycle is on”; ISM off leaves the master checkbox usable and dims the rest with “not used unless two-phase ISM is on.” Selecting `2cc4bf79b375` loads ram 2 / SN 0.3 / lifecycle 40 and draws a fourth **Gas temperature** sparkline. Network filter `frames` matched **0 / 69** requests; no canvas. 700 px: columns stack, ISM sliders reachable, no overflow covering controls. Observe: caption `STELLAR DISK / LIVE DARK-MATTER HALO / STELLAR LIFECYCLE / TWO-PHASE ISM`; inspector **20,628 K** and cold/hot **0.0248 / 0.00 ×10¹⁰ M☉**; Component legend includes Hot gas; Galaxy mode shows two birth-colored clumps; run list `… lifecycle · ISM`. Playback and timeline scrub update the particles (software WebGL, ~25–80 FPS). Energy change 17.4% ± 13.1% is displayed as lifecycle/ISM on, not an error bound. No JS errors. No new job was started.

**Outstanding / honest limits.** Superparticles; no SPH kernel or Riemann solver; SN coupling is a laboratory parameter; blast delay is 15 simulation Myr, not the stellar clock, so `lifecycle_speed=40` can keep overlapping blastwaves; unresolved CNM is an 8e3 K floor; not a calibrated MW ISM. Energy change with ISM on is not an error bound. Mean T ~10^4 K in the 80-step isolated test is the Field warm attractor, not a proof of a two-phase CNM. The 10k encounter’s type-9 count peaked at 3 parcels.

## Rebase onto collision lab (2026-09-17)

## Rebase onto collision lab (2026-09-17)

Kept origin/main 2–5 clone-galaxy physics (`build_one_galaxy` / `place_galaxy`, draft `orbital-lab-draft-v2`). Overlay: 1,000,000 particle stops, `MAX_RUNS=24`, Barnes–Hut `apply_tree_box`, LaunchAgent trampoline, lined-up Compute control room, Observe byte-capped frame cache. Resume after a daemon restart now `spawn()`s a paused job (adopt if the worker is still alive). Historical `validation.json` / r3 JSON were not rewritten. Library on 8766 is empty (`GET /api/jobs` `[]`); `PROTECTED` ids still refuse API DELETE if recreated.

**Measured after the rebase merge.** `PYTHONPATH="$PWD/work/openmp" work/venv/bin/python`. Physics → `validation_r4.json` (14.3 s): isolated vs `n_galaxies=1` max |Δstate| = 0; 2048 energy 4.40e-5 / 5.69e-6; two-galaxy head-on 19.79 → 16.44; five-galaxy slices 820+819×4; retrograde L_z A=+2.06 B=-4.57. API → `api_validation_r4.json` (9.9 s, port 8767): `n_choices` 10k…1M; `n=250000` rejected; `n_galaxies=6` → 400; five-galaxy N=10k OK; pause survives restart then Resume completes 201 frames; first frame identical; isolated `n_galaxies=1` OK; `/lab` has `health-strip` and no Three.js; `max_runs=24`. No 1M science job was started. Live 8766 was not restarted.

## Galaxy collision lab — model revision 4 (2026-09-16)

Implemented 2–5 live N-body galaxies on the existing CPU tree. Isolated `n_galaxies=1` uses the revision-3 disk+halo DF (generator stamped 4). Galaxy A keeps the full knobs; galaxies 2–5 are compact clones. Default **new** Compute/HTTP job is `n_galaxies=2`; `galaxy()` / `GALAXY_DEFAULTS` still default to 1 so omitted keys replay as isolated. Frames stay 24-byte `xyzsmt`. Compute tab still has no Three.js. No canned merger path.

**Physics.** `build_one_galaxy` + `place_galaxy` + mass-weighted N split (min 256/galaxy, remainder on A). Encounter geometry: spin → disk tilt about x → COM at `(sep, impact, 0)` with bulk `(-vrel, 0, 0)` → `R = Rz(azimuth) @ Ry(inclination)`. Tree `root_size=2048` only when `n_galaxies>1`. One `move_to_com()` after assemble. `stellar.py` uses `disk_mask` (contiguous per-galaxy disk slices); old baryon npz without the array infers a disk prefix.

**Compute / API.** Encounter + Galaxy 2–5 groups always visible; unused clone rows get class `unused`. Estimator ×1.05 if `n_galaxies>1` (prediction). `n_galaxies=6` is 400. Draft key `orbital-lab-draft-v2`. Notes provenance: `From Cursor, Grok 4.6: galaxy encounter lab (revision 4)`.

**Observe.** Color mode Galaxy from `meta.galaxies` index ranges (no extra frame bytes). Camera uses `meta.camera_distance` when present. Sidebar shows `N galaxies · …` for encounters.

**Tests (measured in this cloud workspace).** `work/venv/bin/python` (pip rebound 5.1.1, no OpenMP tree). Historical `validation.json` / `validation_r3.json` / `api_validation.json` / `api_validation_r3.json` mtimes unchanged.

```
work/venv/bin/python outputs/observatory/tests/validate_physics.py
work/venv/bin/python outputs/observatory/tests/validate_api.py
```

- Physics → `outputs/observatory/validation_r4.json` (61 s): isolated vs `n_galaxies=1` max |Δstate| = 0; vs `origin/main` revision-3 `physics.py` max |Δstate| = 0 (archived `44c528079f88/model_source.py` is not in this workspace). Lifecycle-off 2048 energy change 4.40e-5 at dt 0.02 / θ 0.4 and 5.69e-6 at dt 0.01 (same bounds as r3). Two-galaxy head-on N=2048: slices 1024+1024, separation 19.79 → 16.44 after 80 steps, finite. Five galaxies N=4096: slices 820+819×4, finite. Retrograde g2_spin=-1: L_z(A)=+2.06, L_z(B)=-4.57. Two-galaxy lifecycle 200 steps: mass drift 1.7e-16, disk_mask length N, halo types unchanged. Isolated lifecycle speed 40 / 500 steps: mass drift 0.0, 307 births; deaths/SN 60/5 on this serial tree (r3 JSON recorded 61/3 on the Mac OpenMP build — same stellar.py on this IC stream matches 60/5).
- API → `outputs/observatory/api_validation_r4.json` (40 s, port 8767, temp dir): `n_galaxies=6` → 400; `n=10000` `n_galaxies=5` OK; 2-galaxy POST: `meta.n_galaxies==2`, `model_revision==4`, 24-byte frames, two SMBHs, baryon mass 2.4, pause/restart first frame identical, summary 5,458 bytes with `galaxies` kept; isolated `n_galaxies=1` OK; `/lab` has Start+Stop and no Three.js; protected DELETE 400.
- Browser (embedded Chromium): Compute shows Encounter + Galaxy 2–5 with no disclosure; Galaxy 3–5 unused rows dim with “not used unless galaxy count ≥ i”; estimate names 2 galaxies and first passage ~245 Myr; Start/Stop on the right; 700 px columns stack. JS heap 1.8 MB; zero `/frames` requests from Compute. Observe Galaxy color mode shows a 5-swatch legend and two birth-colored clumps. No JS errors.

**Server.** Port 8766 is serving this revision-4 code with disposable job `d81656302d72` **complete** (10,000 particles, 2 galaxies, 201 frames, lifecycle off) under `work/observatory-data` (gitignored). Ctrl+C is a graceful shutdown. Tests used 8767.

**Outstanding / honest limits.** Superparticles, collisionless, no SPH/ram pressure, no FoF remapping. Default 245 Myr is a first passage, not MW–M31. Barnes–Hut with several dense concentrations is coarser than an isolated galaxy. Birth-galaxy colors stay frozen. This cloud workspace has no archived `44c528079f88/model_source.py`; isolated bit-match is against `origin/main` revision-3 `physics.py` when git is available.

## Compute page alignment (2026-09-17)

Compute is now a two-column control room with a shared form grid. Labels, sliders, and values share the same x-positions (measured at 1920: labels x=28, tracks x=248–260, values x=799). Seed is no longer duplicated. Right-hand status, queue, history, metrics, diagnostics, events, and saved runs sit in matching cards. Start spans the action row; Add to queue and Stop sit side by side. Compute still has no canvas or Three.js.

**Measured.** `PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py` (12.6 s, isolated 8767): `/lab` still has Start/Stop/`health-strip` and no canvas. Browser 1920: galaxy and planetary grids aligned, no horizontal overflow, Start enabled, **0/24**. 700 px: columns stack, `scrollWidth=700`, Start remains in the status card. Observe header still has Observe/Compute plus Galaxy/Planetary. No science job was started. Live 8766 was not restarted (static assets only).

## Cleared the library; save cap 24 (2026-09-17)

User asked to remove all former runs and save 24. All 12 experiment folders under `work/observatory-data` are gone, including the four previously protected comparison copies (`0e45a855ba11`, `44c528079f88`, `ff56d195ce89`, `58ab7c268cdd`). Unprotected ids were `DELETE`d through the live API; the protected four were removed on disk because the API still returns 400 for those ids. `MAX_RUNS` is now **24**. Historical benchmark JSON (`validation.json`, r3/r4, `validation_1m.json`) was not deleted. No new science job was started.

**Live 8766.** LaunchAgent `com.openorbital.observatory` kickstart after the cap change (Python PID 74647). `GET /api/jobs` is `[]`. `GET /api/system`: `max_runs=24`, `daemon=true`, `worker_pid=null`, `sleep_prevention=off`. Remaining files: `daemon.json`, `queue.json` (held, empty), `server.log`. The four comparison ids remain in `PROTECTED` so a recreated folder with those names still cannot be `DELETE`d from the UI.

**Measured.** `PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py` (12.3 s, isolated port 8767): protected DELETE still 400; finished DELETE ok; pause/auto-resume unchanged. Physics tests not re-run (ICs unchanged). Browser Compute: run count **0/24**, Start enabled, galaxy and planetary lists empty. Observe: **SAVED EXPERIMENTS 0**, “A new experiment awaits”. No 1M job was started.

## Why 1M Start failed, and 1M sustain tests (2026-09-17)

The 1M computation **never queued**. Port 8766 already holds **12/12** experiments, so `POST /api/jobs` returns *12 experiments are saved. Remove a run before creating more.* There is no 1M folder on disk. The newest job `01b1cdfee9e9` is a **200,000**-particle two-galaxy encounter (duration 329, 14 threads) that ran 158 frames / 7.67 h wall then died with `Particle is outside of simulation box. Cannot add to tree` (root 1024, particles must stay in ±512). Compute now disables Start/Add to queue when the save cap is full. Protected ids were not removed.

**Tree box.** Isolated revision-4 ICs still use root 1024 (halo truncated at 100). The worker grows the Barnes–Hut root when the occupied half-width times a margin exceeds the box, and retries a leapfrog step after that error. Particles are loaded with a serialized write, then tree gravity is turned on after COM. ICs for existing N are unchanged.

**Measured (isolated, not the live 8766 library).** `validate_physics.py` still 0.0 rev2/rev3 Δstate; 2048 energy 4.40e-5 / 5.69e-6. `validate_api.py` 12.8 s including the 12/12 button copy. `validate_million.py` → `validation_1m.json` (251 s): 1M lifecycle-off init **3.29 s**, N=1,000,000, root 1024, max |x| 98.2; 20 leapfrog steps **5.67 s/step**, all finite; worker duration 0.4 completed **21 frames / 20 steps** in 123 s, 504 MB frames, no error. Escape at x=600 expanded the root to ~9600 and continued. That is a short live-tree run, **not** a 120 h proof or a calibrated galaxy. Historical `validation.json` / r3 JSON were not modified. No 1M job was added to the 12-run library.

To start 1M on 8766, Remove one unprotected run (the failed encounter `01b1cdfee9e9` and the 10k smoke `ce051010c143` are removable). Then Start from the 1M slider. Estimator ~45 min at 8 threads × 245 Myr is in the same ballpark as 5.67 s/step × 500 steps ≈ 47 min (lifecycle off); lifecycle on is slower.

## Particle ceiling 1,000,000 (2026-09-16)

Galaxy `n` stops are now 10k / 30k / 100k / 200k / 500k / 1M on Compute, Observe’s start menu, and `SCHEMA` (the server still rejects other values). Defaults stay 100,000. Physics ICs for those older N values are unchanged (no model-revision bump). The 120 h wall-time cap, 24-run cap, and disk-space check remain. Observe frame cache is byte-capped (~96 MB) so 1M playback keeps about four frames instead of twelve. 1M dots are still superparticles; a short 1M run would not prove long-term stability. Wall estimates at 500k/1M still scale from the revision-2 100k/10-thread point; the supplemental OpenMP 1M sphere step (2.274 s/step at 8 threads) is a different initial condition.

No 1M science job was started this session.

**Measured.** `PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py` → `api_validation_r4.json` (12.7 s, port 8767). `n_choices` 10k…1M; `n=250000` rejected; 200k×1 thread×duration 5000 still over-budget (535 h). Physics tests not re-run (ICs for existing N unchanged). Production 8766 LaunchAgent kickstart: PID 60770, `daemon=true`, 11 jobs, paused/interrupted unchanged. Browser Compute: slider ticks 10k/30k/100k/200k/500k/1M; readout 1,000,000; 8 threads × duration 10 estimates **45.4 min** (prediction) and ~0.99 GB engine RAM; 1 thread shrinks live max span to **198** model units. Desktop 1920 and 700 px: no horizontal overflow. Compute still has no canvas.

## Dashboard launch fix (2026-09-16)

`start-openorbital` / `Start Open Orbital.command` failed because LaunchAgent `com.openorbital.observatory` executed `outputs/observatory/run.sh` on Desktop. macOS TCC returns `Operation not permitted` (exit 126); KeepAlive was crash-looping (`runs` 10+, `server.log` filled with that line) and nothing listened on 8766. Measured: Homebrew CPython launched from `~/Library/Application Support` **can** read Desktop `server.py` and import REBOUND 5.1.1.

`install-daemon.sh` now writes `~/Library/Application Support/Open Orbital/run-observatory.sh` and a plist whose ProgramArguments are `/bin/sh` plus that trampoline, WorkingDirectory the support folder, exec of the venv’s resolved interpreter (Homebrew, not the Desktop `venv/bin/python` stub). `start.sh` reloads an unhealthy agent and, if :8766 still does not answer, unloads and `nohup`s `run.sh` from the current session. `stop-daemon.sh` also SIGTERMs a leftover observatory listener.

No physics or worker code changed. Historical validation JSON was not modified. Paused/interrupted jobs stay paused (`control=pause`); recover will not auto-resume them.

**Measured after reload.** LaunchAgent `state=running`, `runs=1`, never exited, Python PID 56320 on 127.0.0.1:8766. `GET /api/system`: `daemon=true`, `sleep_prevention=off`, `worker_pid=null`. 11 saved experiments; `cee19b92a783` still paused (36), `60f9f09c5698` still interrupted (38). `start.sh` reuse printed “already running” and kept PID 56320. Browser `/lab`: health strip “up (LaunchAgent)”, Start computation present, no canvas; galaxy tab lists 9 of 11 runs (the two planetary jobs stay on the other tab).

## Local Git setup (2026-09-16)

Initialized a local repository on `main` and captured the current revision-3 project as the initial baseline. Earlier agent edit history is unavailable; archived run sources and historical benchmark files remain the older evidence. No remote was created. Source, documentation, helper scripts, bundled assets, and benchmark evidence are tracked; installed runtimes, live experiment data, logs, caches, and local environment secrets are ignored and remain on disk. See `outputs/GIT_GUIDE.md` for handoff and recovery commands.

Validation: inspected the staged file list, checked ignored runtime/data paths with `git check-ignore`, checked staged whitespace (one pre-existing indentation warning in bundled `three.core.js`, left unchanged; project-owned files passed), and verified the initial commit and clean working tree. No application code changed or numerical tests ran. The server was not restarted and no simulation controls were sent. The preceding read-only review found `cee19b92a783` paused at 36 frames; older running-state notes below are historical.

## Private GitHub remote (2026-09-16)

Created the private repository https://github.com/Ebrav0/open-orbital and connected it as `origin`. Push commits to share changes across agents and computers; saving a file alone does not sync it. Live simulation data and installed runtimes remain ignored. No simulation code or running process changed.

## Durable experiment queue — Codex (2026-09-16)

Added a persistent sequential queue with mixed galaxy/planet runs, Add to queue, Move up/down, Start queue, Hold queue, and confirmed removal. Saved configs are immutable drafts once queued. Queue current work pauses the batch; unrelated old paused runs do not. Failures and server restarts hold dispatch for review. One scheduler thread uses the HTTP mutation lock and waits for worker exit before advancing. Queue state is atomically saved in the data directory; queued jobs count toward 12 saved runs, and free-space checks account for waiting work. See observatory README for endpoints and recovery semantics. Physics is unchanged.

Validation: existing `validate_api.py` passed with `OBSERVATORY_TEST_REPORT="$PWD/outputs/observatory/api_validation_queue.json"` and `PYTHONPATH="$PWD/work/openmp"`; historical reports were preserved. `validate_queue.py` passed all nine assertions recorded in `queue_validation.json`: durable order, reordering, restart hold, pause barrier, hold while finishing, sequential completion, cancellation, failure hold, explicit continue. The first failure fixture used an empty mass list (valid fallback); corrected it to an invalid mass string and reran successfully. Browser tests on isolated port 8768 added three planetary runs, reordered and completed them, checked a 700px layout without horizontal overflow and desktop at 1920px, and reported no console errors. Screenshots: queue-mobile.png / queue-desktop.png. Removed sticky action positioning because it covered queue controls when scrolled.

Production server restarted gracefully only after active run ef1911feb4ff completed (168 frames). Saved checkpoint jobs were preserved; 60f9f09c5698 becomes interrupted after the normal server shutdown, available to resume. No production experiments were queued or deleted. Queue starts empty and held. A later live check showed a newly created production run f747e062e82e computing (31 frames); this agent did not create or alter that run. Ten experiments are now saved, leaving two queue slots under the existing cap. Remaining limitations: server must remain running; restart requires explicit continuation; queue does not bypass the 12-run cap or add a RAM cap. Test run data is isolated under ignored work/queue-ui-data.

## Merge queue + collision lab (2026-09-16)

Fetched `origin/main` (`8e3f6a5`, persistent sequential queue) into `cursor/galaxy-collision-lab-428d`. GitHub reported `CONFLICTING` only in two files. Both hunks were simple keep-both resolutions; there was no conflicting product intent.

**Resolved.** [`outputs/observatory/static/lab.js`](outputs/observatory/static/lab.js): draft key `orbital-lab-draft-v2`, `ACTIVE=['running','initializing','pausing']` (waiting `queued` jobs are not a live worker), `let queue={enabled:false,ids:[]}`, notes provenance kept. [`outputs/observatory/tests/validate_api.py`](outputs/observatory/tests/validate_api.py): r4 coverage plus `Path(os.environ.get('OBSERVATORY_TEST_REPORT',APP/'api_validation_r4.json'))`. Auto-merged without markers: `server.py` (r4 SCHEMA + queue scheduler; `ACTIVE` omits `queued`), `lab.html` (Encounter honesty + Add to queue / queue panel), `style.css` (`.slider-row.unused` + `.queue-panel`), HANDOFF/README (both sections). Incoming from main: `validate_queue.py`, queue evidence JSON/screenshots, `.gitignore` `work/queue-ui-data/`.

**Tests (measured after the merge commit).** Isolated port 8767, `PYTHONPATH="$PWD/work/openmp"` `work/venv/bin/python`. Physics tests were not re-run (ICs / `physics.py` / `stellar.py` / `worker.py` unchanged by the merge). Historical `validation.json` / `validation_r3.json` / `api_validation.json` / `api_validation_r3.json` mtimes unchanged.

```
PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py
PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_queue.py
```

- API → `outputs/observatory/api_validation_r4.json` (40 s): `n_galaxies=6` → 400; five-galaxy N=10k OK; 2-galaxy pause/restart first frame identical; isolated `n_galaxies=1` OK; `/lab` Start+Stop and no Three.js; over-budget omitted-`n_galaxies` uses default 2 (×1.05): "Estimated 561 h … max span … 1069.0 model time units."; planets energy 2.78e-16; `model_revision` 4; 24-byte frames.
- Queue → `outputs/observatory/queue_validation.json` (25 s): all nine assertions true (order persisted, reorder, restart hold, pause blocks next, hold lets current finish, sequential completion, queued removal, error holds queue, explicit continue). Galaxy enqueue without `n_galaxies` takes Compute default 2.

**Browser (embedded Chromium on :8766 after restart).** Compute: Encounter Live galaxies default 2; Galaxy 2–5 groups always visible; 3–5 unused copy when count is 2; toggling count 2→1→2 dimmed Galaxy 2 then restored it; estimate names 2 galaxies and first passage ~245 Myr; Start / Add to queue / Stop + queue panel; queue message "Held. Queue held after server startup…"; 700 px columns stack, no horizontal overflow covering queue controls. Console: no errors. Network: no `/frames`, no `three.module`. Did not Start computation or Start queue.

**Server.** Pre-merge :8766 had only disposable `d81656302d72` **complete**; SIGINT then restarted onto this merge with `OBSERVATORY_DATA=/workspace/work/observatory-data`. `/api/queue` is present, empty, held. No experiments were queued or deleted. Ctrl+C is a graceful shutdown. Older notes below about `cee19b92a783` running on PID 553 are historical.

## Current state
A functioning local observatory with a Python HTTP server, CPU REBOUND workers and a Three.js browser viewer. Both requested modes are implemented and tested. The latest galaxy is **model revision 4** (1–5 live N-body galaxies; isolated `n_galaxies=1` still matches revision 3). Revision 3 remains the parameterized isolated lab; revision 2 remains the comparison run. There are four protected saved experiments (`0e45a855ba11` revision-1 galaxy, `44c528079f88` revision-2 galaxy, `ff56d195ce89` original Solar System, `58ab7c268cdd` 3× Jupiter) plus one revision-3 example (`ce051010c143`, 10,000 particles, lifecycle speed 40, central black hole — created from the Compute page during UI verification; removable). No simulation should need to run merely to view them.

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
- `outputs/observatory/validation.json`, `api_validation.json`, `test_instance_results.json`: revision-2 recorded evidence, not configuration. `validation_r3.json`, `api_validation_r3.json`: revision-3 evidence. `validation_r4.json`, `api_validation_r4.json`: revision-4 evidence. Tests write only the `_r4` files.
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
Improve disk equilibrium over multiple orbital periods; SPH or a feedback-energy model; isochrone-based stages; inspector comparison charts across runs; a worker RAM hard cap; measure the 120 h estimator at 200k, with lifecycle on, and with `n_galaxies>1`. Do not imply those future features already exist.
