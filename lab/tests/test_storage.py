"""Drive store command shape, without calling rclone or Google."""
import tempfile
import unittest
from pathlib import Path

from lab.storage.directory import DirectoryStore
from lab.storage.memory import MemoryStore
from lab.storage.base import StorageError
from lab.storage.drive import RcloneDriveStore


class Completed:
    def __init__(self):
        self.stdout = ''
        self.returncode = 0


class DriveCommandTests(unittest.TestCase):
    def test_put_targets_the_open_orbital_compute_folder(self):
        calls = []

        def runner(args):
            calls.append(args)
            return Completed()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'rclone.conf'
            config.write_text('[labdrive]\ntype = drive\n')
            archive = root / '000001.tar.gz'
            archive.write_bytes(b'abc')
            store = RcloneDriveStore(config, 'labdrive', 'Open Orbital Compute', root / 'scratch', runner=runner)
            store.put('jobs/job/shards/shard/000001.tar.gz', archive)
        joined = ' '.join(calls[0])
        self.assertIn('copyto', calls[0])
        self.assertIn('labdrive:Open Orbital Compute/jobs/job/shards/shard/000001.tar.gz', joined)
        self.assertIn('--drive-chunk-size', calls[0])


    def test_checkpoint_retention_keeps_latest_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = DirectoryStore(root / 'objects')
            for seq in range(1, 6):
                path = root / f'{seq}.tar.gz'
                path.write_bytes(f'checkpoint-{seq}'.encode())
                store.put(f'experiments/e/jobs/j/checkpoints/s/{seq:06d}.tar.gz', path)
            removed = store.prune('experiments/e/jobs/j/checkpoints/s/', 3)
            self.assertEqual(removed, [
                'experiments/e/jobs/j/checkpoints/s/000001.tar.gz',
                'experiments/e/jobs/j/checkpoints/s/000002.tar.gz',
            ])
            self.assertEqual(len(store.list_versions('experiments/e/jobs/j/checkpoints/s/')), 3)
            self.assertTrue(store.verify('experiments/e/jobs/j/checkpoints/s/000005.tar.gz',
                                         __import__('hashlib').sha256(b'checkpoint-5').hexdigest(), len(b'checkpoint-5')))

    def test_rclone_upload_failure_is_reported_without_success(self):
        def fail(_args):
            raise StorageError('simulated Drive transfer failure')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'rclone.conf'
            config.write_text('[labdrive]\ntype = drive\n')
            archive = root / 'checkpoint.tar.gz'
            archive.write_bytes(b'payload')
            store = RcloneDriveStore(config, 'labdrive', 'Open Orbital Compute', root / 'scratch', runner=fail)
            with self.assertRaisesRegex(StorageError, 'simulated Drive transfer failure'):
                store.put('experiments/e/jobs/j/checkpoints/s/000001.tar.gz', archive)

    def test_memory_store_prune_is_scoped_to_prefix(self):
        store = MemoryStore()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for key in ('jobs/a/1', 'jobs/a/2', 'jobs/b/1'):
                path = root / key.rsplit('/', 1)[-1]
                path.write_bytes(key.encode())
                store.put(key, path)
        removed = store.prune('jobs/a/', 1)
        self.assertEqual(removed, ['jobs/a/1'])
        self.assertEqual(store.list_versions('jobs/a/'), ['jobs/a/2'])
        self.assertEqual(store.list_versions('jobs/b/'), ['jobs/b/1'])

    def test_directory_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / '000001.tar.gz'
            archive.write_bytes(b'payload')
            store = DirectoryStore(root / 'objects')
            store.put('jobs/a/000001.tar.gz', archive)
            self.assertTrue(store.verify('jobs/a/000001.tar.gz', __import__('hashlib').sha256(b'payload').hexdigest(), len(b'payload')))
            self.assertFalse(store.verify('jobs/a/000001.tar.gz', '0' * 64, len(b'payload')))
            dest = root / 'out.tar.gz'
            store.fetch('jobs/a/000001.tar.gz', dest)
            self.assertEqual(dest.read_bytes(), b'payload')


if __name__ == '__main__':
    unittest.main()
