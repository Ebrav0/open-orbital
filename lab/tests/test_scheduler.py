"""Scheduler, lease, and checkpoint pointer tests. The store is in memory."""
import hashlib
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from lab.config import load_config
from lab.coordinator.api import serve_http
from lab.coordinator.db import Database
from lab.observatory import server
from lab.safety import accept_explicit, inclusive_values
from lab.storage.memory import MemoryStore, file_sha256
from lab.worker.agent import _publish
from lab.worker.agent import run_once
from lab.worker.bundle import pack, unpack


def limits():
    return load_config()


def planet_spec():
    return server().normalize({'mode': 'planets', 'duration': 1, 'seed': 1, 'jupiter_mass': 1})


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.db = Database(Path(self.tmp.name) / 'lab.sqlite', clock=self.clock)
        self.store = MemoryStore()
        self.cfg = limits()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_claim_race_allows_one_worker(self):
        self.db.create_job([planet_spec()], 'local', {}, self.cfg.budget_worker_hours)
        results = []

        def claim():
            results.append(self.db.claim('worker', 'local', 'host', self.cfg.lease_seconds, self.cfg.heartbeat_grace_seconds))

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        claims = [item for item in results if item]
        self.assertEqual(len(claims), 1)
        self.assertEqual(sum(item is None for item in results), 1)

    def test_expired_lease_is_claimable_at_the_same_checkpoint(self):
        self.db.create_job([planet_spec()], 'local', {}, self.cfg.budget_worker_hours)
        first = self.db.claim('a', 'local', 'host', 18000, 120)
        published = self._publish(first)
        self.clock.t += 18001
        self.assertEqual(self.db.reap(120), 1)
        second = self.db.claim('b', 'local', 'host', 18000, 120)
        self.assertIsNotNone(second)
        self.assertEqual(second['checkpoint']['sha256'], published['current']['sha256'])
        self.assertEqual(second['shard_id'], first['shard_id'])
        self.assertEqual(second['failures'], 1)

    def test_rejected_hash_does_not_move_the_pointer(self):
        self.db.create_job([planet_spec()], 'local', {}, self.cfg.budget_worker_hours)
        claim = self.db.claim('a', 'local', 'host', 18000, 120)
        path = Path(self.tmp.name) / 'bad.tar.gz'
        path.write_bytes(b'not-the-bytes-we-claim')
        self.store.put('jobs/x/000001.tar.gz', path)
        rejected = self.db.stage_and_verify(
            claim['lease_id'], 'a', 1, '0' * 64, path.stat().st_size, 'jobs/x/000001.tar.gz', self.store,
        )
        self.assertEqual(rejected['status'], 'rejected')
        self.assertIsNone(self.db.current_checkpoint(claim['shard_id']))
        digest = file_sha256(path)
        accepted = self.db.stage_and_verify(
            claim['lease_id'], 'a', 1, digest, path.stat().st_size, 'jobs/x/000001.tar.gz', self.store,
        )
        self.assertEqual(accepted['status'], 'current')
        self.assertEqual(self.db.current_checkpoint(claim['shard_id'])['seq'], 1)

    def test_budget_refuses_the_job(self):
        with self.assertRaises(ValueError):
            self.db.create_job([planet_spec()], 'local', {}, 0.0)

    def test_schema_rejects_six_galaxies(self):
        with self.assertRaises(ValueError):
            accept_explicit({'mode': 'galaxy', 'n_galaxies': 6, 'n': 10000, 'duration': 1}, self.cfg, Path(self.tmp.name))

    def test_matrix_includes_both_endpoints(self):
        values = inclusive_values(0, 20, 20)
        self.assertEqual(len(values), 20)
        self.assertEqual(values[0], 0)
        self.assertEqual(values[-1], 20)
        shards = accept_explicit({
            'mode': 'galaxy', 'n': 10000, 'n_galaxies': 3, 'duration': 0.2, 'dt': 0.02,
            'lifecycle_enabled': False, 'seed': 1, 'threads': 1,
            'matrix': {'parameter': 'g2_impact', 'start': 0, 'stop': 20, 'count': 20},
        }, self.cfg, Path(self.tmp.name))
        self.assertEqual(len(shards), 20)
        self.assertEqual(shards[0]['g2_impact'], 0)
        self.assertAlmostEqual(shards[-1]['g2_impact'], 20)

    def test_disk_floor_overrides_a_valid_spec(self):
        tight = replace(self.cfg, disk_floor_bytes=10**18)
        with self.assertRaises(ValueError):
            accept_explicit({'mode': 'planets', 'duration': 1}, tight, Path(self.tmp.name))

    def test_bundle_round_trip_keeps_the_checkpoint_pointer(self):
        run = Path(self.tmp.name) / 'run'
        run.mkdir()
        (run / 'config.json').write_text('{"mode":"planets"}')
        (run / 'meta.json').write_text(json.dumps({'n': 2, 'bytes_per_particle': 16}))
        (run / 'checkpoint-000000.bin').write_bytes(b'rebound')
        (run / 'frames.bin').write_bytes(b'0123456789abcdef' * 2)
        (run / 'checkpoint.json').write_text(json.dumps({'file': 'checkpoint-000000.bin', 'index': 0, 'initial': {}}))
        (run / 'status.json').write_text('{"phase":"paused"}')
        archive = Path(self.tmp.name) / '1.tar.gz'
        pack(run, archive)
        dest = Path(self.tmp.name) / 'resume'
        unpack(archive, dest)
        self.assertEqual(json.loads((dest / 'control.json').read_text())['action'], 'run')
        self.assertEqual((dest / 'checkpoint-000000.bin').read_bytes(), b'rebound')

    def test_worker_publish_uses_the_store_and_not_a_current_flag(self):
        import os
        spec = planet_spec()
        self.db.create_job([spec], 'local', {}, self.cfg.budget_worker_hours)
        httpd = serve_http(self.db, self.store, 'token', 120, 18000, ['127.0.0.1'], 0)[0]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = httpd.server_address[1]
        try:
            cfg = replace(
                self.cfg,
                worker_token='token',
                scratch=Path(self.tmp.name) / 'scratch',
                drain_margin_seconds=600,
                checkpoint_interval_seconds=3600,
                host='127.0.0.1',
                port=port,
            )
            cfg.scratch.mkdir()

            def popen(cmd, cwd, env):
                run_dir = Path(cmd[-1])
                (run_dir / 'meta.json').write_text(json.dumps({'n': 1, 'bytes_per_particle': 16, 'mode': 'planets'}))
                (run_dir / 'checkpoint-000000.bin').write_bytes(b'state')
                (run_dir / 'frames.bin').write_bytes(b'0123456789abcdef')
                (run_dir / 'checkpoint.json').write_text(json.dumps({'file': 'checkpoint-000000.bin', 'index': 0}))
                (run_dir / 'status.json').write_text(json.dumps({'phase': 'complete'}))
                return _Done()

            os.environ['LAB_URL'] = f'http://127.0.0.1:{port}'
            self.assertEqual(run_once(cfg, self.store, popen=popen, sleep=lambda *_: None), 0)
            job = self.db.jobs()[0]
            self.assertEqual(job['status'], 'complete')
            self.assertEqual(job['shards'][0]['checkpoint']['seq'], 1)
            self.assertEqual(len(self.store.objects), 1)
        finally:
            httpd.shutdown()
            httpd.server_close()
            os.environ.pop('LAB_URL', None)


    def test_planned_handoff_can_cross_many_generations_and_checkpoint_sequence_continues(self):
        self.db.create_job([planet_spec()], 'local', {}, 40.0, max_attempts=3)
        cfg = replace(self.cfg, scratch=Path(self.tmp.name) / 'scratch', checkpoint_retention=3)
        cfg.scratch.mkdir()
        run_dir = Path(self.tmp.name) / 'run'
        run_dir.mkdir()
        (run_dir / 'meta.json').write_text(json.dumps({'n': 1, 'bytes_per_particle': 16, 'mode': 'planets'}))
        (run_dir / 'checkpoint-000000.bin').write_bytes(b'state')
        (run_dir / 'checkpoint.json').write_text(json.dumps({'file': 'checkpoint-000000.bin', 'index': 0}))
        (run_dir / 'status.json').write_text('{"phase":"paused"}')
        current = None
        for generation in range(1, 6):
            claim = self.db.claim(f'worker-{generation}', 'local', 'host', 18000, 120)
            self.assertIsNotNone(claim)
            self.assertEqual(claim['generation'], generation)
            seq = _publish(cfg, self.store, _CheckpointClient(self.db, self.store), claim,
                           claim['worker_id'], run_dir, int((claim.get('checkpoint') or {}).get('seq') or 0))
            self.db.release(claim['lease_id'], claim['worker_id'], 'handoff')
            current = self.db.current_checkpoint(claim['shard_id'])
            self.assertEqual(seq, generation)
        self.assertEqual(current['seq'], 5)
        self.assertEqual(len(self.store.list_versions(f"jobs/{claim['job_id']}/shards/{claim['shard_id']}/checkpoints/")), 3)
        shard = self.db.job(claim['job_id'])['shards'][0]
        self.assertEqual(shard['failures'], 0)
        self.assertEqual(shard['state'], 'pending')

    def test_verified_result_is_required_and_idempotent_for_experiment_completion(self):
        spec = planet_spec()
        manifest = {'source': {'git_commit': '1' * 40}, 'runs': [{'config': spec, 'run_index': 0}]}
        manifest['sha256'] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        self.db.create_experiment('experiment1', 'jobid001', [spec], 'local', manifest,
                                  {'objective': 'planet smoke'}, {'complete': True}, [],
                                  'one short planet run', 2.0, manifest_key='experiments/experiment1/manifest.json',
                                  resource_estimate={'total_worker_hours': 0.01})
        self.db.save_conversation('clarify1', {'original_request': 'test', 'plan': {'mode': 'planets'}, 'dialogue': []}, 'waiting')
        self.db.close()
        self.db = Database(Path(self.tmp.name) / 'lab.sqlite', clock=self.clock)
        self.assertEqual(self.db.get_conversation('clarify1')['state']['original_request'], 'test')
        self.assertEqual(self.db.experiment('experiment1')['manifest']['revision'], 1)
        claim = self.db.claim('worker', 'local', 'host', 18000, 120)
        with self.assertRaisesRegex(ValueError, 'verified final result'):
            self.db.release(claim['lease_id'], 'worker', 'complete')
        result_path = Path(self.tmp.name) / 'final.tar.gz'
        result_path.write_bytes(b'scientific-result')
        digest = file_sha256(result_path)
        key = 'experiments/experiment1/jobs/jobid001/results/final.tar.gz'
        self.store.put(key, result_path)
        accepted = self.db.save_result(claim['lease_id'], 'worker', key, digest, result_path.stat().st_size,
                                       {'status': {'phase': 'complete'}}, self.store)
        duplicate = self.db.save_result(claim['lease_id'], 'worker', key, digest, result_path.stat().st_size,
                                       {'status': {'phase': 'complete'}}, self.store)
        self.assertFalse(accepted['idempotent'])
        self.assertTrue(duplicate['idempotent'])
        self.db.release(claim['lease_id'], 'worker', 'complete')
        self.assertEqual(self.db.experiment('experiment1')['status'], 'complete')
        self.assertEqual(len(self.db.results_for_experiment('experiment1')), 1)

    def test_short_budget_is_reserved_before_parallel_claims(self):
        self.db.create_job([planet_spec(), planet_spec()], 'local', {}, 1.0)
        first = self.db.claim('a', 'local', 'host', 18000, 120)
        self.assertIsNotNone(first)
        second = self.db.claim('b', 'local', 'host', 18000, 120)
        self.assertIsNone(second)
        self.assertEqual(self.db.job(first['job_id'])['status'], 'held')

    def test_database_rejects_manifest_with_a_false_embedded_hash(self):
        with self.assertRaisesRegex(ValueError, 'content does not match'):
            self.db.create_experiment('badexp01', 'badjob01', [planet_spec()], 'local',
                                      {'sha256': 'f' * 64, 'revision': 1, 'source': {}, 'runs': []},
                                      {'objective': 'invalid hash'}, {}, [], 'test', 2.0,
                                      resource_estimate={'total_worker_hours': .01})

    def test_experiment_revision_preserves_history_and_uses_remaining_budget(self):
        spec = planet_spec()
        first = {'revision': 1, 'source': {'git_commit': '1' * 40}, 'runs': [{'config': spec, 'run_index': 0}]}
        first['sha256'] = hashlib.sha256(json.dumps(first, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        first_sha = first['sha256']
        self.db.create_experiment('experiment2', 'jobrev01', [spec], 'local', first,
                                  {'objective': 'planet smoke'}, {'complete': True}, [],
                                  'one short planet run', 2.0, manifest_key='experiments/experiment2/manifests/v1.json',
                                  resource_estimate={'total_worker_hours': .01})
        claim = self.db.claim('revision-worker', 'local', 'host', 18000, 120)
        with self.assertRaisesRegex(ValueError, 'Stop or finish'):
            self.db.validate_experiment_revision('experiment2', .5, 2.0)
        result_path = Path(self.tmp.name) / 'revision-1-result.tar.gz'
        result_path.write_bytes(b'revision-one-result')
        digest = file_sha256(result_path)
        key = 'experiments/experiment2/jobs/jobrev01/results/result.tar.gz'
        self.store.put(key, result_path)
        self.clock.t += 3600
        self.db.save_result(claim['lease_id'], claim['worker_id'], key, digest, result_path.stat().st_size,
                            {'status': {'phase': 'complete'}}, self.store)
        self.db.release(claim['lease_id'], claim['worker_id'], 'complete')
        capacity = self.db.validate_experiment_revision('experiment2', .5, 2.0)
        self.assertEqual(capacity['revision'], 2)
        self.assertAlmostEqual(capacity['remaining_worker_hours'], 1.0)
        with self.assertRaisesRegex(ValueError, 'only 1.00 remain'):
            self.db.validate_experiment_revision('experiment2', 1.5, 2.0)

        second = {'revision': 2, 'source': {'git_commit': '2' * 40}, 'runs': [{'config': spec, 'run_index': 0}]}
        second['sha256'] = hashlib.sha256(json.dumps(second, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        second_sha = second['sha256']
        revised = self.db.create_experiment_revision(
            'experiment2', 'jobrev02', [spec], 'local', second,
            {'objective': 'planet smoke revised'}, {'complete': True}, [{'answer': 'revision request'}],
            'one short planet run, revised', 2.0, manifest_key='experiments/experiment2/manifests/v2.json',
            resource_estimate={'total_worker_hours': .5},
        )
        self.assertEqual(revised['current_revision'], 2)
        self.assertEqual(revised['manifest']['sha256'], second_sha)
        self.assertEqual(self.db.manifest('experiment2', 1)['sha256'], first_sha)
        self.assertEqual(self.db.job('jobrev01')['status'], 'complete')
        self.assertEqual(self.db.job('jobrev02')['budget_worker_hours'], 1.0)
        self.assertEqual(self.db.results_for_experiment('experiment2'), [])
        with self.assertRaisesRegex(ValueError, 'Stop or finish'):
            self.db.validate_experiment_revision('experiment2', .1, 2.0)

    def _publish(self, claim):
        path = Path(self.tmp.name) / 'ok.tar.gz'
        path.write_bytes(b'checkpoint-one')
        key = f"jobs/{claim['job_id']}/shards/{claim['shard_id']}/000001.tar.gz"
        self.store.put(key, path)
        return self.db.stage_and_verify(
            claim['lease_id'], claim['worker_id'], 1, file_sha256(path), path.stat().st_size, key, self.store,
        )


class _CheckpointClient:
    def __init__(self, db, store):
        self.db = db
        self.store = store

    def call(self, method, path, body):
        self.assert_path = path
        return self.db.stage_and_verify(body['lease_id'], body['worker_id'], body['seq'],
                                        body['sha256'], body['size'], body['object_key'], self.store)


class _Done:
    def poll(self):
        return 0

    def terminate(self):
        return None

    def kill(self):
        return None

    def wait(self, timeout=None):
        return 0


if __name__ == '__main__':
    unittest.main()
