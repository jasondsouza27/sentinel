"""Comparable neural candidates using deterministic software backends only."""
from dataclasses import replace
import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sentinel.context_harm.contracts import CandidateRef, HarmCase, HarmError, ModelText, ScoreBatch
from test_context_harm_neural_pilot import FixtureTokenizer,row


class NeuralCandidateTests(unittest.TestCase):
    def module(self):
        module=importlib.import_module('sentinel.context_harm.neural')
        self.assertTrue(callable(getattr(module,'fit_neural_candidates',None)),'neural fitting entry point is missing')
        self.assertTrue(callable(getattr(module,'checked_candidate',None)),'checked neural artifacts are missing')
        return module

    def test_unavailable_pilot_disables_full_fit_without_creating_candidates(self):
        module=self.module()
        from sentinel.context_harm.contracts import FrozenStudy
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with patch.object(module,'run_worker',side_effect=AssertionError('unavailable pilot starts fit')):
                candidates=module.fit_neural_candidates(FrozenStudy(root/'absent',{}),{'status':'neural_unavailable','reason':'protected_cohort_unavailable'},
                              Path(__import__('sys').executable),root/'models',{})
            self.assertEqual(candidates,())
            self.assertFalse((root/'models').exists())
            self.assertEqual(json.loads((root/'models.neural-unavailable.json').read_text())['reason'],'protected_cohort_unavailable')

    def test_both_branches_keep_identical_compatible_case_ids(self):
        module=self.module()
        rows=(row('first',252),row('too-long',253),row('last',4))
        with patch.object(module,'_load_tokenizer',return_value=FixtureTokenizer()):
            compatible,_=module.token_compatible_cases(rows,Path('.'))
        target=tuple(value.case_id for value in compatible if module.encode_model_text(value.model_input,FixtureTokenizer(),contextual=False)['supported'])
        context=tuple(value.case_id for value in compatible if module.encode_model_text(value.model_input,FixtureTokenizer(),contextual=True)['supported'])
        self.assertEqual(target,('first','last'))
        self.assertEqual(target,context)

    def test_epoch_checkpoints_are_selected_on_validation_and_keep_the_best_only(self):
        module=self.module()
        training=(replace(row('train0',2),label=0),replace(row('train1',2),label=1))
        validation=(replace(row('validation0',2),label=0),replace(row('validation1',2),label=1))
        retained=[]
        epoch={'value':0}
        def fit_epoch(rows):
            self.assertEqual({value.case_id for value in rows},{'train0','train1'})
            epoch['value']+=1
            return {'mean_loss':1/epoch['value'],'optimizer_steps':1}
        def validate(rows):
            self.assertEqual(tuple(value.case_id for value in rows),('validation0','validation1'))
            return ([.1,.9],[.1,.8],[.7,.6])[epoch['value']-1]
        result=module.fit_epoch_loop(training,validation,fit_epoch,validate,retained.append,'context_neural-lr2e-5')
        self.assertEqual(result['selected_epoch'],1)
        self.assertEqual(result['selection_partition'],'validation')
        self.assertEqual(retained,[1])
        self.assertEqual(len(result['epoch_reports']),3)

    def test_nonfinite_training_step_fails_before_checkpoint_publication(self):
        module=self.module()
        rows=(replace(row('a',2),label=0),replace(row('b',2),label=1))
        retained=[]
        with self.assertRaisesRegex(HarmError,'neural_nonfinite_training'):
            module.fit_epoch_loop(rows,rows,lambda _: {'mean_loss':float('nan'),'optimizer_steps':1},lambda _: [.1,.9],retained.append,'target_neural-lr2e-5')
        self.assertEqual(retained,[])

    def test_lost_target_token_is_rejected_before_tensor_construction(self):
        module=self.module()
        tokenizer=FixtureTokenizer()
        def lost(target,context=None):
            return [101]+target[:-1]+[102]+([] if context is None else context+[102])
        tokenizer.build_inputs_with_special_tokens=lost
        with self.assertRaisesRegex(HarmError,'neural_special_token_contract_changed'):
            module.encode_model_text(row('target',252).model_input,tokenizer,contextual=True)

    def test_subset_class_or_component_failure_never_relaxes_production_gates(self):
        module=self.module()
        from sentinel.context_harm.contracts import PRODUCTION_CRITERIA
        parts={name:(replace(row(name+'0',2),label=0),replace(row(name+'1',2),label=1)) for name in ('train','validation','calibration')}
        report=module.compatible_cohort_manifest(parts,{value.case_id:value.case_id for values in parts.values() for value in values})
        self.assertEqual(report['status'],'neural_unavailable')
        self.assertIn('train_class_support',report['unavailable_reasons'])
        self.assertIn('validation_component_support',report['unavailable_reasons'])
        self.assertEqual(report['criteria']['train_per_class'],PRODUCTION_CRITERIA.train_per_class)

    def test_fixed_grid_is_two_learning_rates_per_branch(self):
        grid=self.module().neural_candidate_grid()
        self.assertEqual(len(grid),4)
        self.assertEqual(len({value['config_id'] for value in grid}),4)
        self.assertEqual({(value['kind'],value['learning_rate']) for value in grid},
                         {(kind,rate) for kind in ('target_neural','context_neural') for rate in (2e-5,5e-5)})

    def test_existing_score_entry_routes_neural_references_to_separate_boundary(self):
        module=self.module()
        from sentinel.context_harm import cpu
        candidate=CandidateRef('target_neural','target_neural-lr2e-5',Path('unused'),{})
        expected=ScoreBatch(('a',),(.25,),(True,),{'status':'ok'})
        with patch.object(module,'score_neural',return_value=expected):
            result=cpu.score_candidate(candidate,(row('a',2),),{'python':'separate-python.exe'})
        self.assertEqual(result.case_ids,('a',))
        self.assertEqual(result.scores,(.25,))


if __name__=='__main__':
    unittest.main()

class NeuralArtifactTests(unittest.TestCase):
    def setUp(self):
        self.module=importlib.import_module('sentinel.context_harm.neural')
        self.assertTrue(callable(getattr(self.module,'fit_neural_candidates',None)),'paired neural fit orchestration is missing')
        self.assertTrue(callable(getattr(self.module,'checked_candidate',None)),'checked neural artifacts are missing')
        self.temporary=tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup); self.root=Path(self.temporary.name)
        from context_harm_neural_fixtures import ControlledWorkers,fixture_sources,ready_study
        self.study=ready_study(self.root); self.sources=fixture_sources(self.root)
        self.workers=ControlledWorkers(self.module,self.study,self.sources)
        self.addCleanup(patch.stopall)
        patch('sentinel.context_harm.neural_sources.verify_sources',side_effect=lambda value:value).start()
        patch.object(self.module,'run_worker',side_effect=self.workers).start()
        self.pilot=self.module.run_neural_pilot(self.study,Path(__import__('sys').executable),self.sources,self.root/'pilot.json')
        self.assertEqual(self.pilot['status'],'ready',self.pilot)

    def train(self):
        from sentinel.context_harm.source import default_settings
        return self.module.fit_neural_candidates(self.study,self.pilot,Path(__import__('sys').executable),self.root/'candidates',default_settings())

    def test_four_candidates_bind_one_cohort_and_validation_checkpoint_selection(self):
        candidates=self.train()
        self.assertEqual(len(candidates),4)
        self.assertEqual(len({value.fit_record['compatible_cohort_sha256'] for value in candidates}),1)
        for candidate in candidates:
            self.assertEqual(candidate.fit_record['selection_partition'],'validation')
            self.assertEqual(candidate.fit_record['selected_epoch'],1)
            self.assertEqual(candidate.fit_record['tokenizer_base_hashes']['revision'],'12040accade4e8a0f71eabdb258fecc2e7e948be')
            self.assertEqual(candidate.fit_record['synthetic'],True)
            self.assertTrue((candidate.directory/'model.safetensors').exists())
            self.assertTrue((candidate.directory/'fit-record.json').exists())
            self.module.checked_candidate(candidate)
        self.assertTrue((self.root/'candidates/manifest.json').exists())

    def test_changed_pilot_or_source_binding_prevents_every_full_fit(self):
        changed=copy.deepcopy(self.pilot); changed['source_manifest_sha256']='0'*64
        candidates=self.module.fit_neural_candidates(self.study,changed,Path(__import__('sys').executable),self.root/'changed',{})
        self.assertEqual(candidates,())
        self.assertFalse(any(value['operation']=='neural_fit' for value in self.workers.requests))
        self.assertFalse((self.root/'changed').exists())
        self.assertEqual(json.loads((self.root/'changed.neural-unavailable.json').read_text())['reason'],'neural_pilot_changed')

    def test_checkpoint_hash_is_checked_before_a_neural_score_worker_runs(self):
        candidate=self.train()[0]
        path=candidate.directory/'model.safetensors'; path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaisesRegex(HarmError,'neural_model_member_changed'):
            self.module.score_neural(candidate,(row('score',2),),{'python':__import__('sys').executable})
        self.assertFalse(any(value['operation']=='neural_score' for value in self.workers.requests))

    def test_neural_scoring_sends_feature_only_payloads_and_preserves_order(self):
        candidate=self.train()[0]
        rows=(replace(row('second',3),metadata={'SECRET':'audit-only'}),row('first',2))
        result=self.module.score_neural(candidate,rows,{'python':__import__('sys').executable})
        self.assertEqual(result.case_ids,('second','first'))
        self.assertEqual(result.scores,(.25,.25))
        request=[value for value in self.workers.requests if value['operation']=='neural_score'][0]
        self.assertEqual([set(value) for value in request['rows']],[{'case_id','model_input'}]*2)
        self.assertNotIn('SECRET',json.dumps(request))
        self.assertNotIn('label',json.dumps(request))

    def test_gpu_limit_or_worker_failure_discards_every_candidate_stage(self):
        from sentinel.context_harm.contracts import WorkerRecord
        workers=self.workers
        calls=[]
        def fail_second(command,limits,**kwargs):
            value=workers(command,limits,**kwargs)
            if workers.requests[-1]['operation']=='neural_fit':
                calls.append(1)
                if len(calls)==2:
                    return WorkerRecord('unavailable','worker_deadline_exceeded',{}, {})
            return value
        with patch.object(self.module,'run_worker',side_effect=fail_second):
            self.assertEqual(self.train(),())
        self.assertEqual(len(calls),2)
        self.assertFalse((self.root/'candidates').exists())
        self.assertFalse(any(self.root.glob('.neural-stage-*')))
        report=json.loads((self.root/'candidates.neural-unavailable.json').read_text())
        self.assertEqual(report['reason'],'worker_deadline_exceeded')

class NeuralIntegrityEdgeTests(unittest.TestCase):
    module=NeuralCandidateTests.module
    def test_same_length_target_token_substitution_is_rejected(self):
        module=self.module(); tokenizer=FixtureTokenizer()
        def substituted(target,context=None):
            return [101]+[9999]+target[1:]+[102]+([] if context is None else context+[102])
        tokenizer.build_inputs_with_special_tokens=substituted
        with self.assertRaisesRegex(HarmError,'neural_special_token_contract_changed'):
            module.encode_model_text(row('target',252).model_input,tokenizer,contextual=True)

    def test_context_turn_omissions_follow_the_actual_token_suffix(self):
        module=self.module()
        result=module.encode_model_text(row('case',250,('c1','c2','c3','c4')).model_input,FixtureTokenizer(),contextual=True)
        self.assertIn('context_turns_available',result,'context turn coverage is missing')
        self.assertEqual(result['context_turns_available'],4)
        self.assertEqual(result['context_turns_used'],2)
        self.assertEqual(result['context_turns_omitted'],2)


class NeuralResourceEdgeTests(unittest.TestCase):
    setUp=NeuralArtifactTests.setUp
    train=NeuralArtifactTests.train

    def test_pilot_excess_gpu_memory_and_slow_forecast_disable_full_fit(self):
        from sentinel.context_harm.contracts import WorkerRecord
        for field,value in (('peak_reserved_bytes',3435973837),('forecast_seconds',1801)):
            with self.subTest(field=field):
                def excessive(command,limits,**kwargs):
                    outcome=self.workers(command,limits,**kwargs)
                    if self.workers.requests[-1]['operation']=='neural_pilot':
                        return WorkerRecord(outcome.status,outcome.reason,outcome.measurements,{**outcome.output,field:value})
                    return outcome
                with patch.object(self.module,'run_worker',side_effect=excessive):
                    result=self.module.run_neural_pilot(self.study,Path(__import__('sys').executable),self.sources,self.root/(field+'.json'))
                self.assertEqual(result['status'],'neural_unavailable')
                self.assertFalse(result['may_fit_full_candidate'])

    def test_pilot_worker_timeout_stays_unavailable(self):
        from sentinel.context_harm.contracts import WorkerRecord
        def timeout(command,limits,**kwargs):
            outcome=self.workers(command,limits,**kwargs)
            if self.workers.requests[-1]['operation']=='neural_pilot':
                return WorkerRecord('unavailable','worker_deadline_exceeded',{}, {})
            return outcome
        with patch.object(self.module,'run_worker',side_effect=timeout):
            result=self.module.run_neural_pilot(self.study,Path(__import__('sys').executable),self.sources,self.root/'timeout.json')
        self.assertEqual((result['status'],result['reason']),('neural_unavailable','worker_deadline_exceeded'))
        self.assertFalse(result['may_fit_full_candidate'])

    def test_forged_ready_cohort_with_insufficient_classes_does_not_fit(self):
        from sentinel.context_harm.integrity import write_json
        pilot=copy.deepcopy(self.pilot)
        pilot['compatible_cohort']['partitions']['train']['class_counts']['1']=1
        write_json(Path(pilot['report_path']),pilot)
        result=self.module.fit_neural_candidates(self.study,pilot,Path(__import__('sys').executable),self.root/'invalid-cohort',{})
        self.assertEqual(result,())
        report=json.loads((self.root/'invalid-cohort.neural-unavailable.json').read_text())
        self.assertEqual(report['reason'],'neural_pilot_changed')

    def test_score_report_exposes_aggregate_tokens_without_per_case_vectors(self):
        candidate=self.train()[0]
        rows=(row('first',2),row('second',3))
        result=self.module.score_neural(candidate,rows,{'python':__import__('sys').executable})
        self.assertIn('token_coverage',result.runtime,'aggregate score token coverage is missing')
        aggregate=result.runtime['token_coverage']
        self.assertEqual(aggregate['total_cases'],2)
        self.assertEqual(aggregate['supported_cases'],2)
        self.assertEqual(aggregate['target_tokens_used'],5)
        self.assertEqual(aggregate['context_tokens_used'],0)
        self.assertNotIn('input_ids',json.dumps(aggregate))
        self.assertNotIn('first',json.dumps(aggregate))

class NeuralGpuScoreTests(unittest.TestCase):
    setUp=NeuralArtifactTests.setUp
    train=NeuralArtifactTests.train

    def test_scoring_reports_gpu_peaks_and_rejects_over_limit_measurements(self):
        from sentinel.context_harm.contracts import WorkerRecord
        candidate=self.train()[0]
        def memory(command,limits,**kwargs):
            outcome=self.workers(command,limits,**kwargs)
            if self.workers.requests[-1]['operation']=='neural_score':
                return WorkerRecord('ok',None,outcome.measurements,{**outcome.output,'peak_allocated_bytes':1024,'peak_reserved_bytes':2048})
            return outcome
        with patch.object(self.module,'run_worker',side_effect=memory):
            result=self.module.score_neural(candidate,(row('case',2),),{'python':__import__('sys').executable})
        self.assertIn('peak_allocated_bytes',result.runtime,'GPU score measurements are missing')
        self.assertEqual(result.runtime['peak_allocated_bytes'],1024)
        self.assertEqual(result.runtime['peak_reserved_bytes'],2048)
        def excessive(command,limits,**kwargs):
            outcome=memory(command,limits,**kwargs)
            if self.workers.requests[-1]['operation']=='neural_score':
                return WorkerRecord('ok',None,outcome.measurements,{**outcome.output,'peak_reserved_bytes':3435973837})
            return outcome
        with patch.object(self.module,'run_worker',side_effect=excessive):
            with self.assertRaisesRegex(HarmError,'neural_gpu_budget_exceeded'):
                self.module.score_neural(candidate,(row('case',2),),{'python':__import__('sys').executable})
