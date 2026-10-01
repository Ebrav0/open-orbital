"""Jev decides what is known. Luna writes only when a decision is not enough."""
from lab.observatory import server
from lab.planner.openrouter import PlannerError
from lab.safety import REQUIRED_GALAXY, REQUIRED_PLANETS, accept_explicit, provenance

NOUL = {
    'n': ('Does the request state how many particles to use?', 'A particle count is stated', 'No particle count is stated'),
    'duration': ('Does the request state the simulation duration or span?', 'A duration is stated', 'No duration is stated'),
    'dt': ('Does the request state a timestep?', 'A timestep is stated', 'No timestep is stated'),
    'lifecycle_enabled': ('Does the request say whether stellar lifecycle is on or off?', 'Lifecycle is stated', 'Lifecycle is not stated'),
    'seed': ('Does the request state a random seed or a seed policy?', 'A seed is stated', 'No seed is stated'),
    'n_galaxies': ('Does the request state how many galaxies to simulate?', 'A galaxy count is stated', 'No galaxy count is stated'),
    'jupiter_mass': ('Does the request state Jupiter mass as 1, 3, or 10?', 'Jupiter mass is stated', 'Jupiter mass is not stated'),
}


class Plan:
    def __init__(self, specs=None, questions=None, backend=None, provenance_doc=None):
        self.specs = specs or []
        self.questions = questions or []
        self.backend = backend
        self.provenance = provenance_doc or {}

    @property
    def ready(self):
        return bool(self.specs) and not self.questions


def plan_request(text, cfg, limits, data_dir, root, confirm_defaults=False, client=None):
    if client is None:
        from lab.planner.openrouter import OpenRouter
        client = OpenRouter(cfg)
    try:
        answers = client.decisions(text, _questions())['answers']
    except PlannerError as exc:
        return Plan(questions=[str(exc)])
    except (KeyError, TypeError) as exc:
        return Plan(questions=[f'Jev returned an unusable decision: {exc}'])
    mode = _choice(answers, 'mode') or ''
    backend = _choice(answers, 'backend') or cfg.default_backend
    if backend not in ('local', 'github'):
        backend = cfg.default_backend
    required = REQUIRED_PLANETS if mode == 'planets' else REQUIRED_GALAXY
    if mode not in ('galaxy', 'planets'):
        required = REQUIRED_GALAXY
    missing = [key for key in required if not _present(answers, key, cfg.noul_threshold)]
    if mode not in ('galaxy', 'planets'):
        missing = ['mode', *missing]
    if missing:
        return Plan(questions=_ask(client, text, missing), backend=backend)
    try:
        drafted = _draft(client, text, mode, required)
    except (PlannerError, ValueError, KeyError, TypeError) as exc:
        return Plan(questions=[f'Luna could not draft a spec: {exc}'], backend=backend)
    for key in required:
        if key not in drafted or drafted[key] is None:
            missing.append(key)
    if missing:
        return Plan(questions=[f'Still missing: {", ".join(missing)}. No job was stored.'], backend=backend)
    schema_keys = server().GALAXY_KEYS if mode == 'galaxy' else server().PLANET_KEYS
    defaulted = [key for key in schema_keys if key not in drafted or drafted[key] is None]
    if defaulted and not confirm_defaults:
        shown = ', '.join(defaulted[:12])
        extra = '' if len(defaulted) <= 12 else f' and {len(defaulted) - 12} more'
        return Plan(questions=[
            f'Unmentioned observatory fields would be defaulted: {shown}{extra}.',
            'Repeat the command with --confirm-defaults to accept those defaults, or name the values you want.',
        ], backend=backend)
    spec = {key: drafted[key] for key in schema_keys if key in drafted and drafted[key] is not None}
    spec['mode'] = mode
    if isinstance(drafted.get('matrix'), dict):
        spec['matrix'] = drafted['matrix']
    if drafted.get('notes'):
        spec['notes'] = drafted['notes']
    try:
        specs = accept_explicit(spec, limits, data_dir)
    except ValueError as exc:
        return Plan(questions=[str(exc)], backend=backend)
    return Plan(specs=specs, backend=backend, provenance_doc=provenance(root, defaulted if confirm_defaults else []))


def _questions():
    questions = {
        'mode': {
            'type': 'choice',
            'instructions': 'Which observatory mode does the request describe?',
            'options': {
                'galaxy': 'An N-body galaxy or galaxy encounter',
                'planets': 'The planetary system',
                'unclear': 'The mode is not stated',
            },
        },
        'backend': {
            'type': 'choice',
            'instructions': 'Which compute backend does the request ask for?',
            'options': {
                'local': 'The coordinator machine',
                'github': 'GitHub-hosted runners',
                'unspecified': 'No backend is stated',
            },
        },
    }
    for key, (instructions, yes, no) in NOUL.items():
        questions[key] = {'type': 'noul', 'instructions': instructions, 'true': yes, 'false': no}
    return questions


def _present(answers, key, threshold):
    answer = answers.get(key) or {}
    try:
        return float(answer.get('noul')) >= float(threshold)
    except (TypeError, ValueError):
        return False


def _choice(answers, key):
    answer = answers.get(key) or {}
    value = answer.get('choice')
    if value in (None, 'unclear', 'unspecified'):
        return None
    return value


def _ask(client, text, missing):
    try:
        payload = client.chat([
            {'role': 'system', 'content': (
                'Write JSON {"questions": ["..."]}. Ask only for the missing scientific parameters. '
                'Do not invent values, measurements, or defaults.'
            )},
            {'role': 'user', 'content': f'Request: {text}\nMissing: {", ".join(missing)}'},
        ])
        content = _message_json(payload)
        questions = content.get('questions') if isinstance(content, dict) else None
        if isinstance(questions, list) and questions:
            return [str(item) for item in questions]
    except (PlannerError, ValueError, KeyError, TypeError):
        pass
    return [f'Provide {", ".join(missing)} before a job can be stored.']


def _draft(client, text, mode, required):
    payload = client.chat([
        {'role': 'system', 'content': (
            'Extract a JSON object of observatory settings that the user explicitly stated. '
            'Use null for anything not stated. Do not invent measurements. '
            'Include mode, the required keys, optional matrix {parameter, start, stop, count}, and notes.'
        )},
        {'role': 'user', 'content': f'mode={mode}\nrequired={",".join(required)}\nrequest:\n{text}'},
    ])
    content = _message_json(payload)
    if not isinstance(content, dict):
        raise ValueError('Luna did not return a spec object')
    return content


def _message_json(payload):
    import json
    content = payload['choices'][0]['message']['content']
    if isinstance(content, dict):
        return content
    return json.loads(content)
