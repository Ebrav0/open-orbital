"""Lab command line. `python -m lab` is the entry point."""
import argparse
import json
import sys

from lab.backends.stubs import STUBS
from lab.config import load_config
from lab.coordinator.db import Database
from lab.coordinator.service import serve
from lab.paths import ROOT
from lab.planner.pipeline import plan_request
from lab.safety import accept_explicit, provenance
from lab.specs import read_spec
from lab.storage import build_store
from lab.worker.agent import run_once

IMPLEMENTED = ('local', 'github')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='lab')
    sub = parser.add_subparsers(dest='command', required=True)
    submit = sub.add_parser('submit')
    submit.add_argument('request', nargs='?')
    submit.add_argument('--spec')
    submit.add_argument('--backend', choices=[*IMPLEMENTED, *STUBS])
    submit.add_argument('--confirm-defaults', action='store_true')
    status = sub.add_parser('status')
    status.add_argument('job_id', nargs='?')
    cancel = sub.add_parser('cancel')
    cancel.add_argument('job_id')
    sub.add_parser('workers')
    sub.add_parser('serve')
    worker = sub.add_parser('worker')
    worker.add_argument('--once', action='store_true')
    worker.add_argument('--backend', default='local', choices=IMPLEMENTED)
    args = parser.parse_args(argv)
    try:
        if args.command == 'submit':
            return submit_command(args)
        if args.command == 'status':
            return status_command(args)
        if args.command == 'cancel':
            return cancel_command(args)
        if args.command == 'workers':
            return workers_command()
        if args.command == 'serve':
            cfg = load_config()
            cfg.data.mkdir(parents=True, exist_ok=True)
            serve(cfg, Database(cfg.database), build_store(cfg))
            return 0
        if args.command == 'worker':
            cfg = load_config()
            return run_once(cfg, build_store(cfg), backend=args.backend)
    except (ValueError, KeyError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 2


def submit_command(args):
    cfg = load_config()
    cfg.data.mkdir(parents=True, exist_ok=True)
    if args.backend in STUBS:
        print(f'{args.backend} is not configured', file=sys.stderr)
        return 1
    if args.spec:
        spec = read_spec(args.spec)
        backend = args.backend or spec.pop('backend', None) or cfg.default_backend
        if backend in STUBS:
            print(f'{backend} is not configured', file=sys.stderr)
            return 1
        shards = accept_explicit(spec, cfg, cfg.data)
        document = provenance(ROOT, [])
        request = args.request or ''
    else:
        if not args.request:
            print('Pass a request or --spec', file=sys.stderr)
            return 2
        result = plan_request(args.request, cfg, cfg, cfg.data, ROOT, confirm_defaults=args.confirm_defaults)
        if not result.ready:
            for question in result.questions:
                print(question)
            return 2
        backend = args.backend or result.backend or cfg.default_backend
        if backend in STUBS:
            print(f'{backend} is not configured', file=sys.stderr)
            return 1
        shards = result.specs
        document = result.provenance
        request = args.request
    job_id = Database(cfg.database).create_job(
        shards, backend, document, cfg.budget_worker_hours, request=request, max_attempts=cfg.max_attempts,
    )
    print(job_id)
    return 0


def status_command(args):
    db = Database(load_config().database)
    rows = [db.job(args.job_id)] if args.job_id else db.jobs()
    for job in rows:
        print(f"{job['id']}  {job['status']}  backend={job['backend']}  used={job['used_worker_hours']:.3f}h/{job['budget_worker_hours']}h")
        if job['message']:
            print(f"  {job['message']}")
        for shard in job['shards']:
            checkpoint = shard['checkpoint']
            mark = f"checkpoint seq {checkpoint['seq']} {checkpoint['sha256'][:12]}" if checkpoint else 'no current checkpoint'
            print(f"  shard {shard['idx']} {shard['id']} {shard['state']} attempt {shard['attempt']} {mark}")
    return 0


def cancel_command(args):
    job = Database(load_config().database).cancel(args.job_id)
    print(json.dumps({'id': job['id'], 'status': job['status']}))
    return 0


def workers_command():
    for worker in Database(load_config().database).workers():
        print(f"{worker['id']}  {worker['backend']}  {worker['status']}  {worker['host']}")
    return 0
