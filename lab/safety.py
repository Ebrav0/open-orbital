"""Hard limits. Planner output is checked here again before a job row exists."""
import shutil
from pathlib import Path

from lab.config import RUNTIME_CEILING_HOURS
from lab.observatory import physics, server

PROTECTED_NOTE = (
    'Merger metrics are integrator diagnostics from this exploratory model, '
    'not astronomical observations. A short run does not establish long-term stability '
    'or a calibrated equilibrium.'
)

# Natural-language submit must ask for these. Observatory defaults are not a substitute.
REQUIRED_GALAXY = ('n', 'duration', 'dt', 'lifecycle_enabled', 'seed', 'n_galaxies')
REQUIRED_PLANETS = ('duration', 'seed', 'jupiter_mass')

# Prediction from the measured ~424 MiB resident set of a 1,000,000-particle run on computenode1.
# It is not a new measurement.
_RAM_BASE_MIB = 80
_RAM_PER_MILLION_MIB = 450


def ram_mib(cfg):
    n = int(cfg.get('n') or 10)
    return _RAM_BASE_MIB + _RAM_PER_MILLION_MIB * (n / 1_000_000)


def required_keys(mode):
    if mode == 'planets':
        return REQUIRED_PLANETS
    return REQUIRED_GALAXY


def git_commit(root: Path):
    head = root / '.git' / 'HEAD'
    try:
        text = head.read_text().strip()
    except OSError:
        return 'unknown'
    if text.startswith('ref:'):
        ref = root / '.git' / text.split(' ', 1)[1].strip()
        try:
            return ref.read_text().strip()
        except OSError:
            return 'unknown'
    return text


def provenance(root: Path, defaulted):
    return dict(
        model_revision=int(physics().MODEL_REVISION),
        git_commit=git_commit(root),
        rebound='reported by the worker at runtime',
        scientific_note=PROTECTED_NOTE,
        defaulted_keys=list(defaulted),
        ram_estimate='prediction',
    )


def _clamp_threads(cfg, limits):
    if cfg['mode'] != 'galaxy':
        return cfg
    allowed = [int(v) for v in server().SCHEMA['threads'][1]]
    cap = int(limits.max_threads)
    choices = [v for v in allowed if v <= cap]
    chosen = max(choices) if choices else allowed[0]
    requested = int(cfg['threads'])
    cfg = dict(cfg)
    cfg['threads'] = requested if requested in choices else chosen
    return cfg


def accept_explicit(spec, limits, data_dir: Path):
    """JSON specs may rely on observatory normalize() defaults. Natural language may not."""
    if not isinstance(spec, dict):
        raise ValueError('Experiment spec must be an object')
    for banned in ('wall_cap_hours', 'wall_capped', 'model_revision'):
        if banned in spec:
            raise ValueError(f'{banned} cannot be set by a job spec')
    raw_shards = expand(spec)
    accepted = []
    for raw in raw_shards:
        ident = str(raw.get('id') or '')
        if ident in server().PROTECTED:
            raise ValueError('Protected observatory runs cannot be targeted by Lab')
        cfg = server().normalize(raw)
        accepted.append(guard(cfg, limits, data_dir))
    return accepted


def guard(cfg, limits, data_dir: Path):
    cfg = _clamp_threads(cfg, limits)
    if cfg['mode'] == 'galaxy' and int(cfg['n_galaxies']) > 5:
        raise ValueError('At most 5 galaxies')
    hours = float(cfg['estimated_seconds']) / 3600
    if hours > limits.max_runtime_hours or hours > RUNTIME_CEILING_HOURS:
        raise ValueError(
            f'Estimated {hours:.1f} h exceeds the runtime cap of {limits.max_runtime_hours} h. '
            'That estimate is a scaling from the revision-2 reference, not a new measurement.'
        )
    needed = ram_mib(cfg)
    if needed > limits.max_ram_mib:
        raise ValueError(
            f'Predicted resident memory {needed:.0f} MiB exceeds max_ram_mib {limits.max_ram_mib}. '
            'The prediction scales from one 1,000,000-particle measurement.'
        )
    free = shutil.disk_usage(data_dir if data_dir.exists() else data_dir.parent).free
    if free < limits.disk_floor_bytes:
        raise ValueError('Coordinator free space is below the 2 GiB floor')
    ident = str(cfg.get('id') or '')
    if ident in server().PROTECTED:
        raise ValueError('Protected observatory runs cannot be targeted by Lab')
    return cfg


def expand(spec):
    matrix = spec.get('matrix')
    base = {k: v for k, v in spec.items() if k != 'matrix'}
    if not matrix:
        return [base]
    if not isinstance(matrix, dict):
        raise ValueError('matrix must be an object')
    parameter = matrix.get('parameter')
    schema = server().SCHEMA
    if parameter not in schema:
        raise ValueError(f'matrix parameter {parameter} is not an observatory field')
    count = int(matrix['count'])
    if count < 1 or count > 500:
        raise ValueError('matrix count must be from 1 to 500')
    start = float(matrix['start'])
    stop = float(matrix['stop'])
    shards = []
    for value in inclusive_values(start, stop, count):
        item = dict(base)
        item[parameter] = value
        shards.append(item)
    return shards


def inclusive_values(start, stop, count):
    if count == 1:
        return [start]
    step = (stop - start) / (count - 1)
    return [start + step * i for i in range(count)]
