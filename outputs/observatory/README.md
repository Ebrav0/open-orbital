# Orbital — local CPU observatory

Open **http://127.0.0.1:8766** (Observe) or **http://127.0.0.1:8766/lab** (Compute) while the server is running.

## What is built

- **Two pages.** *Observe* (`/`) is the Three.js 3D viewer for saved and running frames. *Compute* (`/lab`) shows every initial-condition slider at once, a **Start computation** button, live status (phase, progress, wall time, ETA, diagnostics, events, worker log) and a saved-experiment list with confirmed **Remove**. Compute loads no Three.js and never downloads frames, so that tab stays far below 300 MB (measured JS heap 5 MB after a 30 s slider/polling soak).
- **Galaxy (model revision 3):** a live exponential stellar disk and Plummer dark-matter halo, optional central black hole, and an optional collisionless stellar lifecycle (gas → protostar → main sequence → giant → white dwarf / neutron star / black hole) whose changing masses feed the next gravity step. All particles contribute gravity. 10,000–200,000 particles; 1–14 CPU threads; span limited by a 120-hour compute cap. Sliders cover disk/halo masses and scales, disk warmth, gas fraction, star-formation timescale, lifecycle clock speed, IMF bounds, accretion rate, supernova kicks, tree opening angle, softening and time step. Defaults reproduce revision 2 exactly when the lifecycle is off.
- **Planetary system:** the Sun and eight planetary bodies, using JPL approximate J2000 orbital elements, rounded mass ratios and a direct Newtonian integrator. Jupiter at 1×, 3× or 10×, per-planet mass scales 0.25–10×, and an optional perturber body.
- Rotate, zoom, top/side views, inner-planet view, color/stage/layer controls, timeline scrubbing, playback speed, and independent computation pause/resume.
- Locally saved frames and recoverable checkpoints (including lifecycle arrays). Nothing is sent to a cloud service. The HTTP listener binds only to 127.0.0.1.

![Galaxy workspace](galaxy-preview.png)
![Planetary workspace](planet-preview.png)

## Start again

From any Terminal window (after opening a new tab so `~/.zshrc` is loaded):

```sh
Start OpenOrbital
```

That reuses a running server on port 8766, or starts one, then opens the Compute dashboard at http://127.0.0.1:8766/lab. Observe remains at http://127.0.0.1:8766 . Ctrl+C in that terminal is a graceful shutdown. To start the Python listener only:

```sh
sh outputs/observatory/run.sh
```

This uses the isolated Python runtime at `work/venv` and the previously built multicore REBOUND library at `work/openmp`. The app has no npm server or external CDN dependency; Three.js is bundled locally with its license. Stop the server with Ctrl+C. Active workers save checkpoints on a normal shutdown; use **Resume computation** after restarting.

Saved experiments live under `work/observatory-data`, separate from the source. Set `OBSERVATORY_DATA` to an absolute directory before launching to choose another location. Each run contains its configuration (including free-text notes), metadata, binary frames, checkpoint pairs, status, and log. New runs also archive `physics.py` and `stellar.py`. The application retains up to twelve runs and checks for free disk space. Runs are removed only through the Compute page's confirmed **Remove** (or `DELETE /api/jobs/:id`); the four original experiments (`0e45a855ba11`, `44c528079f88`, `ff56d195ce89`, `58ab7c268cdd`) are protected and cannot be removed.

## Stellar lifecycle — what it is and is not

Types stored per particle: gas, protostar, main sequence, giant, white dwarf, neutron star, black hole, halo, central black hole. Birth converts the densest gas parcels at rate gas mass / `t_sf`; each new star draws a Kroupa mass that sets its clock, while the parcel's gravitational mass is unchanged. Lifetime is `10 Gyr × (m/M☉)^-2.5` clipped to 3–20,000 Myr. At death the parcel keeps only the remnant fraction of its mass; the rest returns to neighbouring gas, so total mass is conserved (measured drift 0.0 at speed 40). `lifecycle_speed` multiplies the clock: 1 = physical lifetimes (only massive stars die within 245 Myr); ~40 fits a solar lifetime into a 250 Myr run. Any speed other than 1 is a laboratory setting, not a calibration. There is no hydrodynamics, cooling, feedback energy, binaries or chemistry, and energy change is not a numerical-error bound when the lifecycle is on.

## Completed test instance

| Run | Result |
|---|---|
| Galaxy, revision 2 | 100,000 particles: 30,000 stellar + 70,000 halo |
| Duration | 245 Myr; 500 integration steps; 168 saved frames |
| Active computation time | 157.84 seconds on 10 threads, including snapshot and diagnostic work |
| Disk half-radius change | +1.93% |
| Total angular-momentum change | 0.0536% |
| Solar System | 12 years; 2,401 frames; relative energy change 1.17e-15 |
| Modified Solar System | Jupiter at 3× mass; 12 years; completed through the browser UI |

The original revision-1 galaxy run remains available for comparison. It used a colder, less balanced disk and contracted by about 12%; the revision-2 model uses disk circular forces and approximate Jeans velocity support. Neither is a calibrated model of the Milky Way.

## Validation and limits

- `validation.json`: analytical two-body period check, 50-year planetary energy check, small-galaxy timestep/tree comparisons, and checkpoint continuation agreement.
- The 2,048-particle galaxy test had relative energy change 4.40e-5 over ten model time units; halving the timestep reduced it to 5.69e-6. These small-model results do not establish the same error at 100,000 particles.
- `api_validation.json`: real server restart and resumed integration; the first saved frame stayed identical, paused frames stopped growing, concurrent active jobs were rejected, and invalid frame requests were rejected.
- Browser checks covered both modes, a new modified planet run, pause/resume, timeline seeking, layers, camera controls and responsive layouts. No browser console errors were observed during these checks.
- Large-galaxy energy is a **Monte Carlo estimate**, with approximate sampling uncertainty displayed. It is not an integration-error bound. The measured 1.62% difference has approximately 6.76% sampling uncertainty.
- Galaxy units are G=1, mass=10^10 solar masses, length=3 kpc and time=24.50 Myr. The tree opening angle is 0.4, softening is 0.06 model lengths and timestep is 0.02 model time units. This is an exploratory collisionless model, with no gas, star formation, relativity or resolved binary-star encounters. Long-term equilibrium is not established by the short test.
- Planet sizes are enlarged for visibility; orbital distances are linear. Orbital guides show the initial Keplerian elements. Playback interpolates saved positions; it does not replace the CPU physics.
- Benchmark timings for a uniform sphere do not directly predict this centrally concentrated disk/halo workload.
- **Revision 3 evidence** (`validation_r3.json`, `api_validation_r3.json`): revision-2 initial conditions reproduced exactly by the new defaults; lifecycle-off 2,048-particle bounds unchanged; lifecycle-on mass conservation to float precision with deterministic resume; a full-knob API run with 24-byte frames, server restart and checkpoint recovery, summary payload of ~3 KB per job, and the Remove rules (running → 400, protected → 400, finished → deleted). The 120-hour estimate scales from the single measured revision-2 point; 200,000-particle and lifecycle timings are predictions until measured.

## Source map

- `physics.py`: parameterized initial conditions, unit conventions, diagnostics.
- `stellar.py`: stellar lifecycle on live REBOUND masses; baryon checkpoints.
- `worker.py`: integration, lifecycle substeps, versioned frames, controls, transactional checkpoints, 120 h cap.
- `server.py`: job management, validation schema, estimator, Remove rules and loopback HTTP API.
- `static/app.js`, `static/index.html`: Observe WebGL viewer and controls.
- `static/lab.html`, `static/lab.js`, `static/shared.js`: Compute page (no Three.js).
- `static/style.css`: both pages.
- `tests/validate_physics.py`, `tests/validate_api.py`: numerical and recovery checks (write `*_r3.json`).

Run validation from the task root:

```sh
PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_physics.py
PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_api.py
```

The API test creates an isolated temporary run and uses port 8767.

## Model references

- [JPL approximate planetary elements](https://ssd.jpl.nasa.gov/planets/approx_pos.html)
- [JPL planetary physical parameters](https://ssd.jpl.nasa.gov/planets/phys_par.html)
- [REBOUND Plummer model example](https://rebound.hanno-rein.de/c_examples/selfgravity_plummer/)
- [Exponential disk gravity](https://galaxiesbook.org/chapters/II-01.-Gravitation-in-Galactic-Disks_3-Gravitational-potentials-from-disk-density-distributions.html)
