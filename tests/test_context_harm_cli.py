"""Production CLI gates and explicit synthetic offline prediction contracts."""
import contextlib
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from context_harm_fixtures import cad_row
from test_context_harm_access import make_study
from test_context_harm_artifacts import make_selections
from sentinel.context_harm.contracts import SourceRelease
from sentinel.context_harm.integrity import read_json


def tiny_source():
    from sentinel.context_harm.source import coalesce_rows
    rows = []
    for split, count in (('train', 24), ('test', 12)):
        for index in range(count):
            thread = f'{split}-thread-{index}'
            earlier = f'{split}-earlier-{index}'
            rows.append(cad_row(earlier, thread=thread, root='NA', split=split,
                author=f'{split}-prior-author-{index}', order='0',
                text=f'Earlier invented {split} context {index}.'))
            rows.append(cad_row(f'{split}-target-{index}', thread=thread, root='NA',
                parent=earlier, split=split, author=f'{split}-target-author-{index}', order='1',
                text=f'Invented statement {split} {index}.',
                label='PersonDirectedAbuse' if index % 2 else 'Neutral'))
    return SourceRelease(coalesce_rows(rows), {'provenance': 'invented_fixture'})


class CliTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module('sentinel.context_harm.cli')
        except ModuleNotFoundError as error:
            if error.name == 'sentinel.context_harm.cli':
                self.fail('Explicit harm reproduction CLI is missing')
            raise
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def invoke(self, *arguments):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
            code = self.api.main(list(arguments))
        return code, json.loads(stream.getvalue())

    def test_empty_challenge_stays_pending_and_has_no_fabricated_labels(self):
        code, report = self.invoke('challenge-init', '--root', str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(report['case_count'], 0)
        self.assertEqual(report['status'], 'pending')
        self.assertEqual((self.root / 'challenge/intake.jsonl').read_text(encoding='utf-8'), '')
        code, report = self.invoke('challenge-audit', '--root', str(self.root))
        self.assertEqual(code, 0)
        self.assertFalse(report['claim_ready'])

    def test_audit_persists_failed_production_gates_as_aggregate_without_model_scoring(self):
        self.invoke('challenge-init', '--root', str(self.root))
        from sentinel.context_harm import source, cpu
        with patch.object(source, 'load_source', return_value=tiny_source()), \
             patch.object(cpu, 'score_candidate', side_effect=AssertionError('must not score')):
            code, report = self.invoke('audit', '--root', str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(report['status'], 'unavailable')
        self.assertTrue(report['unavailable_reasons'])
        self.assertEqual(report['development']['cases'], 24)
        self.assertEqual(report, read_json(self.root / 'runs/audit.json'))
        self.assertNotIn('train-target-0', json.dumps(report))
        self.assertNotIn('Invented statement', json.dumps(report))
        self.assertFalse((self.root / 'final-access.json').exists())
        with patch.object(source, 'load_source', return_value=tiny_source()):
            code, repeated = self.invoke('audit', '--root', str(self.root))
        self.assertEqual(code, 2)
        self.assertEqual(repeated['reason'], 'stage_output_exists')

    def test_failed_freeze_and_train_create_unavailable_records_without_model_publication(self):
        self.invoke('challenge-init', '--root', str(self.root))
        from sentinel.context_harm import source, cpu
        with patch.object(source, 'load_source', return_value=tiny_source()):
            self.invoke('audit', '--root', str(self.root))
            code, report = self.invoke('freeze', '--root', str(self.root))
        self.assertEqual(code, 2)
        self.assertEqual(report['status'], 'unavailable')
        self.assertEqual(read_json(self.root / 'runs/freeze-unavailable.json')['status'], 'unavailable')
        self.assertFalse((self.root / 'v1').exists())
        models = self.root / 'models'
        with patch.object(cpu, 'fit_cpu_candidates', side_effect=AssertionError('must not fit')):
            code, report = self.invoke('train-cpu', '--root', str(self.root), '--models', str(models))
        self.assertEqual(code, 2)
        self.assertEqual(report['status'], 'unavailable')
        self.assertTrue((self.root / 'runs/train-cpu-unavailable.json').exists())
        self.assertFalse((models / 'cpu').exists())

    def test_missing_neural_prerequisites_record_neural_unavailable_without_pilot(self):
        python = self.root / 'absent-neural-python.exe'
        code, report = self.invoke('neural-pilot', '--root', str(self.root),
                                   '--models', str(self.root / 'models'), '--neural-python', str(python))
        self.assertEqual(code, 2)
        self.assertEqual(report['status'], 'neural_unavailable')
        self.assertFalse(report['may_fit_full_candidate'])
        self.assertTrue((self.root / 'runs/neural-pilot-unavailable.json').exists())

    def test_predict_requires_explicit_research_and_returns_no_raw_submission(self):
        from sentinel.context_harm.artifacts import export_artifact
        study = make_study(self.root / 'study')
        selected, calibrators = make_selections(self.root / 'fitted', study)
        artifact = self.root / 'artifact'
        export_artifact(selected, calibrators, study, artifact)
        submitted = self.root / 'input.json'
        submitted.write_text(json.dumps({'message': 'you are stupid', 'language': 'en'}), encoding='utf-8')
        code, denied = self.invoke('predict', '--artifact', str(artifact), '--input-json', str(submitted))
        self.assertEqual(code, 2)
        self.assertEqual(denied['reason'], 'research_artifact_live_refused')
        code, result = self.invoke('predict', '--artifact', str(artifact), '--input-json', str(submitted), '--research')
        self.assertEqual(code, 0)
        self.assertEqual(result['category'], 'review')
        self.assertTrue(result['research_only'])
        self.assertNotIn('calibrated_probability', result)
        self.assertNotIn('you are stupid', json.dumps(result))

    def test_training_selection_uses_only_development_and_keeps_sparse_calibration_unavailable(self):
        study = make_study(self.root / 'study')
        selected, _ = make_selections(self.root / 'fitted', study)
        from sentinel.context_harm import protocol
        original = protocol.read_cases
        def read(path):
            if Path(path).name in ('test.jsonl', 'diagnostics.jsonl'):
                raise AssertionError('training must not load protected rows')
            return original(path)
        with patch.object(protocol, 'read_cases', side_effect=read):
            choices, calibrators = self.api.select_and_calibrate(
                study, tuple(value.candidate for value in selected.values()))
        self.assertEqual(set(choices), {'target_cpu', 'context_cpu'})
        self.assertEqual(choices['target_cpu'].validation_report['recall'], 1.0)
        self.assertEqual(calibrators['target_cpu'].status, 'unavailable')
        self.assertEqual(calibrators['target_cpu'].report['reason'], 'insufficient_calibration_support')
        self.assertFalse((study.path.parent / 'final-access.json').exists())
    def test_production_cli_does_not_accept_seed_criteria_or_grid_overrides(self):
        for option in ('--seed', '--criteria', '--c-grid'):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()), \
                 self.assertRaises(SystemExit) as error:
                self.api.main(['train-cpu', '--root', str(self.root), '--models', str(self.root / 'models'),
                               option, '7'])
            self.assertEqual(error.exception.code, 2)

    def test_failures_hide_private_exception_text_and_leave_fixed_reason_record(self):
        self.invoke('challenge-init', '--root', str(self.root))
        from sentinel.context_harm import source
        with patch.object(source, 'load_source', side_effect=OSError('PRIVATE RAW SUBMISSION')):
            code, report = self.invoke('audit', '--root', str(self.root))
        self.assertEqual(code, 2)
        self.assertEqual(report['status'], 'unavailable')
        self.assertNotIn('PRIVATE RAW SUBMISSION', json.dumps(report))
        saved = read_json(self.root / 'runs/audit-unavailable.json')
        self.assertNotIn('PRIVATE RAW SUBMISSION', json.dumps(saved))


if __name__ == '__main__':
    unittest.main()

