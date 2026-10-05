import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from url_ml_fixtures import HAS_ML, fixture_psl


@unittest.skipUnless(HAS_ML, "Optional URL ML environment is not installed")
class UrlParserTests(unittest.TestCase):
    def setUp(self):
        try:
            from sentinel.url_ml.urls import UrlParser
            from sentinel.url_ml.contracts import UnsupportedUrl
        except ModuleNotFoundError:
            self.fail("URL parser feature is missing")
        self.UnsupportedUrl = UnsupportedUrl
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.psl = fixture_psl(Path(self.temp.name))
        self.parser = UrlParser(self.psl)

    def test_private_suffix_and_ipv6_groups(self):
        self.assertEqual(self.parser.normalize("https://a.github.io/A").domain_group, "domain:a.github.io")
        self.assertEqual(self.parser.normalize("https://b.github.io/A").domain_group, "domain:b.github.io")
        self.assertEqual(self.parser.normalize("https://help.example.co.uk/A").domain_group, "domain:example.co.uk")
        self.assertEqual(self.parser.normalize("http://[2001:db8::1]/").domain_group, "ip:2001:db8::1")

    def test_spelling_idna_and_equivalent_authorities(self):
        first = self.parser.normalize("HTTPS://B\u00dcCHER.DE.:443/A?Token=X#Part")
        second = self.parser.normalize("https://xn--bcher-kva.de/A?Token=X#Part")
        self.assertEqual(first.model_url, second.model_url)
        self.assertEqual(first.model_url, "https://xn--bcher-kva.de/A?Token=X#Part")
        self.assertIn("punycode", first.flags)
        self.assertEqual(self.parser.normalize("http://User:Pass@EXAMPLE.ORG:80/A").model_url,
                         "http://User:Pass@example.org/A")

    def test_invalid_authorities_controls_and_schemes_are_unsupported(self):
        for value in ("https://example.org:99999/a", "https://example.org:-1/a", "http://[bad/a",
                      "https:///nohost", "ftp://example.org/", "https://exa mple.org/", "https://example.org/a\nB",
                      "https://example.org/%ZZ", "https://example.org:\n80/", "https://./", None, 123):
            with self.subTest(value=value), self.assertRaises(self.UnsupportedUrl):
                self.parser.normalize(value)

    def test_exact_size_boundary(self):
        prefix = "https://example.org/"
        value = prefix + "a" * (2048 - len(prefix))
        self.assertEqual(len(self.parser.normalize(value).model_url), 2048)
        with self.assertRaises(self.UnsupportedUrl):
            self.parser.normalize(value + "a")

    def test_unknown_suffix_private_targets_and_no_destination_requests(self):
        with patch("socket.create_connection", side_effect=AssertionError("No network allowed")):
            parser = type(self.parser)(self.psl)
            result = parser.normalize("https://a.unknownsuffix/A")
            self.assertEqual(result.domain_group, "domain:a.unknownsuffix")
            self.assertIn("unknown_suffix", result.flags)
            self.assertEqual(parser.normalize("http://127.0.0.1/").domain_group, "ip:127.0.0.1")
            self.assertEqual(parser.normalize("http://localhost/").host, "localhost")
        self.assertEqual(parser.psl_sha256, hashlib.sha256(self.psl.read_bytes()).hexdigest())

    def test_suffix_snapshot_handle_is_released(self):
        self.parser.normalize("https://a.github.io/A")
        self.psl.unlink()
        with patch("socket.create_connection", side_effect=AssertionError("No network allowed")):
            self.assertEqual(self.parser.normalize("https://b.github.io/").domain_group, "domain:b.github.io")

    def test_assessment_omits_absent_probability(self):
        from sentinel.url_ml.contracts import UrlAssessment
        assessment = UrlAssessment("unavailable", None, None, (), ("Model unavailable",), (), "Verify independently.")
        self.assertNotIn("probability", assessment.to_dict())


if __name__ == "__main__":
    unittest.main()
