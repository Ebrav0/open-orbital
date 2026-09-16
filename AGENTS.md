# Instructions for agents working on Open Orbital

## Read first
- Read HANDOFF.md, then outputs/observatory/README.md.
- Preserve saved experiments in work/observatory-data and all benchmark JSON evidence. Never reset or silently overwrite scientific runs.
- The user wants a working local CPU gravitational observatory with both galaxy and planetary modes. Do not replace numerical physics with animations or prescribed galaxy paths.
- Keep computed simulation time distinct from playback speed and rendering frame rate.
- Do not claim that the exploratory galaxy is a calibrated equilibrium model or that a short run proves long-term stability.

## Working conventions
- Use work/venv/bin/python. The launcher adds work/openmp to PYTHONPATH to use the tested native multicore REBOUND build.
- Reuse the existing server at port 8766 when possible. Check /api/jobs before restarting; pause/checkpoint an active job first. Ctrl+C is a graceful shutdown.
- UI assets are local; no CDN is needed. Preserve the Three.js license.
- Do not launch competing heavy simulations during a benchmark. Ordinary UI validation can use a small particle count.
- For physics changes, run tests/validate_physics.py and inspect the metrics, not merely its exit code. For worker or server changes, run tests/validate_api.py (isolated port 8767).
- Test affected controls in a real browser and check the console. Check desktop and narrow layouts for layout changes.
- Add model revision metadata when changing initial conditions. Archive the model source with each new run, as worker.py already does.
- Keep resource limits explicit; do not remove the saved-run or disk-space safeguards without a considered replacement.

## Handoff discipline
Update HANDOFF.md with the concrete change, exact test command/result, outstanding issues, and whether a server/job remains running. Distinguish measured results from predictions. Do not modify historical benchmark results to match new code.
