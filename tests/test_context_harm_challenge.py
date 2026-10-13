import csv
import importlib
import json
import tempfile
import unittest
from pathlib import Path

from sentinel.context_harm.contracts import HarmError


class ChallengeTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module('sentinel.context_harm.challenge')
        except ModuleNotFoundError:
            self.fail('context harm challenge workflow is not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.module.init_challenge(self.root)

    def case(self, **changes):
        row = dict(case_id='review1', conversation_kind='linear',
            conversation_turns=[dict(turn_id='a', speaker_id=None, text='Please discuss the proposal.'),
                                dict(turn_id='b', speaker_id=None, text='I disagree with that proposal.')],
            target_turn_id='b', source_ref='permissioned-interview:01',
            permission_basis='voluntary participant permission', verification_ref='consent-record:01',
            collected_on='2026-10-13', family='disagreement')
        row.update(changes)
        return row

    def intake(self, rows):
        (self.root/'challenge/intake.jsonl').write_text(
            ''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')

    def prepare(self):
        self.intake([self.case()])
        return self.module.prepare_challenge_reviews(self.root)

    def reviews(self, left='0', right='0', reviewer2='human-b', adjudicate=None):
        packet = self.root/'challenge/review-packet'
        for filename, reviewer, label in [('reviewer-a.csv','human-a',left),('reviewer-b.csv',reviewer2,right)]:
            path = packet/filename
            with path.open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                row.update(reviewer_id=reviewer, task_label=label, family='disagreement', rationale='Reviewed context.')
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                writer.writeheader(); writer.writerows(rows)
        if adjudicate is not None:
            (packet/'adjudication.json').write_text(json.dumps({
                'review1':dict(reviewer_id='human-c', task_label=adjudicate, family='disagreement', rationale='Resolved independent disagreement.')}),encoding='utf-8')

    def test_init_remains_empty_pending_and_reservation_is_immutable(self):
        self.assertEqual((self.root/'challenge/intake.jsonl').read_text(), '')
        self.assertEqual(self.module.audit_challenge(self.root)['status'], 'pending')
        self.assertFalse(self.module.audit_challenge(self.root)['claim_ready'])
        receipt=self.module.challenge_reservation(self.root)
        self.assertEqual(receipt['case_count'],0)
        self.assertEqual(receipt,self.module.challenge_reservation(self.root))
        self.intake([self.case()])
        with self.assertRaises(HarmError): self.module.challenge_reservation(self.root)

    def test_permission_and_provenance_are_required(self):
        for field in ('source_ref','permission_basis','verification_ref','collected_on'):
            self.intake([self.case(**{field:''})])
            with self.subTest(field=field), self.assertRaises(HarmError):
                self.module.prepare_challenge_reviews(self.root)

    def test_predictions_and_gold_labels_cannot_enter_intake(self):
        self.intake([self.case(prediction=1)])
        with self.assertRaises(HarmError): self.module.prepare_challenge_reviews(self.root)
        self.intake([self.case(label=0)])
        with self.assertRaises(HarmError): self.module.prepare_challenge_reviews(self.root)

    def test_packet_is_blinded_and_cannot_be_overwritten(self):
        self.prepare()
        raw=(self.root/'challenge/review-packet/packet.json').read_text()
        self.assertNotIn('permissioned-interview',raw)
        self.assertNotIn('family',raw)
        with self.assertRaises(HarmError): self.module.prepare_challenge_reviews(self.root)

    def test_duplicate_case_ids_and_invalid_conversation_are_rejected(self):
        self.intake([self.case(),self.case()])
        with self.assertRaises(HarmError): self.module.prepare_challenge_reviews(self.root)
        self.intake([self.case(target_turn_id='absent')])
        with self.assertRaises(HarmError): self.module.prepare_challenge_reviews(self.root)

    def test_two_distinct_humans_are_required(self):
        self.prepare(); self.reviews(reviewer2='human-a')
        with self.assertRaises(HarmError): self.module.finalize_challenge_reviews(self.root)

    def test_disagreement_requires_recorded_independent_adjudication(self):
        self.prepare(); self.reviews(left='0',right='1')
        with self.assertRaises(HarmError): self.module.finalize_challenge_reviews(self.root)
        self.reviews(left='0',right='1',adjudicate='0')
        final=self.module.finalize_challenge_reviews(self.root)
        self.assertEqual(final['labelled_count'],1)
        self.assertEqual(final['adjudicated_count'],1)

    def test_uncertain_gold_remains_excluded(self):
        self.prepare(); self.reviews(left='uncertain',right='uncertain')
        final=self.module.finalize_challenge_reviews(self.root)
        self.assertEqual(final['labelled_count'],0)
        self.assertEqual(final['uncertain_count'],1)
        self.assertFalse(self.module.audit_challenge(self.root)['claim_ready'])

    def test_modified_packet_or_intake_is_rejected(self):
        self.prepare(); self.reviews()
        (self.root/'challenge/review-packet/packet.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(HarmError): self.module.finalize_challenge_reviews(self.root)

    def test_final_review_and_reserved_ownership_bind_actual_bytes(self):
        self.prepare(); self.reviews()
        self.module.finalize_challenge_reviews(self.root)
        receipt=self.module.challenge_reservation(self.root)
        self.assertEqual(len(receipt['duplicate_keys']),1)
        audit=self.module.audit_challenge(self.root)
        self.assertNotIn('review1',json.dumps(audit))
        self.assertTrue(audit['claim_ready'])
        with (self.root/'challenge/review-packet/reviewer-a.csv').open('a') as f: f.write('\nchanged')
        with self.assertRaises(HarmError): self.module.challenge_reservation(self.root)


if __name__=='__main__': unittest.main()
