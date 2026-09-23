"""Deterministic expansion of a reviewed ExperimentPlan into immutable run configs."""
import hashlib
import itertools
import json
import random
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from lab.observatory import physics, server
from lab.planner.models import ExperimentPlan
from lab.safety import guard, provenance

OUTPUTS = {
    'disk_half_radius', 'halo_half_radius', 'angular_momentum', 'energy_change',
    'star_formation_rate', 'births', 'deaths', 'supernovae', 'galaxy_separation',
    'particle_counts', 'orbital_elements', 'computed_time', 'checkpoint_status',
}


def expand_plan(plan: ExperimentPlan, limits, data_dir: Path):
    """Return exactly one validated config per requested simulation, with stable IDs and seeds."""
    if plan.mode not in ('galaxy', 'planets'):
        raise ValueError('Choose galaxy or planetary mode')
    if plan.aggregate_groups * plan.simulations_per_group > int(limits.max_total_runs):
        raise ValueError(f'Total run count exceeds the configured limit of {limits.max_total_runs}')
    unsupported_outputs = set(plan.requested_outputs) - OUTPUTS
    if unsupported_outputs:
        raise ValueError('Unsupported requested outputs: ' + ', '.join(sorted(unsupported_outputs)))
    groups = _sweep_groups(plan)
    if len(groups) != plan.aggregate_groups:
        raise ValueError(f'Sampling produced {len(groups)} groups; expected {plan.aggregate_groups}')
    base = dict(plan.fixed_parameters)
    base['mode'] = plan.mode
    if plan.mode == 'galaxy':
        if plan.n_galaxies is not None:
            base['n_galaxies'] = plan.n_galaxies
        if plan.duration_gyr is not None:
            base['duration'] = plan.duration_gyr * 1000.0 / float(physics().MYR_PER_TIME)
        elif plan.duration is not None:
            base['duration'] = plan.duration
        if 'n_galaxies' not in base:
            raise ValueError('The galaxy count is required')
        if 'n' not in base and not any('n' in group for group in groups):
            raise ValueError('Particle resolution is required for a research ensemble')
    elif plan.duration is not None:
        base['duration'] = plan.duration
    if plan.mode == 'planets' and 'duration' not in base:
        raise ValueError('Planetary duration in years is required')
    base_seed = int(base.pop('seed', server().DEFAULTS['seed']))
    if not 0 <= base_seed <= 2**32 - 1:
        raise ValueError('Base seed is outside the observatory range')
    base.setdefault('threads', server().DEFAULTS['threads'])
    runs = []
    for group_index, values in enumerate(groups):
        for replicate_index in range(plan.simulations_per_group):
            run_index = group_index * plan.simulations_per_group + replicate_index
            raw = dict(base)
            raw.update(values)
            raw['seed'] = (base_seed + run_index) % (2**32)
            normalized = guard(server().normalize(raw), limits, data_dir)
            runs.append({
                'simulation_id': uuid.uuid4().hex[:12],
                'group_index': group_index,
                'replicate_index': replicate_index,
                'run_index': run_index,
                'seed': raw['seed'],
                'sweep_values': values,
                'config': normalized,
            })
    if len(runs) != plan.total_runs:
        raise AssertionError('Matrix expansion count changed unexpectedly')
    return runs


def _sweep_groups(plan):
    count = plan.aggregate_groups
    if not plan.sweep:
        return [{} for _ in range(count)]
    method = plan.sampling_method
    dims = list(plan.sweep.items())
    if method == 'grid':
        axes = []
        for key, dimension in dims:
            if 'values' not in dimension:
                raise ValueError(f'Grid sampling requires explicit values for {key}')
            axes.append([(key, value) for value in dimension['values']])
        combos = [dict(items) for items in itertools.product(*axes)]
        if len(combos) != count:
            raise ValueError(f'Grid has {len(combos)} combinations but aggregate_groups is {count}')
        return combos
    rng = random.Random(int(plan.fixed_parameters.get('seed', server().DEFAULTS['seed'])))
    samples = {i: {} for i in range(count)}
    for key, dimension in dims:
        if 'values' in dimension:
            choices = list(dimension['values'])
            if method == 'user_defined':
                if len(choices) != count:
                    raise ValueError(f'user_defined sweep {key} needs exactly {count} values')
                values = choices
            elif method == 'random':
                values = [rng.choice(choices) for _ in range(count)]
            elif method == 'latin_hypercube':
                values = [choices[i % len(choices)] for i in range(count)]
                rng.shuffle(values)
            else:
                raise ValueError(f'Unsupported sampling method: {method}')
        else:
            if method == 'user_defined':
                raise ValueError(f'user_defined sweep {key} needs an explicit values list')
            lo, hi = float(dimension['min']), float(dimension['max'])
            if method == 'random':
                values = [rng.uniform(lo, hi) for _ in range(count)]
            elif method == 'latin_hypercube':
                bins = [(i + rng.random()) / count for i in range(count)]
                rng.shuffle(bins)
                values = [lo + (hi - lo) * q for q in bins]
            else:
                raise ValueError(f'Unsupported sampling method: {method}')
        for index, value in enumerate(values):
            samples[index][key] = value
    return [samples[i] for i in range(count)]


def build_manifest(experiment_id, job_id, request, dialogue, plan, runs, resource_estimate,
                   cfg, root: Path, report, revision=1):
    commit, dirty, fingerprint = source_snapshot(root)
    revision = int(revision)
    defaults = []
    provided = set(plan.fixed_parameters) | set(plan.sweep) | set(plan.user_supplied_fields)
    if plan.n_galaxies is not None:
        provided.add('n_galaxies')
    if plan.duration is not None or plan.duration_gyr is not None:
        provided.add('duration')
    for key in (server().GALAXY_KEYS if plan.mode == 'galaxy' else server().PLANET_KEYS):
        if key not in provided:
            defaults.append(key)
    model_duration = plan.duration
    if model_duration is None and plan.duration_gyr is not None:
        model_duration = plan.duration_gyr * 1000.0 / float(physics().MYR_PER_TIME)
    manifest = {
        'format': 'open-orbital-experiment-manifest/v1',
        'experiment_id': experiment_id,
        'job_id': job_id,
        'revision': revision,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'original_request': request,
        'clarification_dialogue': dialogue,
        'objective': plan.objective,
        'mode': plan.mode,
        'scientific_parameters': {
            'duration_gyr': plan.duration_gyr,
            'duration': model_duration,
            'n_galaxies': plan.n_galaxies,
            'fixed_parameters': plan.fixed_parameters,
            'safe_defaults': defaults,
            'sweep': plan.sweep,
        },
        'sampling': {
            'method': plan.sampling_method,
            'aggregate_groups': plan.aggregate_groups,
            'simulations_per_group': plan.simulations_per_group,
            'total_runs': len(runs),
            'base_seed': int(plan.fixed_parameters.get('seed', server().DEFAULTS['seed'])),
            'seed_policy': 'base_seed plus run_index modulo 2^32; every generated seed is stored per run',
        },
        'requested_outputs': plan.requested_outputs,
        'expected_outputs': sorted(set(plan.requested_outputs) | {'progress', 'final_diagnostics', 'checkpoint_status'}),
        'user_supplied_fields': plan.user_supplied_fields,
        'generated_fields': ['seed'] if 'seed' not in plan.user_supplied_fields else [],
        'planner_inferences': plan.planner_inferences,
        'planner_estimates': plan.planner_estimates,
        'field_decisions': report.to_dict(),
        'resource_estimate': resource_estimate,
        'source': {
            'git_commit': commit,
            'git_dirty': dirty,
            'source_tree_sha256': fingerprint,
            'model_revision': int(physics().MODEL_REVISION),
            'rebound': 'recorded by each worker at runtime',
        },
        'models': {
            'planner': {'provider': 'OpenRouter', 'model': cfg.luna_model, 'version': cfg.luna_model},
            'decision': {'provider': 'OpenRouter', 'model': cfg.jev_model, 'version': cfg.jev_model},
        },
        'provenance': provenance(root, defaults),
        'runs': [{k: run[k] for k in ('simulation_id', 'group_index', 'replicate_index', 'run_index', 'seed', 'sweep_values', 'config')} for run in runs],
        'scientific_limits': [
            'The galaxy model is exploratory and collisionless, not a calibrated equilibrium model.',
            'A short preflight or run does not establish long-term astrophysical stability.',
            'Energy diagnostics with lifecycle enabled and large-N sampled energy are not integration-error bounds.',
        ],
    }
    encoded = canonical_json(manifest)
    manifest['sha256'] = hashlib.sha256(encoded).hexdigest()
    return manifest


def source_snapshot(root: Path):
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, capture_output=True, check=True).stdout.strip()
        status = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=root, text=True, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return 'unknown', True, 'unknown'
    files = []
    for base in (root / 'lab', root / 'outputs' / 'observatory', root / '.github' / 'workflows'):
        if not base.exists():
            continue
        for path in base.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py', '.yml', '.yaml', '.toml', '.sh', '.txt', '.c', '.h'):
                files.append(path)
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b'\0')
        digest.update(path.read_bytes())
    return commit, bool(status.strip()), digest.hexdigest()


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
