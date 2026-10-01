"""Scheduler, lease, and checkpoint pointer tests. The store is in memory."""
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

    def _publish(self, claim):
        path = Path(self.tmp.name) / 'ok.tar.gz'
        path.write_bytes(b'checkpoint-one')
        key = f"jobs/{claim['job_id']}/shards/{claim['shard_id']}/000001.tar.gz"
        self.store.put(key, path)
        return self.db.stage_and_verify(
            claim['lease_id'], claim['worker_id'], 1, file_sha256(path), path.stat().st_size, key, self.store,
        )


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
