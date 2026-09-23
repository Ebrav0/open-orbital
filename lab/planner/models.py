"""Typed, versioned data shapes used by the research planner and manifest builder."""
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

DecisionCategory = Literal[
    'SUPPLIED', 'SAFE_DEFAULT', 'DERIVABLE', 'REQUIRED_FROM_USER', 'INVALID', 'INCOMPATIBLE'
]
DECISION_CATEGORIES = {
    'SUPPLIED', 'SAFE_DEFAULT', 'DERIVABLE', 'REQUIRED_FROM_USER', 'INVALID', 'INCOMPATIBLE'
}


@dataclass
class ExperimentPlan:
    objective: str
    mode: str
    duration_gyr: float | None = None
    duration: float | None = None
    n_galaxies: int | None = None
    aggregate_groups: int = 1
    simulations_per_group: int = 1
    sampling_method: str = 'grid'
    sweep: dict[str, dict[str, Any]] = field(default_factory=dict)
    fixed_parameters: dict[str, Any] = field(default_factory=dict)
    requested_outputs: list[str] = field(default_factory=list)
    planner_estimates: dict[str, Any] = field(default_factory=dict)
    user_supplied_fields: list[str] = field(default_factory=list)
    planner_inferences: list[str] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    schema_version: int = 1

    @property
    def total_runs(self):
        return int(self.aggregate_groups) * int(self.simulations_per_group)

    def to_dict(self):
        doc = asdict(self)
        doc['total_runs'] = self.total_runs
        return doc

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('Luna must return a JSON object')
        allowed = {
            'objective', 'mode', 'duration_gyr', 'duration', 'n_galaxies',
            'aggregate_groups', 'groups', 'simulations_per_group', 'runs_per_group',
            'total_runs', 'sampling_method', 'sweep', 'fixed_parameters',
            'requested_outputs', 'planner_estimates', 'user_supplied_fields', 'planner_inferences',
            'unresolved', 'schema_version',
        }
        extra = set(value) - allowed
        if extra:
            raise ValueError('Unknown plan fields: ' + ', '.join(sorted(extra)))
        groups = value.get('aggregate_groups', value.get('groups', 1))
        per_group = value.get('simulations_per_group', value.get('runs_per_group', 1))
        groups = _positive_int(groups, 'aggregate_groups', 10000)
        per_group = _positive_int(per_group, 'simulations_per_group', 10000)
        declared_total = value.get('total_runs')
        if declared_total is not None:
            declared_total = _positive_int(declared_total, 'total_runs', 100_000_000)
            if declared_total != groups * per_group:
                raise ValueError('total_runs must equal aggregate_groups × simulations_per_group')
        duration_gyr = value.get('duration_gyr')
        duration = value.get('duration')
        if duration_gyr is not None and duration is not None:
            raise ValueError('Specify duration_gyr or internal duration, not both')
        duration_gyr = _optional_positive_float(duration_gyr, 'duration_gyr')
        duration = _optional_positive_float(duration, 'duration')
        n_galaxies = value.get('n_galaxies')
        if n_galaxies is not None:
            n_galaxies = _positive_int(n_galaxies, 'n_galaxies', 100)
        sweep = value.get('sweep', {})
        fixed = value.get('fixed_parameters', {})
        if not isinstance(sweep, dict) or not isinstance(fixed, dict):
            raise ValueError('sweep and fixed_parameters must be objects')
        normalized_sweep = {}
        for key, dimension in sweep.items():
            if not isinstance(dimension, dict):
                raise ValueError(f'sweep[{key}] must be an object')
            if 'values' in dimension:
                values = dimension['values']
                if not isinstance(values, list) or not values:
                    raise ValueError(f'sweep[{key}].values must be a non-empty list')
                normalized_sweep[key] = {'values': values}
            elif 'min' in dimension and 'max' in dimension:
                lo = _finite_float(dimension['min'], f'sweep[{key}].min')
                hi = _finite_float(dimension['max'], f'sweep[{key}].max')
                if hi < lo:
                    raise ValueError(f'sweep[{key}].max must be at least min')
                normalized_sweep[key] = {'min': lo, 'max': hi}
            else:
                raise ValueError(f'sweep[{key}] needs values or min/max')
        if not isinstance(value.get('planner_estimates', {}), dict):
            raise ValueError('planner_estimates must be an object')
        for name in ('requested_outputs', 'user_supplied_fields', 'planner_inferences'):
            if not isinstance(value.get(name, []), list):
                raise ValueError(f'{name} must be a list')
        method_explicit = 'sampling_method' in value
        inferred_method = 'latin_hypercube' if any('min' in item and 'max' in item for item in normalized_sweep.values()) else 'grid'
        sampling_method = str(value.get('sampling_method') or inferred_method).lower()
        unresolved = value.get('unresolved', [])
        if not isinstance(unresolved, list):
            raise ValueError('unresolved must be a list')
        return cls(
            objective=str(value.get('objective') or '').strip(),
            mode=str(value.get('mode') or '').strip(),
            duration_gyr=duration_gyr,
            duration=duration,
            n_galaxies=n_galaxies,
            aggregate_groups=groups,
            simulations_per_group=per_group,
            sampling_method=sampling_method,
            sweep=normalized_sweep,
            fixed_parameters=dict(fixed),
            requested_outputs=[str(x) for x in value.get('requested_outputs', [])],
            planner_estimates=dict(value.get('planner_estimates', {})),
            user_supplied_fields=[str(x) for x in value.get('user_supplied_fields', [])],
            planner_inferences=[str(x) for x in value.get('planner_inferences', [])] + ([
                'Latin-hypercube sampling was selected to span continuous ranges because no method was specified.'
            ] if not method_explicit and inferred_method == 'latin_hypercube' else []),
            unresolved=[dict(x) if isinstance(x, dict) else {'question': str(x)} for x in unresolved],
            schema_version=int(value.get('schema_version', 1)),
        )


@dataclass(frozen=True)
class FieldDecision:
    field: str
    category: DecisionCategory
    rationale: str = ''
    value: Any = None


@dataclass
class DecisionReport:
    fields: dict[str, FieldDecision] = field(default_factory=dict)
    required_from_user: list[dict[str, str]] = field(default_factory=list)
    invalid: list[dict[str, str]] = field(default_factory=list)
    incompatible: list[dict[str, str]] = field(default_factory=list)
    model_notes: list[str] = field(default_factory=list)

    @property
    def complete(self):
        return not (self.required_from_user or self.invalid or self.incompatible)

    def to_dict(self):
        return {
            'fields': {k: asdict(v) for k, v in self.fields.items()},
            'required_from_user': list(self.required_from_user),
            'invalid': list(self.invalid),
            'incompatible': list(self.incompatible),
            'model_notes': list(self.model_notes),
            'complete': self.complete,
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('Jev must return a JSON object')
        fields = {}
        raw_fields = value.get('fields', value.get('field_decisions', {}))
        if not isinstance(raw_fields, dict):
            raise ValueError('Jev fields must be an object')
        for name, raw in raw_fields.items():
            if isinstance(raw, str):
                raw = {'category': raw}
            if not isinstance(raw, dict):
                continue
            category = str(raw.get('category') or '').upper()
            if category not in DECISION_CATEGORIES:
                category = 'REQUIRED_FROM_USER'
            fields[name] = FieldDecision(name, category, str(raw.get('rationale') or ''), raw.get('value'))
        return cls(
            fields=fields,
            required_from_user=_issue_list(value.get('required_from_user')),
            invalid=_issue_list(value.get('invalid')),
            incompatible=_issue_list(value.get('incompatible')),
            model_notes=[str(x) for x in value.get('model_notes', []) if x is not None],
        )


def _issue_list(value):
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, dict):
            result.append({'field': str(item.get('field') or ''), 'reason': str(item.get('reason') or item.get('question') or '')})
        else:
            result.append({'field': '', 'reason': str(item)})
    return result


def _positive_int(value, name, maximum):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be an integer')
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be an integer') from None
    if result < 1 or result > maximum:
        raise ValueError(f'{name} must be from 1 to {maximum}')
    if isinstance(value, float) and value != result:
        raise ValueError(f'{name} must be an integer')
    return result


def _finite_float(value, name):
    import math
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be numeric') from None
    if not math.isfinite(result):
        raise ValueError(f'{name} must be finite')
    return result


def _optional_positive_float(value, name):
    if value is None:
        return None
    result = _finite_float(value, name)
    if result <= 0:
        raise ValueError(f'{name} must be positive')
    return result
