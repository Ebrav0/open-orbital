import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from lab import cli
from lab.config import load_config
from lab.planner.models import DecisionReport, ExperimentPlan
from lab.planner.pipeline import PlanningResult


class _ConversationDB:
    def get_conversation(self, conversation_id):
        return {'state': {'plan': {'objective': 'test'}}}


class CliResearchTests(unittest.TestCase):
    def test_ready_noninteractive_plan_skips_prompt_and_keeps_schedule_choice(self):
        db = _ConversationDB()
        cfg = object()
        plan = ExperimentPlan(objective='test', mode='planets')
        result = PlanningResult(plan=plan, decisions=DecisionReport())
        with patch('lab.cli._schedule_plan', return_value=0) as schedule:
            self.assertEqual(cli._continue_interaction(db, cfg, 'conversation-1', result, 'local', False, True), 0)
        schedule.assert_called_once_with(db, cfg, 'conversation-1', {'plan': {'objective': 'test'}}, 'local', False, True)

    def test_github_prerequisites_fail_before_scheduling_when_credentials_are_missing(self):
        cfg = replace(load_config(), github_token='', worker_token='', tailscale_host='',
                      storage_backend='drive', rclone_config=Path('/definitely/missing/rclone.conf'))
        with self.assertRaisesRegex(ValueError, 'LAB_GITHUB_TOKEN'):
            cli._require_github_prerequisites(cfg, Path('/tmp'))

    def test_result_summary_is_compact_and_tracks_missing_values(self):
        manifest = {'runs': [
            {'sweep_values': {'speed': 1.0}},
            {'sweep_values': {'speed': 2.0}},
            {'sweep_values': {'speed': 2.0}},
        ]}
        rows = [
            {'metadata': {'status': {'phase': 'complete'}, 'diagnostics_summary': {'last': {'energy_change': 2.0}}}},
            {'metadata': {'status': {'phase': 'complete'}, 'diagnostics_summary': {'last': {'energy_change': 4.0}}}},
            {'metadata': {'status': {'phase': 'complete'}, 'diagnostics_summary': {'last': {}}}},
        ]
        summary = cli._summarize_results(rows, manifest)
        self.assertEqual(summary['sweep_summary']['speed']['unique_count'], 2)
        self.assertEqual(summary['result_summary']['verified_runs'], 3)
        metric = summary['result_summary']['diagnostics']['energy_change']
        self.assertEqual(metric['count'], 2)
        self.assertEqual(metric['missing'], 1)
        self.assertEqual(metric['mean'], 3.0)


if __name__ == '__main__':
    unittest.main()
