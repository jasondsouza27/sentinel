import unittest

from sentinel.analysis import analyze
from sentinel.research import train_models


class AnalysisTests(unittest.TestCase):
    def test_structured_target_keeps_embedded_url_and_excludes_future_observations(self):
        payload={'conversation_kind':'linear','target_turn_id':'selected','conversation_turns':[
            {'turn_id':'prior','speaker_id':None,'text':'An ordinary discussion.'},
            {'turn_id':'selected','speaker_id':'local1','text':'Pay a fee at https://example.org/apply'},
            {'turn_id':'future','speaker_id':'local2','text':'you are stupid send password at https://later.example/'}]}
        result=analyze(payload)
        self.assertEqual(result['fraud']['analyzed_url'],'https://example.org/apply')
        self.assertEqual(result['harmful_content']['level'],'low_observed_concern')
        self.assertFalse(any('password' in fact for fact in result['fraud']['evidence']))

    def test_known_phishing_link_and_payment_request_have_separate_evidence(self):
        result = analyze(
            {"message": "You are shortlisted. Pay a registration fee now at https://fake.example/pay", "url": "https://fake.example/pay"},
            known_phishing={"https://fake.example/pay"},
        )
        self.assertEqual(result["fraud"]["level"], "high")
        self.assertTrue(any("verified phishing" in e.lower() for e in result["fraud"]["evidence"]))
        self.assertTrue(any("payment" in e.lower() for e in result["fraud"]["evidence"]))
        self.assertEqual(result["fraud"]["method"], "evidence rules")
        self.assertNotIn("confidence", result["fraud"])

    def test_absent_reputation_is_not_a_safe_verdict(self):
        result = analyze({"url": "https://example.org/"})
        self.assertIn("reputation feed", " ".join(result["fraud"]["unavailable_checks"]).lower())
        self.assertNotEqual(result["fraud"]["level"], "safe")

    def test_insufficient_profile_data_does_not_claim_fake_account(self):
        result = analyze({"profile": {"username": "newstudent"}})
        self.assertEqual(result["profile"]["status"], "insufficient_evidence")
        self.assertNotIn("fake", " ".join(result["profile"]["evidence"]).lower())

    def test_quoted_insult_requests_review(self):
        result = analyze({"message": 'She reported that someone wrote "you are stupid" in the chat.'})
        self.assertEqual(result["harmful_content"]["level"], "review")

    def test_empty_input_is_rejected(self):
        with self.assertRaises(ValueError):
            analyze({"message": "  "})

    def test_trained_url_and_combined_votes_remain_separate_from_evidence(self):
        rows = [
            {"message": "pay fee now", "url": "https://fee.example/pay", "label": "1"},
            {"message": "send password", "url": "https://login.example/verify", "label": "1"},
            {"message": "club meeting", "url": "https://club.example/news", "label": "0"},
            {"message": "library hours", "url": "https://library.example/hours", "label": "0"},
        ]
        result = analyze({"message": "pay fee now", "url": "https://fee.example/pay"}, model=train_models(rows))
        self.assertIn("url", result["fraud"]["model_votes"])
        self.assertIn("combined", result["fraud"]["model_votes"])
        self.assertIn("not calibrated", result["fraud"]["model_note"])

    def test_optional_paired_result_does_not_change_default_or_rule_fraud(self):
        payload = {"message": "Pay now", "url": "https://example.com/pay"}
        default = analyze(payload)
        self.assertNotIn("paired_assessment", default)

        class Paired:
            def assess(self, message, url):
                return {"state": "unavailable", "category": "not_assessed", "evidence": [],
                        "uncertainty": "Not released", "unavailable_checks": ["Research only"],
                        "action": "Verify independently", "model_version": None}

        optional = analyze(payload, paired_model=Paired())
        self.assertEqual(optional["fraud"], default["fraud"])
        self.assertEqual(optional["paired_assessment"]["state"], "unavailable")


if __name__ == "__main__":
    unittest.main()
