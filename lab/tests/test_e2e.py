"""One short real local Open Orbital integration; all generated files live in TemporaryDirectory."""
import hashlib
import json
import os
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from lab.config import load_config
from lab.coordinator.api import serve_http
from lab.coordinator.db import Database
from lab.paths import ROOT
from lab.planner.manifest import build_manifest, expand_plan
from lab.planner.pipeline import start_plan
from lab.preflight import estimate_resources, run_validation_case
from lab.storage.directory import DirectoryStore
from lab.storage.memory import file_sha256
from lab.worker.agent import run_once


class FakeRouter:
    def __init__(self, draft):
        self.draft = draft
        self.calls = []

    def chat(self, messages, model=None, temperature=0):
        self.calls.append(model)
        value = self.draft if len(self.calls) == 1 else {'fields': {}}
        return {'choices': [{'message': {'content': json.dumps(value)}}]}


class LocalExperimentEndToEndTests(unittest.TestCase):
    def test_plaintext_to_manifest_to_real_worker_to_verified_result(self):
        with tempfile.TemporaryDirectory(prefix='lab-e2e-') as tmp:
            root = Path(tmp)
            cfg = replace(load_config(), database=root / 'lab.sqlite', data=root / 'data',
                          scratch=root / 'scratch', worker_token='e2e-token', host='127.0.0.1',
                          port=0, storage_backend='directory', budget_worker_hours=2.0)
            cfg.data.mkdir()
            plan_data = {
                'objective': 'Check a one-year planetary integration and its saved orbital elements',
                'mode': 'planets', 'duration': 1, 'aggregate_groups': 1, 'simulations_per_group': 1,
                'sampling_method': 'grid', 'sweep': {}, 'fixed_parameters': {'seed': 314159, 'jupiter_mass': 1},
                'requested_outputs': ['orbital_elements'], 'user_supplied_fields': ['duration'],
                'planner_inferences': [], 'unresolved': [],
            }
            router = FakeRouter(plan_data)
            result = start_plan('Integrate the planetary system for one year.', cfg, client=router)
            self.assertTrue(result.ready, result.error or result.to_dict())
            runs = expand_plan(result.plan, cfg, cfg.data)
            resources = estimate_resources(runs, cfg, backend='local', benchmark_dir=root / 'no-benchmarks')
            self.assertEqual(run_validation_case(runs[0]['config'], cfg=cfg, root=ROOT)['status'], 'passed')

            experiment_id, job_id = 'e2e000000001', 'e2j000000001'
            manifest = build_manifest(experiment_id, job_id, 'Integrate the planetary system for one year.',
                                      [], result.plan, runs, resources, cfg, ROOT, result.decisions)
            manifest_key = f"experiments/{experiment_id}/manifests/manifest-v1-{manifest['sha256']}.json"
            store = DirectoryStore(root / 'objects')
            manifest_path = root / 'manifest.json'
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False))
            blob_sha = file_sha256(manifest_path)
            store.put(manifest_key, manifest_path)
            self.assertTrue(store.verify(manifest_key, blob_sha, manifest_path.stat().st_size))

            db = Database(cfg.database)
            exp = db.create_experiment(experiment_id, job_id, [row['config'] for row in runs], 'local',
                                       manifest, result.plan.to_dict(), result.decisions.to_dict(), [],
                                       'Integrate the planetary system for one year.', cfg.budget_worker_hours,
                                       cfg.max_attempts, manifest_key=manifest_key, resource_estimate=resources)
            self.assertEqual(exp['run_count'], 1)

            httpd = serve_http(db, store, cfg.worker_token, cfg.heartbeat_grace_seconds,
                               cfg.lease_seconds, ['127.0.0.1'], 0,
                               drain_margin_seconds=cfg.drain_margin_seconds)[0]
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            cfg = replace(cfg, port=httpd.server_address[1])
            try:
                with patch.dict(os.environ, {'LAB_URL': f'http://127.0.0.1:{cfg.port}'}, clear=False):
                    self.assertEqual(run_once(cfg, store, backend='local', worker_id='e2e-worker'), 0)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=5)

            exp = db.experiment(experiment_id)
            self.assertEqual(exp['status'], 'complete')
            self.assertEqual(exp['counts'].get('complete'), 1)
            results = db.results_for_experiment(experiment_id)
            self.assertEqual(len(results), 1)
            self.assertTrue(store.verify(results[0]['object_key'], results[0]['sha256'], results[0]['size']))
            self.assertEqual(results[0]['metadata']['status']['phase'], 'complete')
            self.assertEqual(results[0]['metadata']['run_metadata']['seed'], 314159)
            self.assertTrue(results[0]['metadata']['logs'])
            self.assertEqual(exp['job']['shards'][0]['checkpoint']['seq'], 1)
            self.assertEqual(len(router.calls), 2)
            db.close()


if __name__ == '__main__':
    unittest.main()
