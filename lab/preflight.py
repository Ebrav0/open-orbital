"""Deterministic resource preflight and an isolated real Open Orbital smoke run."""
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from lab.observatory import physics, server
from lab.paths import ROOT


def estimate_resources(runs, cfg, backend='local', benchmark_dir=None):
    if not runs:
        raise ValueError('There are no simulation runs to estimate')
    records = _benchmark_records(benchmark_dir or ROOT / 'work' / 'linux-benchmarks')
    row_estimates = []
    sources = set()
    storage_bytes = 0
    for run in runs:
        config = run['config']
        seconds, source = _seconds(config, records, platform.node())
        sources.add(source)
        if config['mode'] == 'galaxy' and config.get('lifecycle_enabled'):
            seconds *= 1.15  # explicit projection; no lifecycle benchmark is in the history set
        if config['mode'] == 'galaxy' and int(config.get('n_galaxies') or 1) != 2:
            seconds *= 1.05 if int(config.get('n_galaxies') or 1) > 1 else 1.0
        if backend == 'github':
            source = 'cross-host prediction from computenode1 measurements'
            sources.add(source)
        row_estimates.append(seconds)
        per_run_bytes = int(server().disk_bytes(config))
        # Retain the newest configured checkpoints and preserve the final result bundle independently.
        storage_bytes += per_run_bytes * (int(getattr(cfg, 'checkpoint_retention', 3)) + 1)
    runner_startup_seconds = 300.0 if backend == 'github' else 30.0
    total_seconds = sum(row_estimates) + len(row_estimates) * runner_startup_seconds
    concurrency = int(cfg.github_concurrency if backend == 'github' else cfg.local_concurrency)
    max_runtime_hours = max(row_estimates) / 3600
    total_worker_hours = total_seconds / 3600
    storage_gib = storage_bytes / (1024 ** 3)
    warnings = []
    if any(s != 'measured exact match on computenode1, scaled by requested steps' for s in sources):
        warnings.append('At least one runtime value is an extrapolation, not a measured full-run time.')
    if backend == 'github':
        warnings.append('GitHub runner CPU performance has not been measured; computenode1 timings are a cross-host baseline.')
    if storage_gib > float(getattr(cfg, 'max_storage_gib', 100)):
        raise ValueError(f'Predicted output/checkpoint storage {storage_gib:.1f} GiB exceeds the configured {cfg.max_storage_gib} GiB limit')
    if max_runtime_hours > float(cfg.max_runtime_hours):
        raise ValueError(f'One run is projected at {max_runtime_hours:.1f} worker-hours, above the {cfg.max_runtime_hours} h per-run cap')
    if total_worker_hours > float(cfg.budget_worker_hours):
        raise ValueError(
            f'The {len(runs)}-run plan is projected at {total_worker_hours:.1f} worker-hours, above the '
            f'{cfg.budget_worker_hours:.1f} h configured budget. Shorten the span, reduce the run count, or '
            'change the authorized budget before scheduling.'
        )
    return {
        'run_count': len(runs),
        'total_worker_hours': total_worker_hours,
        'runner_startup_overhead_seconds_per_run': runner_startup_seconds,
        'expected_wall_hours_at_configured_concurrency': total_worker_hours / max(1, concurrency),
        'configured_concurrency': concurrency,
        'per_run_seconds_min': min(row_estimates),
        'per_run_seconds_max': max(row_estimates),
        'per_run_estimates_seconds': row_estimates,
        'storage_estimate_bytes': storage_bytes,
        'storage_estimate_gib': storage_gib,
        'checkpoint_retention': int(getattr(cfg, 'checkpoint_retention', 3)),
        'storage_model': 'per-run observatory disk estimate multiplied by retained checkpoints plus one separate final result archive',
        'estimate_sources': sorted(sources),
        'estimate_type': 'prediction; measured step timings are scaled to requested step count',
        'warnings': warnings,
        'measured_run_time': False,
    }


def _benchmark_records(directory):
    root = Path(directory)
    records = []
    if not root.is_dir():
        return records
    for path in sorted(root.glob('galaxy_n*_t*_*.json')):
        try:
            row = json.loads(path.read_text())
            if (row.get('finite') is True and int(row.get('model_revision') or -1) == int(physics().MODEL_REVISION)
                    and int(row.get('timed_steps') or 0) > 0 and float(row.get('seconds_per_step') or 0) > 0):
                row['_path'] = str(path)
                records.append(row)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return records


def _seconds(config, records, host):
    if config['mode'] == 'planets':
        return float(config['estimated_seconds']), 'observatory formula projection for the small planetary model'
    n = int(config['n'])
    threads = int(config.get('threads') or 1)
    same_host = [r for r in records if r.get('host') == host and int(r.get('threads_used') or 0) == threads]
    if same_host:
        nearest = min(same_host, key=lambda r: abs(math.log(max(1, int(r['n'])) / max(1, n))))
        measured_step = float(nearest['seconds_per_step'])
        if int(nearest['n']) != n:
            measured_step *= (n * math.log(n)) / (int(nearest['n']) * math.log(int(nearest['n'])))
            source = f'extrapolated by N log N from {nearest["n"]} particles on computenode1'
        elif int(nearest.get('n_galaxies') or 2) == int(config.get('n_galaxies') or 1):
            source = 'measured exact match on computenode1, scaled by requested steps'
        else:
            source = f'measured {nearest["n"]}-particle, {nearest.get("n_galaxies")} galaxy baseline on computenode1'
        steps = float(config['duration']) / float(config['dt'])
        return measured_step * steps, source
    # Fall back to the checked-in observatory estimator and clearly label it as extrapolated.
    return float(config['estimated_seconds']), 'observatory reference-point scaling; no matching node benchmark'


def run_validation_case(sample_config, cfg=None, root=None, timeout=180):
    """Boot a real temporary worker, require a finite completed run and checkpoint, clean up."""
    root = Path(root or ROOT)
    mode = sample_config['mode']
    smoke = dict(sample_config)
    if mode == 'galaxy':
        galaxies = int(smoke.get('n_galaxies') or 1)
        allowed = server().SCHEMA['n'][1]
        smoke['n'] = next(n for n in allowed if int(n) >= 256 * galaxies)
        smoke['duration'] = 0.04
        smoke['dt'] = 0.02
        smoke['threads'] = 1
    else:
        smoke['duration'] = 1.0
        smoke['threads'] = 1
    smoke['estimated_seconds'] = 120.0
    smoke['notes'] = 'Disposable preflight smoke; not a research result.'
    with tempfile.TemporaryDirectory(prefix='open-orbital-preflight-') as tmp:
        run_dir = Path(tmp) / 'run'
        run_dir.mkdir()
        (run_dir / 'config.json').write_text(json.dumps(smoke))
        (run_dir / 'control.json').write_text(json.dumps({'action': 'run'}))
        env = os.environ.copy()
        paths = [str(root / 'outputs' / 'observatory'), str(root / 'work' / 'openmp')]
        if env.get('PYTHONPATH'):
            paths.append(env['PYTHONPATH'])
        env['PYTHONPATH'] = os.pathsep.join(paths)
        env['OMP_NUM_THREADS'] = '1'
        env['OMP_DYNAMIC'] = 'false'
        result = subprocess.run(
            [sys.executable, str(root / 'outputs' / 'observatory' / 'worker.py'), str(run_dir)],
            cwd=root / 'outputs' / 'observatory', env=env, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        status_path = run_dir / 'status.json'
        status = json.loads(status_path.read_text()) if status_path.is_file() else {}
        checkpoint = run_dir / 'checkpoint.json'
        if result.returncode != 0 or status.get('phase') != 'complete' or not checkpoint.is_file():
            detail = (result.stderr or result.stdout or status.get('error') or 'worker did not complete')[-1200:]
            raise RuntimeError(f'Open Orbital preflight worker failed: {detail}')
        meta = json.loads((run_dir / 'meta.json').read_text())
        if not math.isfinite(float(status.get('computed_time') or 0)):
            raise RuntimeError('Open Orbital preflight produced non-finite computed time')
        return {
            'status': 'passed', 'phase': status['phase'], 'frames': status.get('frames'),
            'model_revision': meta.get('model_revision'), 'checkpoint_written': True,
            'temporary_data_removed': True,
        }
