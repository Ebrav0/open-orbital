import json
import hashlib
import io
import re
import tempfile
import urllib.error
from unittest.mock import patch
import unittest
from dataclasses import replace
from pathlib import Path

from lab.backends.github import GitHubBackend, PartialDispatchError
from lab.config import load_config
from lab.coordinator.db import Database
from lab.coordinator.service import _scale
from lab.observatory import server


class GitHubBackendTests(unittest.TestCase):
    def test_dispatch_pins_coordinator_and_exact_commit(self):
        calls = []
        cfg = replace(load_config(), github_token='test-token', github_repo='owner/repo',
                      github_workflow='lab-worker.yml', github_ref='main',
                      tailscale_host='http://100.64.0.2:8770', port=8770)
        backend = GitHubBackend(cfg, post=lambda url, body, token: calls.append((url, body, token)))
        started = backend.launch(1, {'coordinator_url': 'http://127.0.0.1:8770', 'git_commit': 'a' * 40})
        self.assertEqual(len(started), 1)
        self.assertTrue(started[0].startswith('dispatch-'))
        self.assertEqual(calls[0][1]['ref'], 'main')
        self.assertEqual(calls[0][1]['inputs']['commit_sha'], 'a' * 40)
        self.assertEqual(calls[0][1]['inputs']['coordinator_url'], 'http://100.64.0.2:8770')
        self.assertEqual(calls[0][2], 'test-token')

    def test_missing_commit_fails_closed_and_partial_dispatch_is_accounted(self):
        cfg = replace(load_config(), github_token='test-token', github_repo='owner/repo',
                      github_workflow='lab-worker.yml', github_ref='main', tailscale_host='100.64.0.2')
        backend = GitHubBackend(cfg, post=lambda *_: None)
        with self.assertRaisesRegex(Exception, 'exact 40-character'):
            backend.launch(1, {'coordinator_url': 'http://100.64.0.2:8770'})
        calls = []
        def partial(*_):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('temporary API error')
        backend = GitHubBackend(cfg, post=partial)
        with self.assertRaises(PartialDispatchError) as caught:
            backend.launch(3, {'coordinator_url': 'http://100.64.0.2:8770', 'git_commit': 'b' * 40})
        self.assertEqual(len(caught.exception.started), 1)
        self.assertTrue(caught.exception.started[0].startswith('dispatch-'))

    def test_worker_workflow_pins_actions_and_checks_commit_before_secrets(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github' / 'workflows' / 'lab-worker.yml').read_text()
        action_shas = re.findall(r'^\s*(?:-\s*)?uses:\s+[^@]+@([0-9a-f]+)(?:\s+#.*)?$', workflow, re.MULTILINE)
        self.assertEqual(len(action_shas), 3)
        self.assertTrue(all(len(sha) == 40 for sha in action_shas))
        verify = workflow.index('name: Verify pinned source revision')
        tailnet = workflow.index('name: Join the tailnet')
        secrets = workflow.index('name: Write the Drive config')
        self.assertLess(verify, tailnet)
        self.assertLess(verify, secrets)
        self.assertIn('git merge-base --is-ancestor', workflow)

    def test_dispatch_ids_do_not_collide_after_backend_restart(self):
        cfg = replace(load_config(), github_token='test-token', github_repo='owner/repo',
                      github_workflow='lab-worker.yml', github_ref='main', tailscale_host='100.64.0.2')
        first = GitHubBackend(cfg, post=lambda *_: None).launch(1, {'git_commit': 'a' * 40})
        second = GitHubBackend(cfg, post=lambda *_: None).launch(1, {'git_commit': 'a' * 40})
        self.assertNotEqual(first[0], second[0])

    def test_http_dispatch_error_is_reported_without_crashing(self):
        cfg = replace(load_config(), github_token='test-token', github_repo='owner/repo',
                      github_workflow='lab-worker.yml', github_ref='main', tailscale_host='100.64.0.2')
        error = urllib.error.HTTPError('https://api.github.com', 403, 'forbidden', {}, io.BytesIO(b'permission denied'))
        try:
            with patch('lab.backends.github.urllib.request.urlopen', side_effect=error):
                backend = GitHubBackend(cfg)
                with self.assertRaisesRegex(Exception, r'GitHub dispatch failed \(403\)'):
                    backend.launch(1, {'git_commit': 'c' * 40, 'coordinator_url': 'http://100.64.0.2:8770'})
        finally:
            error.close()

    def test_scaler_dispatches_commit_group_and_tracks_partial_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / 'lab.sqlite')
            spec = server().normalize({'mode': 'planets', 'duration': 1, 'seed': 2})
            manifest = {'source': {'git_commit': 'd' * 40}, 'runs': [{'config': spec}]}
            manifest['sha256'] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            db.create_experiment('exp12345', 'job12345', [spec, spec], 'github', manifest,
                                 {'objective': 'scale'}, {'complete': True}, [], 'test', 40,
                                 resource_estimate={'total_worker_hours': .01})
            cfg = replace(load_config(), port=8770, tailscale_host='100.64.0.2')
            calls = []
            def partial(url, body, token):
                calls.append(body)
                if len(calls) == 2:
                    raise RuntimeError('GitHub API unavailable')
            backend = GitHubBackend(replace(cfg, github_token='token', github_repo='owner/repo'), post=partial)
            _scale(cfg, db, 'github', backend, 20)
            self.assertEqual(calls[0]['inputs']['commit_sha'], 'd' * 40)
            self.assertEqual(db.dispatching_count('github', 900), 1)
            self.assertTrue(any(event['kind'] == 'launch_failed' for event in db.events()))
            db.close()


if __name__ == '__main__':
    unittest.main()
