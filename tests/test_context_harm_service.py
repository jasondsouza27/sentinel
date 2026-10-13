import importlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from sentinel.analysis import analyze
from sentinel.server import create_server


class HarmServiceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module=importlib.import_module('sentinel.context_harm.service')
            self.budget=importlib.import_module('sentinel.optional_work').OptionalModelBudget
        except ModuleNotFoundError: self.fail('optional harm service and shared model budget are missing')

    def payload(self):
        return {'conversation_kind':'linear','conversation_turns':[
            {'turn_id':'a','speaker_id':None,'text':'Earlier calm discussion.'},
            {'turn_id':'b','speaker_id':'local1','text':'I disagree with the proposal.'},
            {'turn_id':'c','speaker_id':'local2','text':'you are stupid'}], 'target_turn_id':'b'}

    def test_structured_target_and_preceding_context_exclude_future_abuse(self):
        result=analyze(self.payload(),harm_model=self.module.HarmService(None))
        self.assertEqual(result['harmful_content']['level'],'low_observed_concern')
        harm=result['harm_assessment']
        self.assertEqual(harm['target_id'],'b')
        self.assertEqual(harm['state'],'unavailable')
        self.assertNotIn('calibrated_probability',harm)
        self.assertEqual(harm['branch'],'context_cpu')
        self.assertTrue(harm['coverage']['language_assumed'])

    def test_malformed_structured_fields_and_ambiguous_target_are_rejected(self):
        for payload in ({'conversation_kind':'linear'},dict(self.payload(),message='another target')):
            with self.assertRaises(ValueError): analyze(payload,harm_model=self.module.HarmService(None))

    def test_non_english_and_legacy_context_only_are_not_assessed(self):
        service=self.module.HarmService(None)
        for payload in ({'message':'Bonjour','language':'fr'},{'conversation':'Earlier discussion only.'}):
            result=analyze(payload,harm_model=service)
            self.assertEqual(result['harm_assessment']['state'],'not_assessed')
            self.assertEqual(result['harm_assessment']['category'],'not_assessed')
            self.assertNotIn('calibrated_probability',result['harm_assessment'])

    def test_research_and_missing_artifacts_are_lightweight_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=self.module.HarmService(Path(tmp)/'missing')
            self.assertEqual(service.health()['state'],'unavailable')
            with patch('sentinel.context_harm.artifacts.inspect_artifact',return_value={
                'schema_version':1,'release_status':'research_only','model_version':'study1'}):
                research=self.module.HarmService(Path(tmp)/'candidate')
                self.assertEqual(research.health()['reason'],'research_only_artifact')
                self.assertNotIn(str(tmp),json.dumps(research.health()))

    def test_shared_budget_rejects_parallel_optional_work_and_releases_on_error(self):
        budget=self.budget(); entered=threading.Event(); release=threading.Event(); outcomes=[]
        def held(): entered.set(); release.wait(2); return 'done'
        thread=threading.Thread(target=lambda:outcomes.append(budget.run('url',held,lambda:'busy')))
        thread.start(); self.assertTrue(entered.wait(1))
        self.assertEqual(budget.run('harm',lambda:'should not run',lambda:'busy'),'busy')
        release.set(); thread.join(2)
        self.assertEqual(outcomes,['done'])
        with self.assertRaises(RuntimeError): budget.run('harm',lambda:(_ for _ in ()).throw(RuntimeError()),lambda:'busy')
        self.assertEqual(budget.run('paired',lambda:'available',lambda:'busy'),'available')

    def test_server_health_always_describes_missing_harm_without_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            server=create_server(port=0,db_path=Path(tmp)/'db.sqlite')
            self.addCleanup(server.server_close)
            self.assertEqual(server.harm_model.health()['reason'],'artifact_not_configured')


if __name__=='__main__': unittest.main()
