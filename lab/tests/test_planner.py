"""Planner contracts use fake OpenRouter responses; no model tokens are spent."""
import json
import unittest

from lab.planner.models import ExperimentPlan

from lab.config import load_config
from lab.planner.pipeline import start_plan, update_plan


def plan(**overrides):
    value = {
        'objective': 'Compare a stable planetary integration',
        'mode': 'planets',
        'duration': 1,
        'aggregate_groups': 1,
        'simulations_per_group': 1,
        'sampling_method': 'grid',
        'sweep': {},
        'fixed_parameters': {},
        'requested_outputs': ['orbital_elements'],
        'user_supplied_fields': ['duration'],
        'planner_inferences': [],
        'unresolved': [],
    }
    value.update(overrides)
    return value


class FakeRouter:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def chat(self, messages, model=None, temperature=0):
        self.calls.append({'model': model, 'messages': messages})
        if not self.answers:
            raise AssertionError('unexpected OpenRouter call')
        return {'choices': [{'message': {'content': json.dumps(self.answers.pop(0))}}]}


class PlannerTests(unittest.TestCase):
    def test_plaintext_to_complete_typed_plan(self):
        client = FakeRouter([plan(), {'fields': {'duration': {'category': 'SUPPLIED'}}}])
        result = start_plan('Run the solar system for one year.', load_config(), client=client)
        self.assertTrue(result.ready, result.error or result.to_dict())
        self.assertEqual(result.plan.mode, 'planets')
        self.assertEqual(result.plan.duration, 1)
        self.assertEqual([call['model'] for call in client.calls], [load_config().luna_model, load_config().jev_model])

    def test_missing_scientific_choices_are_grouped_and_returned(self):
        draft = plan(
            objective='Study two galaxy collision speeds and sizes', mode='galaxy', duration=0.2,
            n_galaxies=2, aggregate_groups=20, simulations_per_group=20,
            fixed_parameters={}, user_supplied_fields=['duration', 'n_galaxies'],
        )
        client = FakeRouter([draft, {'fields': {}}, {'questions': ['What particle resolution and collision parameter ranges should I use?']}])
        result = start_plan('Study two galaxies over 20 groups.', load_config(), client=client)
        self.assertFalse(result.ready)
        self.assertEqual(result.plan.total_runs, 400)
        fields = {item['field'] for item in result.decisions.required_from_user}
        self.assertIn('n', fields)
        self.assertIn('g2_vrel', fields)
        self.assertIn('g2_size_ratio', fields)
        self.assertEqual(len(result.questions), 1)
        self.assertNotIn('dt', fields)  # the current schema default is safe

    def test_answer_updates_plan_then_jev_revalidates(self):
        incomplete = plan(objective='Compare two galaxy encounters', mode='galaxy', duration=0.2,
                          n_galaxies=2, user_supplied_fields=['duration', 'n_galaxies'])
        updated = dict(incomplete)
        updated['fixed_parameters'] = {'n': 10000, 'g2_vrel': 2.0, 'g2_size_ratio': 1.2}
        updated['user_supplied_fields'] += ['n', 'g2_vrel', 'g2_size_ratio']
        client = FakeRouter([updated, {'fields': {}}])
        result = update_plan('Compare encounters', ExperimentPlan.from_dict(incomplete), [], 'Use 10,000 particles, speed 2, size ratio 1.2.', load_config(), client=client)
        self.assertTrue(result.ready, result.error or result.to_dict())
        self.assertEqual(result.plan.fixed_parameters['n'], 10000)
        self.assertEqual([call['model'] for call in client.calls], [load_config().luna_model, load_config().jev_model])

    def test_hard_schema_validation_rejects_jev_approval(self):
        bad = plan(mode='planets', duration=1, fixed_parameters={'n': 10000})
        client = FakeRouter([bad, {'fields': {'n': {'category': 'SUPPLIED'}}}, {'questions': ['That parameter is invalid in planetary mode.'] }])
        result = start_plan('A planetary experiment.', load_config(), client=client)
        self.assertFalse(result.ready)
        self.assertTrue(any(item['field'] == 'n' for item in result.decisions.invalid))

    def test_plan_rejects_boolean_integer_fields_and_fractional_total(self):
        with self.assertRaisesRegex(ValueError, 'aggregate_groups must be an integer'):
            ExperimentPlan.from_dict({'objective': 'test', 'mode': 'planets', 'duration': 1, 'aggregate_groups': True})
        with self.assertRaisesRegex(ValueError, 'total_runs must be an integer'):
            ExperimentPlan.from_dict({'objective': 'test', 'mode': 'planets', 'duration': 1,
                                      'aggregate_groups': 1, 'simulations_per_group': 1, 'total_runs': 1.5})

    def test_continuous_range_defaults_to_recorded_latin_hypercube(self):
        draft = plan(mode='galaxy', duration=0.2, n_galaxies=2, aggregate_groups=8,
                     fixed_parameters={'n': 10000, 'g2_size_ratio': 1.0}, sweep={'g2_vrel': {'min': 0.4, 'max': 4.0}},
                     user_supplied_fields=['duration', 'n_galaxies', 'n'])
        draft.pop('sampling_method')
        client = FakeRouter([draft, {'fields': {}}])
        result = start_plan('Study a continuous encounter speed range.', load_config(), client=client)
        self.assertTrue(result.ready, result.to_dict())
        self.assertEqual(result.plan.sampling_method, 'latin_hypercube')
        self.assertTrue(any('Latin-hypercube' in item for item in result.plan.planner_inferences))


if __name__ == '__main__':
    unittest.main()
