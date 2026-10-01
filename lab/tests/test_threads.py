import dataclasses
import unittest

from lab.config import load_config
from lab.observatory import server
from lab.safety import _clamp_threads


class ThreadChoiceTests(unittest.TestCase):
    def clamp(self, requested, cap):
        limits = dataclasses.replace(load_config(), max_threads=cap)
        cfg = server().normalize({'mode': 'galaxy', 'n': 10000, 'threads': requested, 'duration': 1})
        return _clamp_threads(cfg, limits)['threads']

    def test_schema_offers_12_and_keeps_14(self):
        self.assertEqual(server().SCHEMA['threads'][1], [1, 4, 8, 10, 12, 14])

    def test_12_cpu_node_uses_all_12(self):
        self.assertEqual(self.clamp(14, 12), 12)
        self.assertEqual(self.clamp(12, 12), 12)

    def test_14_cpu_host_keeps_14(self):
        self.assertEqual(self.clamp(14, 14), 14)

    def test_smaller_caps_are_unchanged(self):
        self.assertEqual(self.clamp(14, 4), 4)
        self.assertEqual(self.clamp(14, 10), 10)
        self.assertEqual(self.clamp(8, 12), 8)


if __name__ == '__main__':
    unittest.main()
