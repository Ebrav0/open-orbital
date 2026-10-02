"""Lab command line for natural-language planning, immutable experiments and worker control."""
import argparse
import hashlib
import json
import secrets
import sys
import uuid
from pathlib import Path

from lab.backends.stubs import STUBS
from lab.config import load_config
from lab.coordinator.db import Database
from lab.coordinator.service import serve
from lab.paths import ROOT
from lab.planner.manifest import build_manifest, canonical_json, expand_plan
from lab.planner.models import ExperimentPlan
from lab.planner.openrouter import OpenRouter, PlannerError
from lab.planner.pipeline import PlanningResult, start_plan, update_plan
from lab.preflight import estimate_resources, run_validation_case
from lab.safety import accept_explicit, provenance
from lab.specs import read_spec
from lab.storage import build_store, file_sha256
from lab.worker.agent import run_once

IMPLEMENTED = ('local', 'github')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='lab')
    sub = parser.add_subparsers(dest='command', required=True)

    ask = sub.add_parser('ask', help='plan a research experiment from plaintext')
    ask.add_argument('request')
    ask.add_argument('--backend', choices=IMPLEMENTED)
    ask.add_argument('--yes', action='store_true', help='schedule after deterministic preflight without an interactive confirmation')
    ask.add_argument('--no-interactive', action='store_true', help='save clarification state and print its ID')

    revise = sub.add_parser('revise', help='create a new immutable revision of a stopped experiment')
    revise.add_argument('experiment_id')
    revise.add_argument('instruction')
    revise.add_argument('--backend', choices=IMPLEMENTED)
    revise.add_argument('--yes', action='store_true')
    revise.add_argument('--no-interactive', action='store_true')

    answer = sub.add_parser('answer', help='continue a saved clarification conversation')
    answer.add_argument('conversation_id')
    answer.add_argument('answer')
    answer.add_argument('--backend', choices=IMPLEMENTED)
    answer.add_argument('--yes', action='store_true')

    schedule = sub.add_parser('schedule', help='schedule a complete, saved plan after preflight')
    schedule.add_argument('conversation_id')
    schedule.add_argument('--backend', choices=IMPLEMENTED)
    schedule.add_argument('--yes', action='store_true')

    submit = sub.add_parser('submit', help='submit an explicit JSON spec (or use ask for plaintext)')
    submit.add_argument('--spec', required=True)
    submit.add_argument('--backend', choices=IMPLEMENTED)

    experiments = sub.add_parser('experiments', help='list frozen experiments')
    sub.add_parser('workers', help='list workers')
    status = sub.add_parser('status', help='show aggregate status or one job/experiment')
    status.add_argument('id', nargs='?')
    show = sub.add_parser('show', help='show an experiment and its frozen manifest')
    show.add_argument('experiment_id')
    jobs = sub.add_parser('jobs', help='show jobs and shards for an experiment')
    jobs.add_argument('experiment_id')
    results = sub.add_parser('results', help='show verified final result records')
    results.add_argument('experiment_id')
    analyze = sub.add_parser('analyze', help='ask Luna for a sourced summary of completed results')
    analyze.add_argument('experiment_id')
    pause = sub.add_parser('pause', help='pause an experiment at the next valid checkpoint')
    pause.add_argument('experiment_id')
    resume = sub.add_parser('resume', help='resume a paused experiment')
    resume.add_argument('experiment_id')
    cancel = sub.add_parser('cancel', help='cancel an experiment or legacy job')
    cancel.add_argument('id')
    sub.add_parser('quotas', help='show configured limits and coordinator accounting')
    sub.add_parser('serve', help='run the coordinator and scheduler')
    worker = sub.add_parser('worker', help='claim and run one shard')
    worker.add_argument('--once', action='store_true')
    worker.add_argument('--backend', default='local', choices=IMPLEMENTED)

    args = parser.parse_args(argv)
    try:
        if args.command == 'ask':
            return ask_command(args)
        if args.command == 'answer':
            return answer_command(args)
        if args.command == 'revise':
            return revise_command(args)
        if args.command == 'schedule':
            return schedule_command(args)
        if args.command == 'submit':
            return submit_command(args)
        if args.command == 'experiments':
            return experiments_command()
        if args.command == 'workers':
            return workers_command()
        if args.command == 'status':
            return status_command(args)
        if args.command == 'show':
            return show_command(args.experiment_id)
        if args.command == 'jobs':
            return jobs_command(args.experiment_id)
        if args.command == 'results':
            return results_command(args.experiment_id)
        if args.command == 'analyze':
            return analyze_command(args.experiment_id)
        if args.command == 'pause':
            return pause_command(args.experiment_id)
        if args.command == 'resume':
            return resume_command(args.experiment_id)
        if args.command == 'cancel':
            return cancel_command(args.id)
        if args.command == 'quotas':
            return quotas_command()
        if args.command == 'serve':
            cfg = load_config()
            cfg.data.mkdir(parents=True, exist_ok=True)
            serve(cfg, Database(cfg.database), build_store(cfg))
            return 0
        if args.command == 'worker':
            cfg = load_config()
            return run_once(cfg, build_store(cfg), backend=args.backend)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 2


def ask_command(args):
    cfg = load_config()
    db = Database(cfg.database)
    result = start_plan(args.request, cfg)
    if result.error:
        print(result.error, file=sys.stderr)
        return 1
    conversation_id = uuid.uuid4().hex[:12]
    state = _state_from_result(args.request, result, [])
    db.save_conversation(conversation_id, state, 'ready' if result.ready else 'waiting')
    print(f'Conversation: {conversation_id}')
    return _continue_interaction(db, cfg, conversation_id, result, args.backend, args.yes, args.no_interactive)


def revise_command(args):
    cfg = load_config()
    db = Database(cfg.database)
    experiment = db.experiment(args.experiment_id)
    if experiment['job']['status'] not in ('complete', 'cancelled', 'held'):
        raise ValueError('Stop or finish the current revision first. Use lab cancel, then wait for active workers to release their leases.')
    db.validate_experiment_revision(args.experiment_id, 0.0, cfg.budget_worker_hours)
    plan = ExperimentPlan.from_dict(experiment['plan'])
    prior_dialogue = list(experiment.get('dialogue') or [])
    result = update_plan(experiment['request'], plan, prior_dialogue, args.instruction, cfg)
    dialogue = prior_dialogue + [{'questions': [f'Revision request for frozen revision {experiment["current_revision"]}.'], 'answer': args.instruction}]
    state = _state_from_result(experiment['request'], result, dialogue, {
        'existing_experiment_id': args.experiment_id,
        'revision_of': experiment['current_revision'],
        'backend': args.backend or experiment['job']['backend'],
    })
    conversation_id = uuid.uuid4().hex[:12]
    db.save_conversation(conversation_id, state, 'error' if result.error else ('ready' if result.ready else 'waiting'))
    print(f'Revision conversation: {conversation_id} (based on revision {experiment["current_revision"]})')
    if result.error:
        print(result.error, file=sys.stderr)
        return 1
    backend = args.backend or experiment['job']['backend']
    return _continue_interaction(db, cfg, conversation_id, result, backend, args.yes, args.no_interactive)


def answer_command(args):
    cfg = load_config()
    db = Database(cfg.database)
    conversation = db.get_conversation(args.conversation_id)
    if conversation['status'] not in ('waiting', 'error', 'ready'):
        raise ValueError(f"Conversation {args.conversation_id} is {conversation['status']}; use lab schedule to submit a ready plan")
    state = conversation['state']
    plan = ExperimentPlan.from_dict(state['plan'])
    dialogue = list(state.get('dialogue') or [])
    old_questions = list(state.get('questions') or [])
    result = update_plan(state['original_request'], plan, dialogue, args.answer, cfg)
    dialogue.append({'questions': old_questions, 'answer': args.answer})
    if result.error:
        state.update({'plan': result.plan.to_dict() if result.plan else plan.to_dict(), 'dialogue': dialogue, 'error': result.error})
        db.save_conversation(args.conversation_id, state, 'error')
        print(result.error, file=sys.stderr)
        return 1
    state = _state_from_result(state['original_request'], result, dialogue, state)
    db.save_conversation(args.conversation_id, state, 'ready' if result.ready else 'waiting')
    return _continue_interaction(db, cfg, args.conversation_id, result, args.backend, args.yes, no_interactive=not sys.stdin.isatty())


def _continue_interaction(db, cfg, conversation_id, result, backend, yes, no_interactive):
    state = db.get_conversation(conversation_id)['state']
    if result.error:
        print(result.error, file=sys.stderr)
        return 1
    while not result.ready:
        if not result.questions:
            print('Plan remains incomplete. Check the saved conversation with its ID.', file=sys.stderr)
            return 2
        print('\n'.join(f'{i + 1}. {question}' for i, question in enumerate(result.questions)))
        if no_interactive or not sys.stdin.isatty():
            print(f'Answer later with: lab answer {conversation_id} "your answer"')
            return 2
        try:
            answer = input('Your answer (Ctrl-D to continue later): ').strip()
        except EOFError:
            print(f'Clarification saved. Continue later with: lab answer {conversation_id} "your answer"')
            return 2
        if not answer:
            continue
        dialogue = list(state.get('dialogue') or [])
        dialogue.append({'questions': result.questions, 'answer': answer})
        result = update_plan(state['original_request'], result.plan, state.get('dialogue') or [], answer, cfg)
        if result.error:
            state['dialogue'] = dialogue
            state['error'] = result.error
            db.save_conversation(conversation_id, state, 'error')
            print(result.error, file=sys.stderr)
            return 1
        state = _state_from_result(state['original_request'], result, dialogue, state)
        db.save_conversation(conversation_id, state, 'ready' if result.ready else 'waiting')
    return _schedule_plan(db, cfg, conversation_id, state, backend, yes, no_interactive)


def _state_from_result(request, result, dialogue, previous_state=None):
    state = {
        'original_request': request,
        'plan': result.plan.to_dict() if result.plan else None,
        'decisions': result.decisions.to_dict(),
        'questions': list(result.questions),
        'dialogue': dialogue,
        'error': result.error,
    }
    for key in ('existing_experiment_id', 'revision_of', 'backend'):
        if previous_state and key in previous_state:
            state[key] = previous_state[key]
    return state


def schedule_command(args):
    cfg = load_config()
    db = Database(cfg.database)
    conversation = db.get_conversation(args.conversation_id)
    if conversation['status'] != 'ready':
        raise ValueError(f"Conversation {args.conversation_id} is not ready to schedule")
    return _schedule_plan(db, cfg, args.conversation_id, conversation['state'], args.backend, args.yes)


def _schedule_plan(db, cfg, conversation_id, state, backend, yes, no_interactive=False):
    backend = backend or state.get('backend') or cfg.default_backend
    if backend in STUBS:
        raise ValueError(f'{backend} is not configured')
    plan = ExperimentPlan.from_dict(state['plan'])
    if 'seed' not in plan.fixed_parameters:
        if 'generated_seed' not in state:
            state['generated_seed'] = secrets.randbelow(2**32)
            db.save_conversation(conversation_id, state, 'ready')
        plan.fixed_parameters['seed'] = int(state['generated_seed'])
    cfg.data.mkdir(parents=True, exist_ok=True)
    runs = expand_plan(plan, cfg, cfg.data)
    resources = estimate_resources(runs, cfg, backend=backend)
    existing_experiment_id = state.get('existing_experiment_id')
    revision = 1
    if existing_experiment_id:
        revision_info = db.validate_experiment_revision(existing_experiment_id, resources['total_worker_hours'], cfg.budget_worker_hours)
        revision = revision_info['revision']
        print(f'Revision {revision}; cumulative worker-time budget remaining: {revision_info["remaining_worker_hours"]:.2f} h')
    preflight = run_validation_case(runs[0]['config'], cfg=cfg, root=ROOT)
    print(f"Preflight: {preflight['status']} ({preflight['phase']}, model revision {preflight['model_revision']})")
    print(f"Runs: {len(runs)}; projected worker time: {resources['total_worker_hours']:.2f} h; "
          f"wall time at configured concurrency: {resources['expected_wall_hours_at_configured_concurrency']:.2f} h")
    print(f"Storage projection: {resources['storage_estimate_gib']:.3f} GiB; estimate: {resources['estimate_type']}")
    for warning in resources['warnings']:
        print(f'Estimate note: {warning}')
    if backend == 'github':
        _require_github_prerequisites(cfg, ROOT)
        commit, dirty, _ = _source_snapshot(ROOT)
        if dirty:
            raise ValueError('GitHub workers require a clean, committed source tree so the manifest SHA can be checked out exactly. Commit and push the reviewed feature branch, then retry.')
    store = build_store(cfg)
    if cfg.storage_backend == 'memory':
        raise ValueError('The process-local memory store cannot share coordinator and worker blobs. Use directory for local workers or Drive for GitHub workers.')
    answer_yes = yes
    if not answer_yes and not no_interactive and sys.stdin.isatty():
        answer_yes = input('Freeze this manifest and schedule the runs? [y/N] ').strip().lower() in ('y', 'yes')
    if not answer_yes:
        print(f'Plan and preflight saved. Schedule later with: lab schedule {conversation_id} --yes')
        return 0
    experiment_id = state.get('existing_experiment_id') or uuid.uuid4().hex[:12]
    job_id = uuid.uuid4().hex[:12]
    dialogue = list(state.get('dialogue') or [])
    manifest = build_manifest(experiment_id, job_id, state['original_request'], dialogue, plan, runs, resources, cfg, ROOT,
                              _report_from_state(state), revision=revision)
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    manifest_key = f"experiments/{experiment_id}/manifests/manifest-v{revision}-{manifest['sha256']}.json"
    cfg.scratch.mkdir(parents=True, exist_ok=True)
    local_manifest = cfg.scratch / f'manifest-{experiment_id}.json'
    try:
        local_manifest.write_bytes(manifest_bytes)
        store.put(manifest_key, local_manifest)
        blob_sha = file_sha256(local_manifest)
        if not store.verify(manifest_key, blob_sha, len(manifest_bytes)):
            raise ValueError('Uploaded immutable manifest failed SHA-256 verification')
    finally:
        try:
            local_manifest.unlink()
        except OSError:
            pass
    create = db.create_experiment_revision if existing_experiment_id else db.create_experiment
    created = create(
        experiment_id, job_id, [run['config'] for run in runs], backend, manifest,
        plan.to_dict(), state['decisions'], dialogue, state['original_request'],
        cfg.budget_worker_hours, cfg.max_attempts, manifest_key=manifest_key, resource_estimate=resources,
    )
    db.save_conversation(conversation_id, state, 'scheduled')
    print(f"Scheduled experiment {experiment_id}: {created['run_count']} runs, manifest revision {revision}, SHA-256 {manifest['sha256']}")
    print(f'Backend: {backend}; experiment job: {job_id}')
    return 0


def _require_github_prerequisites(cfg, root):
    if not cfg.github_token:
        raise ValueError('LAB_GITHUB_TOKEN is required on the coordinator to dispatch GitHub Actions.')
    if not cfg.worker_token:
        raise ValueError('LAB_WORKER_TOKEN is required; start the coordinator once to generate it before scheduling GitHub workers.')
    if not cfg.tailscale_host:
        raise ValueError('Set server.tailscale_host to the private coordinator address before scheduling GitHub workers.')
    if cfg.storage_backend != 'drive':
        raise ValueError('GitHub workers require the configured shared Drive store; set storage.backend = "drive".')
    if not cfg.rclone_config.is_file():
        raise ValueError(f'Google Drive configuration is missing: {cfg.rclone_config}')
    if not cfg.github_repo or not cfg.github_workflow:
        raise ValueError('Configure github.repo and github.workflow before scheduling GitHub workers.')
    commit, dirty, _ = _source_snapshot(root)
    if dirty:
        raise ValueError('GitHub workers require a clean, committed source tree so the manifest SHA can be checked out exactly. Commit and push the reviewed feature branch, then retry.')
    return commit


def _report_from_state(state):
    from lab.planner.models import DecisionReport
    return DecisionReport.from_dict(state.get('decisions') or {})


def _source_snapshot(root):
    from lab.planner.manifest import source_snapshot
    return source_snapshot(root)


def submit_command(args):
    cfg = load_config()
    cfg.data.mkdir(parents=True, exist_ok=True)
    spec = read_spec(args.spec)
    backend = args.backend or spec.pop('backend', None) or cfg.default_backend
    if backend in STUBS:
        raise ValueError(f'{backend} is not configured')
    shards = accept_explicit(spec, cfg, cfg.data)
    job_id = Database(cfg.database).create_job(
        shards, backend, provenance(ROOT, []), cfg.budget_worker_hours,
        request=f'explicit spec: {Path(args.spec).name}', max_attempts=cfg.max_attempts,
    )
    print(job_id)
    return 0


def experiments_command():
    db = Database(load_config().database)
    for exp in db.experiments():
        counts = exp['counts']
        complete = counts.get('complete', 0)
        running = counts.get('running', 0) + counts.get('leased', 0)
        waiting = counts.get('pending', 0)
        failed = counts.get('held', 0)
        print(f"{exp['id']}  {exp['status']}  runs={exp['run_count']} complete={complete} running={running} waiting={waiting} held={failed}  {exp['plan']['objective']}")
    return 0


def show_command(experiment_id):
    exp = Database(load_config().database).experiment(experiment_id)
    manifest = exp['manifest']['manifest']
    print(f"Experiment: {exp['id']}\nStatus: {exp['status']}\nObjective: {exp['plan']['objective']}\nRuns: {exp['run_count']}\nManifest revision: {exp['manifest']['revision']} SHA-256: {exp['manifest']['sha256']}")
    print(f"Source commit: {manifest['source']['git_commit']} (dirty tree: {manifest['source']['git_dirty']})")
    print(f"Planner: {manifest['models']['planner']['model']}\nDecision model: {manifest['models']['decision']['model']}")
    print('Scientific parameters:')
    print(json.dumps(manifest['scientific_parameters'], indent=2, ensure_ascii=False))
    resources = manifest['resource_estimate']
    resource_keys = ('run_count', 'total_worker_hours', 'expected_wall_hours_at_configured_concurrency',
                     'configured_concurrency', 'per_run_seconds_min', 'per_run_seconds_max',
                     'storage_estimate_gib', 'checkpoint_retention', 'estimate_sources', 'estimate_type', 'warnings')
    print('Resource estimate:')
    print(json.dumps({key: resources[key] for key in resource_keys if key in resources}, indent=2, ensure_ascii=False))
    return 0


def jobs_command(experiment_id):
    exp = Database(load_config().database).experiment(experiment_id)
    print(f"Experiment {exp['id']} — {len(exp['job']['shards'])} runs")
    for row in exp['job']['shards']:
        checkpoint = row['checkpoint']
        checkpoint_text = f"checkpoint {checkpoint['seq']} sha256={checkpoint['sha256'][:12]}" if checkpoint else 'no verified checkpoint'
        print(f"{row['idx']:04d} {row['id']} {row['state']} generation={row['attempt']} failures={row['failures']}/{row['max_attempts']} {checkpoint_text}")
    return 0


def results_command(experiment_id):
    db = Database(load_config().database)
    rows = db.results_for_experiment(experiment_id)
    for row in rows:
        print(f"{row['shard_id']} {row['sha256']} {row['size']} bytes {row['object_key']}")
        print(json.dumps(row['metadata'], ensure_ascii=False))
    print(f'Verified results: {len(rows)}')
    return 0


def _summarize_results(results, manifest):
    """Reduce verified per-run metadata to auditable counts and scalar distributions."""
    import math
    from collections import Counter

    runs = manifest.get('runs') or []
    sweep_keys = sorted({key for run in runs for key in (run.get('sweep_values') or {})})
    sweep_summary = {}
    for key in sweep_keys:
        values = [(run.get('sweep_values') or {}).get(key) for run in runs if key in (run.get('sweep_values') or {})]
        numeric = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))]
        if numeric:
            sweep_summary[key] = {'count': len(values), 'numeric_count': len(numeric), 'min': min(numeric), 'max': max(numeric), 'unique_count': len(set(numeric))}
            if len(set(numeric)) <= 12:
                sweep_summary[key]['values'] = sorted(set(numeric))
        else:
            counts = Counter(str(value) for value in values)
            sweep_summary[key] = {'count': len(values), 'categories': dict(sorted(counts.items())[:12])}

    phases = Counter()
    metric_values = {}
    for row in results:
        metadata = row.get('metadata') or {}
        status = metadata.get('status') or {}
        phases[str(status.get('phase') or 'unknown')] += 1
        diagnostics = (metadata.get('diagnostics_summary') or {}).get('last') or {}
        for key, value in diagnostics.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                metric_values.setdefault(key, []).append(float(value))

    result_summary = {'verified_runs': len(results), 'phases': dict(sorted(phases.items())), 'diagnostics': {}}
    for key, values in sorted(metric_values.items()):
        ordered = sorted(values)
        count = len(ordered)
        def quantile(fraction):
            position = (count - 1) * fraction
            lower = int(position)
            upper = min(lower + 1, count - 1)
            return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
        result_summary['diagnostics'][key] = {
            'count': count, 'missing': len(results) - count, 'min': ordered[0], 'mean': sum(ordered) / count,
            'median': quantile(0.5), 'p05': quantile(0.05), 'p95': quantile(0.95), 'max': ordered[-1],
        }
    return {'sweep_summary': sweep_summary, 'result_summary': result_summary}


def analyze_command(experiment_id):
    cfg = load_config()
    db = Database(cfg.database)
    exp = db.experiment(experiment_id)
    results = db.results_for_experiment(experiment_id)
    if not results:
        raise ValueError('No verified final results are recorded yet')
    if len(results) != exp['run_count'] or exp['status'] != 'complete':
        raise ValueError('Luna analysis is available after every run has a verified final result')
    manifest = exp['manifest']['manifest']
    summary = _summarize_results(results, manifest)
    result_set_hash = hashlib.sha256(''.join(sorted(row['sha256'] for row in results)).encode('ascii')).hexdigest()
    payload = {
        'experiment_id': experiment_id,
        'objective': exp['plan']['objective'],
        'manifest_sha256': exp['manifest']['sha256'],
        'verified_result_count': len(results),
        'verified_result_set_sha256': result_set_hash,
        'sampling': manifest['sampling'],
        'scientific_parameters': manifest['scientific_parameters'],
        'sweep_summary': summary['sweep_summary'],
        'result_summary': summary['result_summary'],
        'requested_outputs': manifest['requested_outputs'],
        'scientific_limits': manifest['scientific_limits'],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    input_hash = hashlib.sha256(encoded).hexdigest()
    response = OpenRouter(cfg).chat([
        {'role': 'system', 'content': 'You are GPT-6 Luna writing final analysis for Open Orbital. Return JSON only with an analysis string. Base every claim on supplied verified result summaries. Separate observed simulation outputs from interpretation. State sample size, missing/failed values, uncertainty, and simulator limitations. Do not call the exploratory galaxy model calibrated or treat a short run as proof of long-term stability.'},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
    ], model=cfg.luna_model, temperature=0.2)
    content = response.get('choices', [{}])[0].get('message', {}).get('content', '') if isinstance(response, dict) else ''
    try:
        analysis = json.loads(content).get('analysis', content)
    except (TypeError, ValueError):
        analysis = str(content)
    analysis_id = uuid.uuid4().hex[:12]
    db.save_analysis(analysis_id, experiment_id, cfg.luna_model, input_hash, str(analysis))
    print(str(analysis))
    print(f'Analysis record: {analysis_id}; source results hash: {input_hash}')
    return 0


def status_command(args):
    db = Database(load_config().database)
    if args.id:
        try:
            exp = db.experiment(args.id)
            counts = exp['counts']
            print(f"Experiment {exp['id']} {exp['status']} — runs={exp['run_count']} complete={counts.get('complete', 0)} running={counts.get('running', 0)+counts.get('leased',0)} waiting={counts.get('pending', 0)} held={counts.get('held', 0)}")
            print(f"GitHub actions active: {db.active_leases('github')} / 20; workers: {len(db.workers())}")
        except KeyError:
            job = db.job(args.id)
            print(f"{job['id']}  {job['status']}  backend={job['backend']}  used={job['used_worker_hours']:.3f}h/{job['budget_worker_hours']}h")
        return 0
    for exp in db.experiments():
        counts = exp['counts']
        print(f"{exp['id']}  {exp['status']}  complete={counts.get('complete',0)} running={counts.get('running',0)+counts.get('leased',0)} waiting={counts.get('pending',0)} held={counts.get('held',0)}")
    legacy = [job for job in db.jobs() if not job.get('experiment_id')]
    for job in legacy:
        print(f"{job['id']}  {job['status']}  backend={job['backend']}  used={job['used_worker_hours']:.3f}h/{job['budget_worker_hours']}h")
    return 0


def workers_command():
    db = Database(load_config().database)
    for worker in db.workers():
        print(f"{worker['id']}  {worker['backend']}  {worker['status']}  {worker['host']}")
    return 0


def cancel_command(ident):
    db = Database(load_config().database)
    try:
        exp = db.experiment(ident)
    except KeyError:
        job = db.cancel(ident)
        print(json.dumps({'id': job['id'], 'status': job['status']}))
    else:
        job = db.cancel(exp['job_id'])
        print(json.dumps({'experiment_id': ident, 'id': job['id'], 'status': job['status']}))
    return 0


def pause_command(experiment_id):
    exp = Database(load_config().database).pause_experiment(experiment_id)
    print(f"Paused {experiment_id}; active workers will publish a valid checkpoint and hand off on their next heartbeat.")
    return 0


def resume_command(experiment_id):
    exp = Database(load_config().database).resume_experiment(experiment_id)
    print(f"Resumed {experiment_id}: {exp['status']}")
    return 0


def quotas_command():
    cfg = load_config()
    db = Database(cfg.database)
    print(f'GitHub worker cap: {cfg.github_concurrency} (hard maximum 20)')
    print(f'Active GitHub leases: {db.active_leases("github")}')
    print(f'Local worker concurrency: {cfg.local_concurrency}')
    print(f'Run-count limit: {cfg.max_total_runs}; per-run wall-time limit: {cfg.max_runtime_hours} h')
    print(f'Configured worker-hour budget per experiment: {cfg.budget_worker_hours:.1f} h')
    print(f'Maximum estimated output/checkpoint storage per experiment: {cfg.max_storage_gib:.1f} GiB')
    used = sum(float(job['used_worker_hours']) for job in db.jobs())
    print(f'Recorded worker time across jobs: {used:.3f} h (provider free-tier quotas are not synchronized)')
    return 0
