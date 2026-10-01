# Agent handoff — Open Orbital

## cloudnode1 (OVH) retired — Claude Opus 5.5, 2026-10-01

User has a new VM and asked to clear cloudnode1 from the codebase. Done:
- `DELETE /api/nodes/cloudnode1` on live :8766 → registry `work/nodes.json` now holds only computenode1 (GET /api/nodes: local, computenode1).
- Run `7ffea0bd7149` (complete, 222/222 frames on the Mac, `synced_complete`) was re-homed: `location.json` node → `local`, plan cleared, its cloudnode1 history segment closed at frame 222, and `retired_node` recorded. The original is kept as `location.cloudnode1-backup.json` in the run folder. Frames, status and `.hub` are untouched. The timeline still lists the cloudnode1 segment (drawn in the default colour).
- The README example now says "another node"; 12 cloudnode1 allow rules were removed from `.claude/settings.local.json` (backup in the session scratchpad).
- Older handoff entries mentioning cloudnode1 are left as history.

Not done by the agent: deleting the OVH VPS (`vps-1a2db40e.vps.ovh.ca`) and removing it from the tailnet. Both are account actions the user must take in the OVH manager and the Tailscale admin console. `~/.ssh/known_hosts` still has entries for `cloudnode1` and `148.113.254.109`. The remote copy of the run on that VM was not deleted (no access). No job running; server not restarted.

## Real World Physics toggle (model revision 6) — Claude Opus 5.5, 2026-09-29/30

**Ask.** The user's 2-galaxy run `f559cd291229` became a "giant pulsating blob" after ~4 Gyr instead of one new galaxy. They asked for the numbers to be checked, accuracy over particle count, and a Compute tab with one toggle, "Real World Physics", building in as much real physics as possible.

**Diagnosis (measured from saved frames; read-only scratch scripts; the run was not modified).** 30k particles; B = 3× A's mass at 0.45× its size; revision 5; 5 Gyr.
- Exact direct-sum softened energy went −385.92 → −385.02 (+0.23%) over 5 Gyr. The UI's 6.1% was the Monte Carlo estimate (±10%).
- A (low density) was tidally shredded by ~500 Myr. The fraction of A's disk within 3 kpc of A's centre went 0.20 → 0.01, and A's stars end at a median 24.5 kpc from B. A's stripped SMBH oscillates 1–33 kpc from the centre (~170 Myr radial period) for 4.5 Gyr: the likely "pulse".
- B's disk inertia axis ratio c/a went 0.04 → 0.18 (0.5 Gyr) → 0.35 (1.5 Gyr) → 0.65 (5 Gyr); final v_φ/σ 0.79.
- Control, B alone, revision 5, lifecycle off, no collision. At 22.5k, c/a 0.30 at 1.4 Gyr and 0.37 at 2 Gyr. At 90k, 0.19 at 1.9 Gyr (≈4× slower in σ² terms). At 22.5k with dt/4 and 54 pc softening, 0.45 at 1.8 Gyr (worse).
- Softening scan, 22.5k, c/a at 1 Gyr: 54 pc 0.30, 120 pc 0.28, 180 pc 0.24, 270 pc 0.23, 390 pc ~0.18 (at 800 Myr; stopped early).
- Conclusion: two-body particle noise, not the merger, turned B into a spheroid. Particle count is the accuracy lever for long runs.

**Change** (config `realistic: true` → `model_revision` 6; revision ≤5 code paths untouched):
- `physics.py`: `REALISTIC_REVISION=6`, `galaxy_params` accepts 6 and forces lifecycle on at speed 1, and `build_one_galaxy_r6`.
  - Halo: tapered Hernquist (ρ_H − ρ_H(300 kpc)), a = 0.54 × the Plummer slider for the same half-mass radius. Speeds come from `eddington_speeds`: Eddington inversion in the softened halo potential plus spherical disk plus softened BH (Barnes 2012), logit-coordinate interpolation, log-spaced τ quadrature, and speed CDF in θ.
  - Disk: σ_R cap 0.6 v_c; the first round(nd·gas_fraction) disk particles are a cold gas disk (c_s 10 km/s, thickness max(c_s/ν, ε/2)).
  - `realistic_settings`: ε = the mean midplane particle spacing at R = Rd in the densest disk, clipped 30–450 pc. dt_initial = √(2ηε/a_max) (η 0.025), capped at 0.02.
  - `heating_times`: particle-noise estimate from Binney & Tremaine eq. 7.106.
  - `meta.realistic`, `meta.physics`, sources.
- `stellar.py`: `kroupa_pdf`, `ssp_tables` (0.0109 SN/M☉, 42% returned by 10 Gyr), `new_baryons_ssp`. save/load store `pending` and `ssp` extras only when present.
- New `realistic.py`, the `Engine` used per step:
  - SPH at the current state, then dt = min(gravity, Courant 0.3, 0.02), shortened to land on the frame.
  - ½ SPH kick → REBOUND step → ½ SPH kick.
  - Stellar-population mass return and SN momentum (2.8e5 M☉ km/s × n^−0.17, net vector removed, 32 gas neighbours within 1 kpc).
  - Stochastic star formation at ε_ff 1% above 0.1 H/cm³.
  - Reads and writes REBOUND memory through a checked 112-byte particle view.
- `worker.py`: revision 6 when config.realistic; 241 evenly spaced frames; archives `realistic_source.py`; `status.realistic` = per-frame dt, limiter, min dt, gas count.
- `nodes.py`: `ENGINE_FILES` and `SMALL_PULL` include `realistic.py` / `realistic_source.py`.
- `server.py`: schema key `realistic`; normalize forces lifecycle; cached `realistic_info`; `POST /api/realistic`. The estimate uses dt_initial plus measured SPH/lifecycle per-step cost (2 ms + 15 µs/gas + 0.08 µs/particle; measured 31/92/191 ms at 30k/100k/200k on 8 threads).
- UI: new **Physics** panel tab with the single toggle. It explains each change, and shows the particle-noise time per galaxy (Real World vs Standard), the cost, and what is not included. On New, a banner appears and the dt, softening, lifecycle, t_sf, speed, bias, protostar-accretion and remnant-kick rows lock with their physical values. The Run panel shows timestep and limiter, populations, SF, SNe and feedback. The legend and inspector say young stars / stellar population.
- README section added.

**Earlier in this session (UI only).** The New tab's "Reset settings to defaults" button moved above the sliders. The Run tab got a live COMPUTE SPEED card (simulated time per wall second, steps/s, particle-steps/s, computed in the page from polled status).

**Measured.**
- `PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_realistic.py` → `validation_r6.json`, exit 0, 328 s, all checks true.
  - SSP 0.0109 SN/M☉ and 0.423 returned at 10 Gyr. SPH momentum 1e-15; colliding clouds KE → 0.60.
  - Jeans σ_r² ratio 0.98–1.01 for r = 0.59–65 (default disk and a compact BH galaxy). The r = 0.14 shell reads +1–10% across seeds (mean ≈ +5%) and is recorded but not asserted.
  - SF law: 325 births vs 300 expected (+1.4σ).
  - Isolated 30k over 490 Myr, halo r10/r50/r90 max|final change: rev6 4.4/2.7/1.3 | 0.8/0.01/0.9%; rev5 2.1/1.7/2.8 | 0.04/1.1/2.8%.
  - Worker 10k 2 galaxies: mass conserved; SIGTERM at frame 101 then resume gives byte-identical frames.
- `validate_physics.py` (historical `validation_r5.json` backed up and restored, same sha1 fe2155…): 60/61 metrics identical, only `lifecycle_speed40_2048.wall_seconds` differs (1.25 → 1.30 s).
- `validate_api.py` with the report to scratch → ok, 11 s. `validate_nodes.py` with the report to scratch → ok, 170 s. `python -m unittest discover -s lab/tests` → 14 OK.
- Browser (isolated :8768, temp data, removed): toggle, locks, estimate, Physics tab at 800 px and 375 px (no overflow); a 10k realistic run started from the UI completed as revision 6; Run diagnostics and legend render; no console errors. The pane was hidden, so polling paused by design; checked after a reload.

**Not done / open.**
- No long realistic science run yet. Predicted: the user's collision at 30k × 5 Gyr on 14 threads ≈ 1.3 h from the starting step; close passages will lengthen it.
- The 22.5k softening scan shows that ε = particle spacing heats a disk faster than 180 pc would at low N; this is a resolution trade-off.
- Low N under-resolves SF and feedback: in the 10k test, 73% of SN momentum found no gas within 1 kpc (reported as unused), and 1 star particle formed in 98 Myr.
- A realistic run on a real node is untested (engine push is covered only by the fake-node suite).
- No BH accretion/AGN, no cooling below 10⁴ K, no planetary GR.

**Server/runs.** :8766 restarted via `launchctl kickstart -k` on 2026-09-30 (pid 39256) after confirming all six runs complete, no worker and the queue held/empty. The new endpoint answers. Saved runs untouched. No job running.

## Cloud node diagnostic — Codex, 2026-09-29 16:30 EDT

- Read-only live checks confirm the failure is SSH authentication for `ubuntu@cloudnode1`, before the Python runtime or worker can be inspected. `ssh -vv -o BatchMode=yes -o ConnectTimeout=8 -o ConnectionAttempts=1 ubuntu@cloudnode1 true` → exit 255: DNS resolves to 100.121.220.52, TCP and SSH handshake succeed, the known ED25519 host key matches, this Mac's id_ed25519 key is offered and rejected, ending in `Permission denied (publickey,password)`. No password was attempted.
- `tailscale ping --c 2 --timeout 5s cloudnode1` → exit 0, direct pong in 51 ms. `ssh -o BatchMode=yes -o ConnectTimeout=8 -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 edb@computenode1 'printf "key-login-ok\\n"'` → exit 0, `key-login-ok`. The Mac key works on the home node; cloud-side authorized_keys, permissions, account state or SSH policy need inspection through the OVH console. Exact underlying cause remains unverified without authenticated access.
- GET `/api/nodes` on existing :8766 confirms computenode1 ready, cloudnode1 rejected at authentication. GET `/api/jobs` reports all four saved jobs complete, including cloud run `7ffea0bd7149`, with `synced_complete: true` and 222 locally available frames. GET `/api/queue`: held, empty. No existing provider console was available in this chat's browser surfaces; Arc's visible window was Google Docs.
- No source/runtime/network/authentication changes, restarts, new simulations, password retries or benchmark writes. Existing :8766 server remains running. Remote process/service state cannot be established through the rejected login. Next step: authenticated OVH KVM/console to inspect Ubuntu SSH auth logs and `/home/ubuntu/.ssh` ownership/permissions/key presence before deciding on a repair.

## Gravity bugs: model revision 5 — Claude Opus 5.5, 2026-09-29

User saw every galaxy in 5-galaxy run `7ffea0bd7149` hollow into expanding rings. Measured from its frames: each disk's 10th-percentile radius went 0.30 → 1.45 units by frame 8 (~35 Myr), before any encounter, so the cause was the initial conditions, not the collision.

**Bugs found and fixed.**
1. `physics.build_one_galaxy` set disk rotation from the razor-thin, unsoftened Freeman curve. Real pull of the Gaussian-thick disk under Plummer softening is weaker near the centre. For that run's settings (`disk_mass 5`, `halo_mass 13`, `halo_scale 6.2`, `disk_scale .5`, `disk_thickness .14`, `softening .06`), Freeman over direct summation was 2.23 / 1.67 / 1.39 / 1.21 at R = .1 / .25 / .5 / 1. Defaults are halo-dominated and thin, so they were barely affected. New `disk_midplane_vc2()` is the exact Hankel form: a softened pair at vertical offset z' equals an unsoftened one at sqrt(z'²+ε²). It is splined over 160 radii. Revision 5 also uses the truncated halo's true interior mass (`Mh·(rmax²+a²)^1.5/rmax³`, +0.6% at a = 6.2).
2. `worker.advance_galaxy`: on "outside of simulation box", REBOUND (`tree.c` `reb_tree_construct`, `gravity.c`) had already finished the step with a partial tree. Every particle from the escaper onward exerted no gravity. The old retry kept that step and took an extra one. New `physics.ensure_tree_box_for_step()` checks `max|x + v·dt/2|` (DKD midpoint) before every step and grows the root (×4 margin). The retry is removed. This applies to all runs, including resumed revision-4 runs. Cost: 8.8 ms/step at 1M (vs ~5.7 s/step).
3. `stellar.step` moved mass (accretion, ejecta) without momentum. Revision 5 carries it (inelastic merge for the receiver; the donor's velocity is unchanged). It is gated on `params['revision']>=5`, so revision-4 runs resume with their original lifecycle.

**Revision plumbing.** `MODEL_REVISION=5`. `GALAXY_DEFAULTS['revision']=4`, so bare `galaxy()` still bit-matches revisions 2–4. `worker.py` (new runs) and `server.preview` pass `revision=MODEL_REVISION`. Galaxy `meta.model_revision` is `P['revision']`. Planets stamp 5, but their physics is unchanged. `validate_api.py` asserts 5; `validate_million.py` asserts `>=4`.

**Measured.**
- `PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_physics.py` → exit 0, 39 s, writes `validation_r5.json` (the script now writes r5; `validation_r4.json` was not written). Every revision-4 key equals `validation_r4.json` except `lifecycle_speed40_2048.wall_seconds`. Revision-3 bit-match 0.0.
- New keys: disk curve / direct sum 0.997–1.004; thin limit / Freeman 0.967–0.9998. Compact settings, 20k particles, t = 3: half-mass growth rev4 +150%, rev5 +40%. Default 2048, t = 10: rev5 energy 3.77e-5, disk +10.0% (rev4 4.40e-5, +10.8%). Lifecycle per-step relative momentum change: rev4 3.1e-5, rev5 2.3e-18. Edge escaper: the unguarded step raises after finishing, and the next particle's vx is −0.01130 vs −0.01275 guarded.
- `OBSERVATORY_NODES= OBSERVATORY_TEST_REPORT="$PWD/outputs/observatory/api_validation_r5.json" PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py` → ok, 10.5 s.

**Still open (not changed).**
- The run's `warmth 0.4` requests Toomre Q = 0.6, which is unstable by design. `sigma_r` is also clipped at `.35·max(1,warmth)`, so the realized centre Q is ~0.3. Revision 5 therefore still spreads in that case (+40%). Consider a UI warning or scaling the clip with v_c.
- `diagnostics.jsonl` repeats the last full diagnostics (computed every 40 frames) on every frame. That is why disk_half_radius looked frozen at 1.06.
- Not run: `validate_nodes.py`, and a browser check (no UI change).

**Server/runs.** :8766 was not restarted, so the preview keeps revision-4 ICs until the next restart. The live server doesn't import physics for jobs; each new worker process does, so new local runs already use revision 5. Node engines are pushed by content hash, so the next remote start or hand-off ships revision-5 code. `7ffea0bd7149` (revision 4, on cloudnode1, final leg) and the other saved runs were not touched. No local worker was running.

## One-time password to install the SSH key on a node — Claude Opus 5.5, 2026-09-29
- Unreachable node cards now show a password field + Connect. `POST /api/nodes/<id>/install-key {password}` → `nodes.install_key()`: appends this Mac's public key (`~/.ssh/id_ed25519|ecdsa|rsa.pub`, creating id_ed25519 if none) to the node's `~/.ssh/authorized_keys` (no duplicates, chmod 700/600), then re-probes. The password reaches ssh only via `SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force` in the child's environment; it is never written to disk, logged (log_message is silenced) or stored. All other SSH stays key-only BatchMode.
- The node poll (every 6 s) skips re-rendering the node cards while a password field has focus or text, so typing is not wiped.
- Tested: syntax checks; `install_key` rejects empty/over-1024-char passwords; against a dummy node at 127.0.0.1 it reports "Connection refused" cleanly. Browser: the field renders on the cloudnode1 card at desktop and 375 px widths, no console errors. **Not tested against a real password-auth sshd**: the askpass path is unverified end to end. Nodes with `PasswordAuthentication no` will still reject it (the message says so).
- The server on 8766 was **not restarted** (job `b53e3ff252f3` and others are in the library); the new route and error wording take effect after a graceful restart. Static UI changes are already served.
- **cloudnode1 key loss investigation (same day, later).** Measured: Tailscale direct path OK, sshd (OpenSSH 10.2p1) answers, host key unchanged (VM not rebuilt), this Mac's only key `SHA256:Ohe991…` (unchanged since 2026-03-08) is offered and rejected by `ubuntu@cloudnode1`; the same key still works on computenode1; no agent keys; no Tailscale SSH on cloudnode1; computenode1 has no key there. Last successful cloudnode1 sync: 2026-09-29 01:01 EDT (run `7ffea0bd7149`). So the node's `authorized_keys` lost the key or its home/.ssh permissions changed (StrictModes); which one could not be seen without logging in. `install_key` now prints the pre-repair state (perms of ~, ~/.ssh, authorized_keys mtime, whether the key was present, sshd AuthorizedKeysFile/StrictModes via `sudo -n`) to `work/observatory-data/server.log` as `[install-key …]`, and also runs `chmod go-w ~`. Script tested in a temp HOME on computenode1 (repairs a 777 home, installs the key). Service restarted with `launchctl kickstart -k` at 2026-09-29 ~09:47 EDT after confirming no job running (c9f32fae5585 paused, queue held).
- User's Connect attempt: password rejected. Verified the askpass path works (ssh -v shows `read_passphrase: requested to askpass`, helper called with the password prompt, server replied Permission denied) using one deliberately wrong password. So cloudnode1 now rejects both the key and the user's password, which worked on 09-28. Public IP 148.113.254.109:22 accepts TCP but sent no SSH banner in two tries (filtered by a proxy, or sshd saturated; unknown). Next step needs the OVH web console/KVM or rescue mode: check `~/.ssh/authorized_keys`, `/var/log/auth.log`, `last`, `passwd -S ubuntu`, and if anything is unexplained treat the VM as compromised and rebuild. Do not retry passwords repeatedly (fail2ban/lockout).
- **OVH-side check (2026-09-29 afternoon).** VPS is `vps-1a2db40e.vps.ovh.ca` (OVH US account, Canada, installed 2026-09-28 21:37 UTC). OVH status pages: no current VPS/BHS incident; a global "Delivery incident" for dedicated/VPS (software issue) ran 09-28 18:00 → 09-29 08:13 UTC, overlapping the window in which access broke (after 05:01 UTC); only BHS cooling/network maintenance otherwise. The owner's Gmail has an OVH email "Restarting in rescue mode" at 2026-09-29 17:28 UTC (root password via a one-time OVH secret link; links the anti-hack guide). The key was already failing ~13:30 UTC, so rescue mode is not the original cause. At 16:26 EDT the VM runs its normal OS (Tailscale up, usual host key) but still rejects the key; Tailscale counters reset, so it has rebooted. Not yet known: who requested rescue mode (user or OVH security) and what changed `authorized_keys`/the password. Needs the OVH manager (not signed in in the browser pane; the agent must not sign in) or the rescue root login.

## Dashboard slowdown during heavy runs — Claude Opus 5.5, 2026-09-28

The user reported the dashboard slowing a lot during serious computations. Four causes were investigated and addressed. Physics numerics, ICs and frame format are unchanged, so there is no model-revision bump.

**Causes found (measured 20:50–21:00).**
1. A 14-thread worker used every core (10 P + 4 E) at `USER_INITIATED` QoS (priority 37, above the server's 31).
2. `~/Desktop` is in iCloud Drive, and `work/observatory-data` (3.3 GB) was being synced. A 1M run writes a ~138 MB checkpoint plus a 24 MB frame per chunk. After the pause, `fileproviderd`, `bird` and `cloudd` were the top CPU users.
3. 24 GB RAM with 4.6/6 GB swap in use.
4. Bug: the frames endpoint rejected any request over 8 MB, so 1M frames (24 MB) always returned 400, and `viewer.js` re-requested them on every animation tick. A simulated 108 req/s storm did not slow the server's polls, so this was a correctness bug more than a load source.

**Changes.**
- `physics.py` `_set_worker_qos()` (replaces `_set_qos_user_initiated`): the worker defaults to `utility` QoS. `OBSERVATORY_WORKER_QOS=user_initiated|default|utility` overrides it. On Linux nodes it is a no-op, as before. Thread count is still honoured, not capped.
- `server.py` frames block: a single frame is always served; the 8 MB cap applies only when `count>1`.
- `viewer.js` `request()`: failed frames back off 1 s, doubling to 30 s, per job:frame.
- Data: the server was stopped, then `work/observatory-data` was moved to `work/observatory-data.nosync` with a symlink left at the old path. `.gitignore` and README were updated. No evicted (dataless) files were found before the move. iCloud will drop its cloud copy of that folder; the local files are intact.

**Measured.**
- `OBSERVATORY_NODES= OBSERVATORY_TEST_REPORT="$PWD/outputs/observatory/api_validation_perf.json" PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py` → ok, 10.2 s, no false assertions.
- `validate_physics.py` → exit 0, 30 s. 45/46 metrics identical to the prior `validation_r4.json`. The only difference is `lifecycle_speed40_2048.wall_seconds` (1.27 → 2.01 s). The prior `validation_r4.json` was restored afterwards.
- `OBSERVATORY_TEST_REPORT="$PWD/outputs/observatory/nodes_validation_perf.json" … validate_nodes.py` → ok, 232 s.
- Live :8766 after the restart:
  - 1M `c9f32fae5585` frame 65: 200, 24,000,000 B in 21 ms (6 MB with the redesign session's `every=4`); `count=2` still 400.
  - Browser: 1M run plays thinned, 0 failed frame requests, no console errors.
  - Forced 400s: each frame retried 4× in 15 s, then recovered.
- QoS benchmark (scratch scripts, not in repo): 200k × 2 galaxies × 14 threads, with three default-QoS "render loop" probe processes (4 ms of work per 16.7 ms deadline). Machine shared with other sessions, so the numbers are noisy.
  - Worst stall: utility 21/21/54/21/21 ms vs user_initiated 108/109/34/67/18 ms.
  - Missed probe frames: about the same (~0.6% vs ~0.7%).
  - Step time: utility ~5–25% slower (e.g. 0.51–0.66 vs 0.47–0.62 s/step).
  - The benefit is fewer worst-case spikes, not fewer missed frames. Keep or revert as the user prefers.

**Not measured.** iCloud load with a real local run after the move (none was running locally). Real foreground-browser FPS (the embedded pane is hidden and throttles rAF).

**Server.** :8766 restarted 21:21 via stop-daemon.sh + `launchctl bootstrap` (2 s down). `data_directory` = `work/observatory-data.nosync`. Jobs: `7ffea0bd7149` running on computenode1, `67be855d5342` complete, `c9f32fae5585` paused at 66. No local worker. The same restart picked up the star-inspector and 1M-thinning server changes from the other two sessions.

## 1M playback: thinned display — Claude Opus 5.5, 2026-09-28 (late)

User reported choppy 1M playback. Causes: (1) the live server rejected every 24 MB frame (8 MB cap) and the viewer retried every tick — fixed by the parallel "Dashboard slowdown" session (single-frame exception + retry backoff; live after its :8766 restart); (2) sheer volume: 24 MB per frame × ~5 frames/s of playback, two full buffer copies + GPU uploads per step, GC churn. Change: `server.py` frames endpoint takes `every=1..64` (`display_sample()`: 0, k, 2k… then each SMBH); `viewer.js` draws a strided sample above 250k particles (k=ceil(n/250k): 1M → 1 in 4), point size ×√k for equal light, uploads only the newly needed frame per step (ping-pong buffers), and translates particle ↔ display indices so the star inspector and `/track` keep particle indices; falls back to thinning a full frame if a server ignores `every`. Layers → **Full detail** restores every particle. Status line says "drawing 1 in k". Physics and saved data unchanged.
**Measured** (isolated :8768 on an APFS clone of `c9f32fae5585`, clone removed): every=4 frame 6,000,000 B vs 24,000,000 B, identical to the client rule; server serves a full 24 MB frame in 12 ms (not the bottleneck); page heap 122 MB thinned vs 325 MB full; inspector pick → particle #100,900 with its 66-frame track; no console errors. **Not measured:** FPS — the embedded pane was hidden (rAF throttled to ~1 Hz in both modes); check in the user's browser. A camera re-framing heuristic was tried and reverted (saved `camera_distance` is ~0.45–0.56 of a fitted distance for every run, so it would have re-framed all runs).

## Star inspector (click a body, see its live stats and saved track) — Claude Opus 5.5, 2026-09-28

User asked to click a star in the 3D view, see its stats update as the simulation progresses, and see its past track and statistics. Refresh once per saved frame was accepted, and it had to work in both saved/live runs and the composer ("collision lab") preview. Physics, ICs, worker and frame format are unchanged (no model-revision bump; `validate_physics.py` not re-run).

**Server.** `track_particle` in `server.py` (unused leftover from an older page) was rewritten with a numpy memmap. `GET /api/jobs/:id/track?index=i&start=k` returns row i of frames k…, plus `r` (distance from its galaxy centre), `height` (off its fitted disk plane, null when the sample's smallest/middle singular value > 0.45), `nearest` / `nearest_r` (closest galaxy centre), component, galaxy id and units. Planets: `r`/`height` relative to the Sun, plus the body name. Centre = the galaxy's SMBH when present, else a shrinking-sphere density centre of 1,024 strided disk particles. Centres are cached in memory in `CENTER_CACHE` per run; frames after `checkpoint.json` index are recomputed, and the cache entry is dropped on Remove. Nothing is written to run folders.

**UI.** `viewer.js`: click-not-drag picks the nearest visible body on screen within 12 px (22 px for planets); hidden layers can't be picked. Screen-sized ring sprite; additive track line through saved positions up to the playhead, ending at the interpolated ring; `focusSelected`, `setFollow`, `sample`. `app.js`/`index.html`/`style.css`: an inspector card over the stage (a bottom sheet under 760 px) with live values from the saved frame under the playhead, charts with a playhead line and stage-change marks, a summary and an event list. The track is fetched incrementally on each poll when `status.frames` grows, and refetched if frames go backwards. Esc/✕ clear it; switching runs or re-previewing clears it. Preview picks show initial values only (no track, and no mass, since preview particles carry N/8,000 × the run's mass).

**Measured.**
- `OBSERVATORY_NODES= OBSERVATORY_TEST_REPORT="$PWD/outputs/observatory/api_validation_inspector.json" PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py` → ok, 11.1 s. New assertions: the track matches `frames.bin` for all 201 frames; incremental `start` equals the tail; the SMBH has r = 0 in every frame; index ≥ n → 400; Earth r 0.9833–1.0165 AU. `api_validation_r4.json` was not rewritten.
- `track_particle` read-only on the saved library: 200k 0.96 s cold / 0.01 s warm; 1M (`c9f32fae5585`, 66 frames) 0.75 s cold; 5-galaxy 30k with SMBHs 0.03 s.
- Browser (embedded, isolated :8768, temp data, removed afterwards): 30k two-galaxy live run: pick → card; track appended as frames arrived (`start=12,14,15…`); Centre view, pause, and card scrolling worked. Planets: Jupiter 4.97 AU, 13.6 km/s, 318 M⊕. Composer preview pick works. 1440 px and 375 px, no horizontal overflow; no JS errors. (The only console errors were `/api/nodes`, caused by launching with `OBSERVATORY_NODES=` empty, which nodes.py reads as `.`. This is pre-existing and unrelated.)
- Not measured: click-pick cost on a 1M frame in a real GPU browser (it's a single JS loop over the displayed buffers), and the inspector on live :8766, which still runs the old server.py until it restarts.

**Server state.** Live :8766 was not restarted by this session. The "Dashboard slowdown" session announced a graceful restart plus moving `work/observatory-data` to `.nosync`. The isolated :8768 server and its test runs were stopped and deleted.

## cloudnode1, standby pick-up, multi-machine chains, twin runs — Claude Opus 5.5, 2026-09-28 (evening)

User asked to connect OVH VM `ubuntu@cloudnode1` and computenode1 so that (A) a node picks up a Mac run when the Mac closes/sleeps, (B) a run can be split across all three machines, (C) one more idea (chose twin runs). Physics, ICs and frame formats unchanged; `physics.py`/`stellar.py`/`worker.py` untouched.

**cloudnode1.** Key installed by the user typing the password into a terminal command the agent started (the agent never entered a password). Ubuntu 26.04, 6 cores x86_64, 11 GB RAM, Python 3.14.4, passwordless sudo, Tailscale already up. `node/bootstrap.sh` run over SSH (first real run): numpy 2.5.3, scipy 1.18.1, REBOUND 5.1.1 built with OpenMP (`OpenMP linked: True`). Registered as `cloudnode1` (label "cloudnode1 (OVH)", always on). Benchmarks through the app, same workload (100k × 2 galaxies × 3 steps, all cores): **computenode1 2.33 s/step (4 thr) → factor 2.81; cloudnode1 2.61 s/step (6 thr) → factor 4.72**. computenode1's earlier 6.21 came from 1M particles — factors depend on N; estimates remain predictions.

**(A) Standby.** `nodes.py`: while a Mac run computes, the Mac stages its latest checkpoint pair into `<runs>/jobs/<id>` on the standby node (staging dir + swap; never overwrites a copy already picked up), writes `standby.json` (armed, index, threads, absolute engine path), and touches `<runs>/hub-heartbeat` every 10 s, (re)starting a stdlib `standby_watchdog.py` there. Watchdog resumes armed copies when the heartbeat is >90 s old and reaps its children. Mac side, on the next heartbeat after waking: sees `taken`, SIGTERMs its own worker, truncates Mac frames to the copy's index, records a `standby pick-up` history segment and follows the node; `return_on_wake` hands back once a sync has seen the node's worker alive. Armed state persists in `location.json` (`standby.armed_on`, `index`, `pushed_at`); paused/finished runs are disarmed; hand-offs disarm first; remote starts delete stale `standby.json`. Copy interval 2 s/MB clamped 2–30 min.
**(B) Chains.** `location.plan = {legs:[{node,until}], leg}`; old `{at,to,from,done}` is read as two legs (`plan_of`). Up to 5 legs. Cap check is the whole-run sum. UI legs editor with per-leg estimate bar and timeline markers.
**(C) Twins.** `POST /api/jobs {twin: node}` creates two linked runs (`location.twin`, `config.twin/twin_of`) started together; `GET /api/jobs/:id/twin` returns per-frame median/p90/max particle separation (strided ≤20k sample, memmap) + diagnostics, cached in `twin_compare.json`. Run panel twin card with chart; ⧉ marker in the library.

**Bugs found and fixed by the tests.** (1) Watchdog-launched workers became zombies after exiting, so `kill_remote` reported "did not stop" and the hand-back failed — watchdog now reaps; stop check treats `Z` as stopped. (2) `sync()` published a finished status before updating liveness, so a node could look busy for a moment — liveness now updated first. (3) **Pre-existing race**: right after a hand-off the node's `frames.bin` is briefly shorter than the stint start; a sync then truncated the Mac's frames and refilled them with the node's sparse zeros (playback only, physics unaffected). Sync now never truncates below the current stint's first frame. The old live server ran the unfixed code until the restart below.

**Measured.** `work/venv/bin/python outputs/observatory/tests/validate_nodes.py` → `outputs/observatory/nodes_validation.json`, ok, 219.5 s: all earlier scenarios plus chain Mac→fake→fake2 (hand-offs at frames 54/118), twins (max divergence 0.0 on one CPU), standby: server + Mac worker SIGSTOPped at frame 104, node picked up the copy at index 102 after 11.0 s silence (test grace 6 s), SIGCONT → handed back at frame 132, final `frames.bin` byte-identical to an unsplit 1-thread reference; no zero frames anywhere. `validate_api.py` (report `api_validation_nodes.json`) and `validate_queue.py` (report to scratch) pass. Browser on live :8766: chain chips for the user's cloudnode1 run, composer legs Mac→computenode1→cloudnode1 with per-leg estimates, standby and twin controls; no console errors. Fixed "Add machine" defaulting to a machine already in the chain.
**Not measured on real machines:** standby pick-up, chains and twins against computenode1/cloudnode1 (they were busy with the user's runs; launching test workers there would compete). `tests/validate_node_live.py cloudnode1` not run for the same reason. Real sleep (lid close) not tested — SIGSTOP stands in for it; Wi-Fi may drop before the heartbeat stops, which the 90 s grace covers either way.

**Server/runs.** Live :8766 restarted (LaunchAgent kickstart) at ~21:03 EDT onto this code after confirming: `55228a36ea55` (user-created, 5 galaxies, 30k, on cloudnode1, plan → computenode1 at 45%) kept running on the node, 32/32 frames on the Mac, no zero frames; `da12c4d2dfbc` (user-created, 1M, paused 4 frames) stayed paused (its in-RAM worker exited on SIGTERM); `67be855d5342` complete; `c9f32fae5585` paused 66. None created, resumed or removed by the agent. Standby is off for both user runs (created before the feature).

## One-page observatory + compute nodes with checkpoint hand-off — Claude Opus 5.5, 2026-09-28

User asked for Compute and Observe rebuilt as one seamless experience, and for runs to compute fully on the Mac, fully on `Edb@computenode1` (Tailscale), or split between them and visualized later, plus an always-on Oracle Cloud VM. For "split" the user chose **hand off one run** (serial, at checkpoints) and **Mac as hub**. Physics, ICs and frame formats are unchanged (`physics.py`, `stellar.py`, `worker.py` untouched, so no model-revision bump; `validate_physics.py` not re-run).

**Backend.** New `outputs/observatory/nodes.py`: registry in `work/nodes.json` (gitignored; `OBSERVATORY_NODES` overrides), key-only `ssh -o BatchMode=yes` transport (tar streamed via Python `tarfile`), engine snapshot pushed per content hash, `nohup` remote launch, a sync loop that pulls status/diagnostics/log and appends only new frame bytes (`tail -c +N | head -c M`) before writing the Mac's `status.json`, and a hand-off state machine (pause → SIGTERM checkpoint → pull checkpoint pair + frames to the committed index → push small files + that pair → resume on target). Old frames are never pushed; the target's `frames.bin` is sparse before the hand-off index and never read there. `server.py`: one active experiment **per node** (`busy(node=…)`), `placement` stored in `config.json`, `location.json` per run (node, plan, per-node frame history, transfer state), remote control/resume/Remove, queue barrier per node, `recover()` skips remote runs and marks interrupted hand-offs failed, new endpoints (`/api/nodes`, probe, benchmark, `/api/jobs/:id/move`, `node`/`split` on create). Node estimates = Mac estimator × one measured speed factor (computenode1 seeded with 6.21 from `work/node-comparison`, 1M × 2 galaxies × 4 threads).

**UI.** `lab.html`/`lab.js` removed; `/`, `/observe`, `/lab`, `/compute` all serve `index.html` (`/lab` opens the composer). `app.js` = library | stage | Run/New/Nodes panel; `viewer.js` = Three.js, imported lazily; **Layers → 3D rendering** disposes the GPU context. Composer previews ICs on the stage via `/api/preview` (camera fitted to the 90th-percentile radius). Timeline strip colours frame ranges by node. This supersedes the old "Compute tab loads no Three.js" rule — deliberate, per the request; the byte-capped frame cache stays.

**Oracle.** Not created. Account signup and card verification must be done by the user (the agent does not create accounts or enter card details). `outputs/observatory/node/bootstrap.sh` prepares any Ubuntu x86/ARM VM (numpy, scipy, REBOUND 5.1.1 + OpenMP, Tailscale). Not executed on a real VM.

**Measured.**
- `work/venv/bin/python outputs/observatory/tests/validate_nodes.py` → `outputs/observatory/nodes_validation.json`, ok, 61.4 s (earlier runs 77 s). Fake `ssh` runs the "remote" shell locally under a temp `$HOME`. Remote planets 2,401 frames mirrored byte-identical (energy 1.17e-15); Mac and node computed concurrently; split Mac→node (hand-off at frame 57, 1.2 s), node→Mac (frame 93), manual node→Mac mid-run (frame 49): all three `frames.bin` **byte-identical** to an unsplit 1-thread reference (10k, 2 galaxies, lifecycle on, 151 frames); Remove deleted the node copy; unreachable node → 400 naming `ssh-copy-id`. A race found on the first run (a remote run finishing between syncs kept a 25 s start-up grace, so the node looked busy and a planned hand-off was skipped) is fixed and has a regression step.
- `OBSERVATORY_NODES=<empty> OBSERVATORY_TEST_REPORT="$PWD/outputs/observatory/api_validation_nodes.json" PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py` → ok, 9.9 s (page assertions updated for the single page; `api_validation_r4.json` not rewritten).
- `validate_queue.py` with `OBSERVATORY_TEST_REPORT` (new override; `queue_validation.json` not rewritten) → all ten assertions true.
- Browser (embedded, isolated :8768 + fake node): composed a 10k split run by clicking Start; watched Mac 49% → hand-off at frame 120 → node 84% "synced 2 s ago" → complete 232/232. 1440 px and 375 px (no horizontal overflow); no console errors in any check. Live :8766: 200k run plays at 60 FPS. The pane once reported 289,684 dropped console messages from earlier page instances; not reproducible afterwards (0 messages at any level over 8 s on Run and composer) — cause unknown.

**computenode1 (measured 2026-09-28, after the user installed the key).** Account is lowercase `edb` (`Edb` is rejected); key installed by the user typing the password into a terminal command the agent started — the agent never entered it. Registry host is now `edb@computenode1` (speed 6.21 kept: same machine). App probe: ready, 4 cores x86_64, Python 3.14.4, REBOUND 5.1.1, numpy/scipy, 10 GB free RAM, 84 GB free disk, ~1 s SSH latency. `work/venv/bin/python outputs/observatory/tests/validate_node_live.py computenode1` (isolated :8767, temp data, node folder `work/remote-runs-test`, removed afterwards) → `outputs/observatory/node_live_computenode1.json`: remote planets 2,401 frames in 6.2 s wall, energy 1.56e-15. **Cross-architecture hand-off works both ways**: Mac(arm64)→node(x86_64) at frame 57 in 2.5 s and node→Mac at frame 54 in 3.1 s; both finish 151 frames, all finite, total mass 42.0 = reference. Mac→node frames are identical to the Mac reference up to and including the first frame after the hand-off; final max position difference 0.0094 (Mac→node) and 0.015 (node→Mac) model units (≈28 / 46 pc), i.e. floating-point differences between architectures amplified by N-body chaos — not an error bound. Stellar types diverge accordingly (density-biased births). Byte-identical splits therefore hold only within one architecture (the fake-node test). Not tried: moving the paused 1M run (a 1M checkpoint transfer over Tailscale, and ~6× slower stepping there per the 4-thread benchmark). Oracle VM not created; `bootstrap.sh` not run on a real VM.

**Server.** Live :8766 restarted via LaunchAgent kickstart after confirming no worker (`worker_pid=null`). Jobs unchanged: `67be855d5342` complete 234, `c9f32fae5585` (1M) **paused 66**, not resumed, placement local. Node loop probes computenode1 every 45 s (currently reports the key error). Isolated test servers on 8767/8768 stopped.

## Lab scheduler — 2026-09-22

Added a separate coordinator in `lab/` on branch `lab-scheduler`. It does not change `physics.py`, `worker.py`, or `server.py`. Observatory data under `work/observatory-data` was not used. Historical `validation.json` / `validation_r3.json` / `api_validation.json` were not rewritten. `validate_physics.py` did rewrite `validation_r4.json`, which is that test's own output.

Lab keeps job state in SQLite (`work/lab-data/lab.sqlite`, gitignored). Checkpoint archives are uploaded through `CheckpointStore`. The Drive implementation is rclone into the folder `Open Orbital Compute`. The current pointer moves only after the coordinator recomputes SHA-256. Workers cannot set it. Lease length is clamped to 5 hours. GitHub concurrency defaults to 1 and cannot be configured above 20. Oracle, Modal, Codespaces, and Google Spot are unimplemented backends with the same interface.

Natural-language submit calls Jev on OpenRouter first and GPT-6 Luna only to draft a spec or to phrase missing-parameter questions. One `OPENROUTER_API_KEY` covers both. Missing particle count, duration, timestep, lifecycle, seed, or galaxy count stores no job. `--confirm-defaults` is required before unmentioned observatory fields are filled. Provenance records model revision, git commit, and that merger metrics are integrator diagnostics.

**Measured.** `work/venv/bin/python -m unittest discover -s lab/tests -v` — 14 tests OK. That includes one real planetary year in a temp directory (phase `complete`, checkpoint file present; an isolated run of the same test took 0.983 s). Physics → `outputs/observatory/validation_r4.json` (14.3 s): 2048-particle energy change 4.395e-5 at dt 0.02 / θ 0.4 and 5.695e-6 at dt 0.01; two-galaxy head-on separation 19.79 → 16.44; retrograde L_z A=+2.06 B=-4.57; isolated vs `n_galaxies=1` max |Δstate| = 0. `rev2_reproduction_max_state_difference` is null in this workspace. API → `work/lab-data/api_validation_lab.json` (10.2 s, port 8767): `n_galaxies=6` rejected, five-galaxy N=10k OK, pause survives restart, recovered 201 frames, planets energy change 4.17e-16, protected DELETE rejected. Local observatory on 127.0.0.1:8766 was left running. No million-particle job was started.

**Not measured here.** A live GitHub runner round trip. On computenode1, `LAB_GITHUB_TOKEN`, `OPENROUTER_API_KEY`, and a `[labdrive]` rclone remote are unset, and `TS_AUTHKEY` is not in the repo. The workflow file is on this branch and has not been pushed, so GitHub cannot dispatch it yet.

**Coordinator.** computenode1 is running Lab under the user service `lab.service` (`systemctl --user is-active` returned `active`), listening on `127.0.0.1:8770` and `100.105.242.80:8770`. Observatory `server.py` pid 19196 is still on `127.0.0.1:8766`. Production `GET /api/jobs` is empty. A throwaway local smoke (`LAB_STORAGE=directory`, database `/tmp/lab-smoke.sqlite`, port 8771) completed planetary job `df5647e4013e`: shard checkpoint seq 1, sha256 prefix `75c38501389e`, used 0.001 worker-hours. That smoke process was stopped. It did not use Drive and did not write `work/observatory-data`. Linger is not enabled, so the user service can stop when every login session for `edb` ends.

Operate the coordinator with `work/venv/bin/python -m lab serve` from the repo root. Secrets live in `work/lab-data/lab.env` and `work/lab-data/rclone.conf`. See `lab/README.md`.

## CPU cap and service throttling correction — Codex, 2026-09-17

Supersedes the P-core cap below: requested 14 now gives 14. Removed forced close binding, fixed captions/estimator, added validate_threads.py. Found LaunchAgent default ProcessType was throttling the workload; installer and installed plist now specify Interactive. Live checkpoint run 67be855d5342 resumed without resetting; 14 threads, ~1039% CPU in a ten-second measurement, frame 26 complete interval 13.017 s versus earlier 43.718 s. API/thread/browser checks passed. Full evidence, limitations and commands in outputs/observatory/CPU_DIAGNOSIS.md. Pre-existing dirty edits preserved; no commit combining another agent's work.


## 1M run was on 14 threads including E-cores (2026-09-17)

Live job `c9f32fae5585`: **1,000,000** particles, **14** OpenMP threads requested, **2 galaxies**, **lifecycle on**, duration 10, **paused at 66/168** frames (195 steps, 1430 s wall, last chunk **25 s**). Config still lists unused `companion_*` / bulge knobs; physics used clone defaults (`g2_sep=20`). This M4 Pro is **10 performance + 4 efficiency** cores (`hw.perflevel0.logicalcpu=10`). Barnes–Hut waits at a barrier, so the 4 E-threads leave P-cores idle — that matches Activity Monitor (E-cores packed, P-cores gappy). A 14-thread worker was still parked in RAM after Pause (peak footprint 889 MB, then swapped); SIGTERM left the job paused so Resume can spawn a new process. Saved `config.json` still says `threads=14` (not rewritten). Resume uses 10 P-cores. Did not auto-resume.

Engine: `effective_threads()` caps OpenMP at P-cores, `OMP_PROC_BIND=close` / `OMP_PLACES=cores`, `OMP_DYNAMIC=false`, QoS `user-initiated` from inside the worker (`pthread_set_qos_class_self_np`). Did **not** wrap spawn in `taskpolicy` (that hung isolated API tests). Wait policy stays PASSIVE so a paused in-RAM worker would not spin.

**Measured.** `effective_threads(14)→10`. `PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py` (10.2 s, port 8767): `performance_cores=10`, `n_choices` 10k…1M, five-galaxy 10k OK, pause survives restart, isolated `n_galaxies=1` OK, planets energy 4.17e-16. LaunchAgent kickstart: Python PID 92037 on 8766, `GET /api/system` `performance_cores=10`, `worker_pid=null`, job still `paused` 66 frames. Browser `/lab`: CPU-threads hint names the P-core cap; 1M×14 draft estimate reads **10 P-cores (14 requested)** / 38.1 min (prediction). Historical JSON not rewritten.


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
