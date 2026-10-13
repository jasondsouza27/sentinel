"""Invented cases exercise integration, never real detector quality."""
import importlib
import json
import tempfile
import unittest
from pathlib import Path

from context_harm_fixtures import cad_row
from sentinel.context_harm.contracts import HarmCriteria, HarmError, SourceRelease
from sentinel.context_harm.integrity import canonical_sha256, sha256
from sentinel.context_harm.source import coalesce_rows, default_settings


class HarmWorkflowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.evaluation=importlib.import_module('sentinel.context_harm.evaluation')
        except ModuleNotFoundError:
            self.fail('the full directed-abuse research workflow is not integrated')

    def test_synthetic_admission_to_single_use_evaluation_and_unavailable_live_service(self):
        from sentinel.context_harm.conversation import build_cases,parse_submission
        from sentinel.context_harm.challenge import init_challenge,challenge_reservation
        from sentinel.context_harm.protocol import _freeze_cohort,load_development,verify_study
        from sentinel.context_harm.cpu import fit_cpu_candidates,score_candidate
        from sentinel.context_harm.selection import select_candidates,fit_calibration
        from sentinel.context_harm.artifacts import export_artifact,inspect_artifact
        from sentinel.context_harm.service import HarmService
        project=Path(__file__).resolve().parents[1]
        protected=['requirements-ml-win-py311.lock.txt','requirements-url-data-win-py311.lock.txt',
            'configs/url-ml-v3.json','output/research/url-ml-v3/evaluation.json',
            'data/curation/intake.csv']
        before={name:sha256(project/name) if (project/name).is_file() else None for name in protected}
        rows=[]
        for i in range(55):
            thread=f'toy-thread-{i}'; root=f'toy-root-{i}'
            split='test' if i>=50 else 'train'
            rows.append(cad_row(root,thread=thread,parent='NA',root='NA',order='0',
                text=f'Previous discussion {i}.',split='exclude_bot',author=f'context-owner-{i}'))
            for label in (0,1):
                rows.append(cad_row(f'toy-target-{i}-{label}',thread=thread,parent=root,
                    root='NA',order=f'0,{label}',author=f'target-owner-{i}',split=split,
                    text=f'you are stupid hostile sample{i}' if label else f'calm friendly discussion sample{i}',
                    label='PersonDirectedAbuse' if label else 'Neutral'))
        source=SourceRelease(coalesce_rows(rows),{'synthetic_fixture':True,'fixture_sha256':canonical_sha256(rows)})
        settings=default_settings(); cohort=build_cases(source,settings)
        self.assertEqual(len(cohort.primary),110)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); status=init_challenge(root)
            self.assertFalse(status['claim_ready'])
            challenge=challenge_reservation(root)
            study=_freeze_cohort(root,cohort,settings,challenge,
                criteria=HarmCriteria(2,1,1,1,1,1,.7),synthetic=True)
            self.assertTrue(verify_study(study)['synthetic'])
            parts=load_development(study)
            refs=fit_cpu_candidates(study,root/'candidates',settings)
            labels={row.case_id:row.label for row in parts['validation']}
            batches={ref.config_id:score_candidate(ref,parts['validation']) for ref in refs}
            selections=select_candidates(refs,batches,labels)
            components=json.loads((study.path/'components.json').read_text())['development']
            cal_labels={row.case_id:row.label for row in parts['calibration']}
            calibrators={kind:fit_calibration(selection,score_candidate(selection.candidate,parts['calibration']),
                cal_labels,components) for kind,selection in selections.items()}
            self.assertTrue(all(value.status=='unavailable' for value in calibrators.values()))
            artifact=root/'artifact'
            export_artifact(selections,calibrators,study,artifact)
            self.assertTrue(inspect_artifact(artifact,research=True)['synthetic'])
            with self.assertRaises(HarmError): inspect_artifact(artifact)
            report=self.evaluation.evaluate_final(study,artifact,root/'public')
            self.assertEqual(report['comparison_case_hashes']['target'],report['comparison_case_hashes']['context'])
            self.assertEqual(report['bootstrap']['replicates'],1000)
            public=json.dumps(report)
            self.assertNotIn('toy-target-',public)
            self.assertNotIn('hostile sample',public)
            self.assertNotIn('target-owner-',public)
            self.assertTrue((root/'final-access.json').is_file())
            with self.assertRaises(HarmError):
                self.evaluation.evaluate_final(study,artifact,root/'public')
            live=HarmService(artifact).assess(parse_submission({'message':'A plain target.'}))
            self.assertEqual(live['state'],'unavailable')
            self.assertNotIn('calibrated_probability',live)
        after={name:sha256(project/name) if (project/name).is_file() else None for name in protected}
        self.assertEqual(before,after)

    def test_production_failure_publishes_no_frozen_data_or_models(self):
        from sentinel.context_harm.protocol import freeze_study
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises(HarmError): freeze_study(root,default_settings())
            self.assertFalse((root/'v1').exists())
            self.assertFalse((root/'candidates').exists())


if __name__=='__main__': unittest.main()
