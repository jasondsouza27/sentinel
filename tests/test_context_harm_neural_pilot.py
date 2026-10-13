"""Token boundaries and bounded preflight/pilot policy without a GPU dependency."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sentinel.context_harm.contracts import FrozenStudy, HarmCase, HarmError, ModelText, WorkerRecord


class FixtureTokenizer:
    pad_token_id, cls_token_id, sep_token_id = 0, 101, 102
    def __init__(self, pair_special=3):
        self.pair_special = pair_special
    def num_special_tokens_to_add(self, pair=False):
        return self.pair_special if pair else 2
    def encode(self, text, add_special_tokens=False):
        result=[]
        for word in text.split():
            if word.startswith('t') and word[1:].isdigit(): result.append(1000+int(word[1:]))
            elif word.startswith('c') and word[1:].isdigit(): result.append(2000+int(word[1:]))
            elif word=='[URL]': result.append(10)
            elif word=='[USER]': result.append(11)
            else: result.append(9000+sum(map(ord,word)))
        return result
    def build_inputs_with_special_tokens(self, target, context=None):
        return [101]+list(target)+[102]+([] if context is None else list(context)+[102])


def row(identity, tokens, context=('c1 c2 c3 c4',)):
    return HarmCase(identity,ModelText(' '.join('t'+str(i) for i in range(tokens)),context),('before',),'thread',0,{})


class NeuralPilotTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)

    def module(self):
        try:
            return importlib.import_module('sentinel.context_harm.neural')
        except ModuleNotFoundError:
            self.fail('bounded neural pilot policy is missing')

    def test_252_target_tokens_are_preserved_and_253_abstains_for_both_branches(self):
        module=self.module()
        with patch.object(module,'_load_tokenizer',return_value=FixtureTokenizer()):
            compatible,report=module.token_compatible_cases((row('supported',252),row('too-long',253)),self.root)
        self.assertEqual(tuple(r.case_id for r in compatible),('supported',))
        self.assertEqual(report['case_coverage']['supported']['supported'],True)
        self.assertEqual(report['case_coverage']['too-long']['supported'],False)
        self.assertEqual(report['case_coverage']['supported']['target_tokens'],252)
        self.assertEqual(report['case_coverage']['supported']['context_tokens_used'],1)

    def test_unexpected_special_token_layout_is_rejected(self):
        module=self.module()
        with patch.object(module,'_load_tokenizer',return_value=FixtureTokenizer(pair_special=4)):
            with self.assertRaisesRegex(HarmError,'neural_special_token_contract_changed'):
                module.token_compatible_cases((row('case',20),),self.root)

    def test_recent_context_suffix_is_kept_without_truncating_target(self):
        module=self.module()
        result=module.encode_model_text(row('case',250).model_input,FixtureTokenizer(),contextual=True)
        self.assertEqual(result['input_ids'][1:251],list(range(1000,1250)))
        self.assertEqual(result['input_ids'][252:255],[2002,2003,2004])
        self.assertEqual(result['target_tokens_used'],250)
        self.assertEqual(result['context_tokens_used'],3)
        self.assertTrue(result['context_truncated'])
        self.assertEqual(len(result['input_ids']),256)

    def test_encoder_features_use_masked_target_and_have_no_audit_fields(self):
        module=self.module()
        result=module.encode_model_text(ModelText('https://private.example/name u/privateuser',('c1',)),FixtureTokenizer(),contextual=False)
        self.assertEqual(result['input_ids'][:4],[101,10,11,102])
        self.assertNotIn('privateuser',json.dumps(result))

    def test_missing_neural_python_produces_durable_unavailable_report(self):
        module=self.module()
        result=module.probe_neural_runtime(self.root/'missing-python.exe',self.root/'probe.json')
        self.assertEqual(result['status'],'neural_unavailable')
        self.assertFalse(result['may_fit_full_candidate'])
        self.assertTrue((self.root/'probe.json').exists())

    def test_cuda_forward_backward_or_optimizer_failure_never_claims_runtime_ready(self):
        module=self.module()
        for failed in ('forward','backward','optimizer'):
            with self.subTest(failed_stage=failed):
                smoke={stage:stage!=failed for stage in ('forward','backward','optimizer')}
                worker=WorkerRecord('ok',None,{'rss_peak_bytes':100}, {'status':'ready','reason':'cuda_'+failed+'_failed','cuda_smoke':smoke})
                with patch.object(module,'run_worker',return_value=worker):
                    result=module.probe_neural_runtime(Path(__import__('sys').executable),self.root/(failed+'-probe.json'))
                self.assertEqual((result['status'],result['reason']),('neural_unavailable','cuda_'+failed+'_failed'))
                self.assertFalse(result['may_fit_full_candidate'])

    def test_unavailable_cohort_cannot_start_or_publish_pilot_success(self):
        module=self.module()
        study=FrozenStudy(self.root/'absent',{})
        with patch.object(module,'run_worker',side_effect=AssertionError('unready cohort starts pilot')):
            result=module.run_neural_pilot(study,Path(__import__('sys').executable),{},self.root/'pilot.json')
        self.assertEqual((result['status'],result['reason']),('neural_unavailable','protected_cohort_unavailable'))
        self.assertFalse(result['may_fit_full_candidate'])
        self.assertTrue((self.root/'pilot.json').exists())


if __name__=='__main__':
    unittest.main()

class NeuralWorkerPolicyTests(unittest.TestCase):
    def module(self):
        value=importlib.import_module('sentinel.context_harm.neural')
        self.assertTrue(callable(getattr(value,'worker_operation',None)),'neural worker operations are missing')
        return value

    def test_cpu_inventory_cannot_claim_a_supported_cuda_runtime(self):
        value=self.module().worker_operation({'operation':'neural_probe'})
        self.assertEqual((value['status'],value['reason']),('neural_unavailable','neural_runtime_inventory_mismatch'))
        self.assertFalse(value['may_fit_full_candidate'])

    def test_balanced_pilot_uses_only_training_cases_and_seed_42(self):
        module=self.module()
        rows=tuple(HarmCase('train-'+str(i),ModelText('t1',('c1',)),(),str(i),i%2,{}) for i in range(60))
        chosen=module.balanced_pilot_rows(rows)
        self.assertEqual(len(chosen),32)
        self.assertEqual(sum(value.label for value in chosen),16)
        self.assertEqual(tuple(value.case_id for value in chosen),tuple(value.case_id for value in module.balanced_pilot_rows(rows)))
        self.assertTrue({value.case_id for value in chosen}.issubset({value.case_id for value in rows}))

    def test_conservative_forecast_includes_loading_three_epochs_and_validation(self):
        module=self.module()
        # 100 optimizer steps per epoch + 50 validation batches per epoch,
        # measured two seconds/step, 1.5 safety multiplier, ten seconds loading.
        self.assertEqual(module.forecast_candidate_seconds(10,40,20,800,100),1360)
        self.assertGreater(module.forecast_candidate_seconds(10,80,20,800,100),1800)

    def test_incomplete_runtime_record_cannot_become_a_ready_probe(self):
        module=importlib.import_module('sentinel.context_harm.neural')
        worker=WorkerRecord('ok',None,{}, {'status':'ready','cuda_smoke':{'forward':True,'backward':True,'optimizer':True}})
        with tempfile.TemporaryDirectory() as temporary, patch.object(module,'run_worker',return_value=worker):
            value=module.probe_neural_runtime(Path(__import__('sys').executable),Path(temporary)/'probe.json')
        self.assertEqual(value['status'],'neural_unavailable')
        self.assertEqual(value['reason'],'neural_runtime_record_invalid')

