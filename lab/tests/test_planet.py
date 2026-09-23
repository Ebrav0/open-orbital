"""One real planetary integration in a temporary directory, outside the observatory library."""
import json
import tempfile
import unittest
from pathlib import Path

from lab.observatory import server


class PlanetWorkerTests(unittest.TestCase):
    def test_short_planetary_run_checkpoints(self):
        cfg = server().normalize({'mode': 'planets', 'duration': 1, 'seed': 1, 'jupiter_mass': 1})
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'config.json').write_text(json.dumps(cfg))
            (folder / 'control.json').write_text(json.dumps({'action': 'run'}))
            import worker
            worker.run(str(folder))
            status = json.loads((folder / 'status.json').read_text())
            self.assertEqual(status['phase'], 'complete')
            self.assertTrue((folder / 'checkpoint.json').is_file())
            pointer = json.loads((folder / 'checkpoint.json').read_text())
            self.assertTrue((folder / pointer['file']).is_file())


if __name__ == '__main__':
    unittest.main()
