"""Drive store command shape, without calling rclone or Google."""
import tempfile
import unittest
from pathlib import Path

from lab.storage.directory import DirectoryStore
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
