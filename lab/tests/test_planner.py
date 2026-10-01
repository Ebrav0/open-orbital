"""Planner tests use a fake OpenRouter client. They do not spend tokens."""
import tempfile
import unittest
from pathlib import Path

from lab.config import load_config
from lab.planner.pipeline import plan_request


class FakeRouter:
    def __init__(self, answers, draft):
        self.answers = answers
        self.draft = draft
        self.chats = 0

    def decisions(self, state, questions):
        return {'answers': self.answers}

    def chat(self, messages):
        self.chats += 1
        return {'choices': [{'message': {'content': self.draft}}]}


def galaxy_answers(present):
    score = 0.99 if present else 0.01
    answers = {
        'mode': {'choice': 'galaxy'},
        'backend': {'choice': 'unspecified'},
    }
    for key in ('n', 'duration', 'dt', 'lifecycle_enabled', 'seed', 'n_galaxies', 'jupiter_mass'):
        answers[key] = {'noul': score}
    return answers


class PlannerTests(unittest.TestCase):
    def test_missing_parameter_asks_and_stores_nothing(self):
        cfg = load_config()
        client = FakeRouter(galaxy_answers(False), '{"questions":["How many particles?"]}')
        with tempfile.TemporaryDirectory() as tmp:
            result = plan_request('run some galaxies', cfg, cfg, Path(tmp), Path(tmp), client=client)
        self.assertFalse(result.ready)
        self.assertTrue(result.questions)
        self.assertEqual(result.specs, [])
        self.assertGreaterEqual(client.chats, 1)

    def test_confirmed_defaults_produce_a_spec(self):
        cfg = load_config()
        draft = json_spec()
        client = FakeRouter(galaxy_answers(True), draft)
        with tempfile.TemporaryDirectory() as tmp:
            result = plan_request(
                'three galaxies, 10000 particles, duration 0.2, dt 0.02, lifecycle off, seed 1',
                cfg, cfg, Path(tmp), Path(tmp), confirm_defaults=True, client=client,
            )
        self.assertTrue(result.ready)
        self.assertEqual(result.specs[0]['n'], 10000)
        self.assertEqual(result.specs[0]['n_galaxies'], 1)
        self.assertIn('scientific_note', result.provenance)
        self.assertIn('model_revision', result.provenance)


def json_spec():
    import json
    return json.dumps({
        'mode': 'galaxy', 'n': 10000, 'duration': 0.2, 'dt': 0.02,
        'lifecycle_enabled': False, 'seed': 1, 'n_galaxies': 1, 'threads': 1,
    })


if __name__ == '__main__':
    unittest.main()
