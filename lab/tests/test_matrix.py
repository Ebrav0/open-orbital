import tempfile
import unittest
from pathlib import Path

from lab.config import load_config
from lab.planner.manifest import build_manifest, expand_plan
from lab.planner.models import DecisionReport, ExperimentPlan


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = load_config()

    def tearDown(self):
        self.tmp.cleanup()

    def galaxy_plan(self):
        return ExperimentPlan.from_dict({
            'objective': 'Study three-galaxy collision outcomes over speed and size',
            'mode': 'galaxy', 'duration': 0.2, 'n_galaxies': 3,
            'aggregate_groups': 20, 'simulations_per_group': 20,
            'sampling_method': 'latin_hypercube',
            'sweep': {
                'g2_vrel': {'min': 0.4, 'max': 4.0},
                'g3_vrel': {'min': 0.4, 'max': 4.0},
                'g2_size_ratio': {'min': 0.3, 'max': 2.0},
                'g3_size_ratio': {'min': 0.3, 'max': 2.0},
            },
            'fixed_parameters': {'n': 10000, 'seed': 7, 'dt': 0.02, 'lifecycle_enabled': False},
            'user_supplied_fields': ['duration', 'n_galaxies', 'n'],
        })

    def test_20_groups_times_20_replicates_make_400_seeded_jobs(self):
        plan = self.galaxy_plan()
        runs = expand_plan(plan, self.cfg, self.root)
        self.assertEqual(len(runs), 400)
        self.assertEqual(len({run['seed'] for run in runs}), 400)
        self.assertEqual({run['group_index'] for run in runs}, set(range(20)))
        self.assertEqual({run['replicate_index'] for run in runs}, set(range(20)))
        for run in runs:
            self.assertEqual(run['config']['n_galaxies'], 3)
            self.assertEqual(set(run['sweep_values']), {'g2_vrel', 'g3_vrel', 'g2_size_ratio', 'g3_size_ratio'})
        again = expand_plan(plan, self.cfg, self.root)
        self.assertEqual([r['sweep_values'] for r in runs], [r['sweep_values'] for r in again])
        self.assertEqual([r['seed'] for r in runs], [r['seed'] for r in again])

    def test_grid_size_must_equal_declared_group_count(self):
        plan = ExperimentPlan.from_dict({
            'objective': 'grid', 'mode': 'galaxy', 'duration': 0.2, 'n_galaxies': 2,
            'aggregate_groups': 3, 'simulations_per_group': 1, 'sampling_method': 'grid',
            'sweep': {'g2_vrel': {'values': [1.0, 2.0]}},
            'fixed_parameters': {'n': 10000, 'g2_size_ratio': 1.0, 'seed': 3},
        })
        with self.assertRaisesRegex(ValueError, 'combinations'):
            expand_plan(plan, self.cfg, self.root)

    def test_manifest_hash_is_content_addressed_and_keeps_dirty_source_marker(self):
        plan = ExperimentPlan.from_dict({
            'objective': 'short planetary smoke', 'mode': 'planets', 'duration': 1,
            'fixed_parameters': {'seed': 99}, 'user_supplied_fields': ['duration'],
        })
        runs = expand_plan(plan, self.cfg, self.root)
        report = DecisionReport()
        manifest = build_manifest('exp', 'job', 'one year planet smoke', [], plan, runs,
                                  {'total_worker_hours': 0.01}, self.cfg, Path(__file__).parents[2], report)
        self.assertEqual(len(manifest['sha256']), 64)
        self.assertEqual(manifest['sampling']['total_runs'], 1)
        self.assertEqual(manifest['runs'][0]['seed'], 99)
        self.assertIn('git_commit', manifest['source'])
        self.assertIn('source_tree_sha256', manifest['source'])


if __name__ == '__main__':
    unittest.main()
