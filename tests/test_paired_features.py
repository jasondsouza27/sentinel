import unittest
from pathlib import Path

from sentinel.paired.features import strip_links, paired_inputs
from sentinel.url_ml.urls import UrlParser


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser = UrlParser(Path(__file__).resolve().parents[1] / "resources" / "url-v2-suffix.dat")

    def test_message_branch_removes_host_path_and_query_from_every_link(self):
        message = "Verify award https://host.example/secretpath?credentialtoken=yes then www.other.com/hiddenpath"
        clean = strip_links(message).lower()
        for token in ("host", "secretpath", "credentialtoken", "other", "hiddenpath"):
            self.assertNotIn(token, clean)
        self.assertIn("verify award", clean)

    def test_inputs_keep_modalities_separate(self):
        row = {"case_id": "a", "message": "Special scholarship https://school.com/pay",
               "url": "https://school.com/pay", "label": "1"}
        message = paired_inputs("message", [row], self.parser)
        url = paired_inputs("url", [row], self.parser)
        early = paired_inputs("early", [row], self.parser)
        self.assertIn("scholarship", message[0][0])
        self.assertNotIn("school", message[0][0])
        self.assertEqual(url[0], ["https://school.com/pay"])
        self.assertEqual(early[0][0], message[0][0])
        self.assertEqual(early[1][0], url[0][0])

    def test_missing_or_malformed_url_is_unsupported(self):
        row = {"case_id": "a", "message": "Check this", "url": "", "label": "1"}
        for kind in ("message", "url", "early"):
            with self.assertRaises(ValueError):
                paired_inputs(kind, [row], self.parser)
            with self.assertRaises(ValueError):
                paired_inputs(kind, [{**row, "url": "https://bad.com:broken/x"}], self.parser)


if __name__ == "__main__":
    unittest.main()
