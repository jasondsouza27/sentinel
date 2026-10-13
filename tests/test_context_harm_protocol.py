import importlib
import json
import tempfile
import unittest
from pathlib import Path

from sentinel.context_harm.contracts import (CadUtterance, CaseCohort, HarmCase,
    HarmCriteria, HarmError, ModelText, SourceRelease)
from sentinel.context_harm.source import default_settings


def case(identity, split='train', author=None, label=0, text=None, thread=None):
    thread=thread or identity
    record=CadUtterance(identity,thread,None,None,author,('0',),text or identity,
        split,('PersonDirectedAbuse',) if label else ('Neutral',),(),True,True,{})
    target=HarmCase(identity,ModelText(text or identity,('Earlier '+identity,)),
        ('context-'+identity,),thread,label,{'source_split':split})
    return record,target


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        try: self.module=importlib.import_module('sentinel.context_harm.protocol')
        except ModuleNotFoundError: self.fail('protected context harm protocol is missing')
        self.criteria=HarmCriteria(2,1,1,1,1,1,.7)

    def cohort(self, entries, extra=()):
        records,cases=zip(*entries)
        return CaseCohort(tuple(cases),(),SourceRelease(tuple(records)+tuple(extra),{}),{})

    def empty_challenge(self):
        return {'schema_version':1,'case_count':0,'status':'pending',
                'cad_case_ids':[],'duplicate_keys':[],'case_ids':[]}

    def test_test_author_in_excluded_context_row_purges_whole_thread(self):
        entries=[case('protected','test',label=1),case('protected0','test'),
            case('development',author='held-author'),case('other',thread='development'),case('retained')]
        hidden=CadUtterance('hidden','protected',None,None,'held-author',('0',),
                           'Unavailable context','exclude_lang',(),(),False,False,{})
        audit=self.module.audit_cohort(self.cohort(entries,(hidden,)),self.empty_challenge(),self.criteria)
        self.assertEqual(audit['purges']['test_author']['threads'],1)
        self.assertEqual(audit['purges']['test_author']['cases'],2)

    def test_masked_input_duplicates_purge_whole_development_thread(self):
        entries=[case('protected','test',text='Read https://evil.example/a @anna'),
                 case('copied',text='Read https://other.example/b @bob')]
        # Same used context makes the complete model inputs identical after masking.
        first,second=[entry[1] for entry in entries]
        first=HarmCase(first.case_id,ModelText(first.model_input.target,('A shared context.',)),(),first.thread_id,0,{})
        second=HarmCase(second.case_id,ModelText(second.model_input.target,('A shared context.',)),(),second.thread_id,0,{})
        cohort=CaseCohort((first,second),(),SourceRelease(tuple(e[0] for e in entries),{}),{})
        audit=self.module.audit_cohort(cohort,self.empty_challenge(),self.criteria)
        self.assertEqual(audit['purges']['test_duplicate']['threads'],1)

    def test_missing_authors_do_not_join_unrelated_threads(self):
        entries=[case('short'+str(i),author=None) for i in range(20)]
        cohort=self.cohort(entries)
        components=self.module.connected_components(cohort.primary,cohort.source)
        self.assertEqual(len(set(components.values())),20)

    def test_known_authors_and_near_duplicate_targets_join_whole_threads(self):
        a=case('a',author='same'); b=case('b',author='same')
        text='alpha beta gamma delta epsilon zeta eta theta '*20
        c=case('c',text=text+' changed'); d=case('d',text=text+' again')
        from sentinel.context_harm.text import simhash_target
        self.assertEqual((simhash_target(c[1].model_input.target)^simhash_target(d[1].model_input.target)).bit_count(),3)
        cohort=self.cohort([a,b,c,d])
        components=self.module.connected_components(cohort.primary,cohort.source)
        self.assertEqual(components['a'],components['b'])
        self.assertEqual(components['c'],components['d'])

    def test_allocation_is_reproducible_and_never_cuts_components(self):
        entries=[]
        for i in range(40):
            entries.extend([case(f'x{i}n',thread=f'g{i}'),case(f'x{i}p',thread=f'g{i}',label=1)])
        cohort=self.cohort(entries)
        comp=self.module.connected_components(cohort.primary,cohort.source)
        parts=self.module.allocate_development(cohort.primary,comp,self.criteria)
        self.assertEqual(set(parts),{'train','validation','calibration'})
        again=self.module.allocate_development(cohort.primary,comp,self.criteria)
        self.assertEqual(parts,again)
        owners={}
        for name,rows in parts.items():
            for row in rows:
                self.assertIn(owners.setdefault(comp[row.case_id],name),(name,))

    def test_class_loss_and_oversized_component_are_honest_failures(self):
        cohort=self.cohort([case('small')])
        with self.assertRaises(HarmError):
            self.module.allocate_development(cohort.primary,{'small':'one'},self.criteria)
        cohort=self.cohort([case(str(i),author='one',label=i%2) for i in range(20)])
        with self.assertRaisesRegex(HarmError,'component'):
            self.module.allocate_development(cohort.primary,
                self.module.connected_components(cohort.primary,cohort.source),self.criteria)

    def test_failed_allocation_reports_actual_partition_support_without_changing_split(self):
        entries=[]
        for i in range(40):
            for label in (0,1): entries.append(case(f'support{i}{label}',label=label,thread=f'support{i}'))
        entries.extend([case('test0','test'),case('test1','test',label=1)])
        audit=self.module.audit_cohort(self.cohort(entries),self.empty_challenge(),
                                      HarmCriteria(1000,1,1,1,1,1,.7))
        self.assertEqual(audit['status'],'unavailable')
        self.assertIn('failed_allocation',audit)
        self.assertEqual(sum(row['cases'] for row in audit['failed_allocation'].values()),80)
        self.assertLess(audit['failed_allocation']['train']['class_counts']['1'],1000)

    def test_challenge_cannot_own_protected_test_cases(self):
        cohort=self.cohort([case('protected','test')])
        challenge=self.empty_challenge(); challenge['cad_case_ids']=['protected']
        with self.assertRaises(HarmError): self.module.audit_cohort(cohort,challenge,self.criteria)

    def test_production_freeze_requires_prior_challenge_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises(HarmError): self.module.freeze_study(root,default_settings())
            self.assertFalse((root/'v1/manifest.json').exists())

    def test_synthetic_freeze_is_immutable_and_development_loader_has_no_test(self):
        entries=[]
        for i in range(40):
            for label in (0,1): entries.append(case(f'd{i}{label}',label=label,thread=f'd{i}'))
        entries.extend([case('tn','test'),case('tp','test',label=1)])
        cohort=self.cohort(entries)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            study=self.module._freeze_cohort(root,cohort,default_settings(),self.empty_challenge(),
                                           criteria=self.criteria,synthetic=True)
            parts=self.module.load_development(study)
            self.assertEqual(set(parts),{'train','validation','calibration'})
            with self.assertRaises(HarmError):
                self.module._freeze_cohort(root,cohort,default_settings(),self.empty_challenge(),
                    criteria=self.criteria,synthetic=True)
            path=study.path/'train.jsonl'
            with path.open('a',encoding='utf-8') as f: f.write('{}\n')
            with self.assertRaises(HarmError): self.module.load_development(study)


if __name__=='__main__': unittest.main()
