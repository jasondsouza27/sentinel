import tempfile
import unittest
from pathlib import Path
from url_ml_fixtures import HAS_ML,fixture_psl

@unittest.skipUnless(HAS_ML,"Optional URL ML environment is not installed")
class FeatureTests(unittest.TestCase):
    def setUp(self):
        try: from sentinel.url_ml import features
        except ImportError: self.fail("Shared lexical features are missing")
        from sentinel.url_ml.urls import UrlParser
        self.api=features; self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.parser=UrlParser(fixture_psl(Path(self.temp.name)))

    def test_observable_properties_and_fixed_feature_order(self):
        parsed=self.parser.normalize("https://User:Pass@xn--bcher-kva.de/A1?Token=X%20#Part")
        f=self.api.lexical_features(parsed)
        self.assertEqual(tuple(f),self.api.FEATURE_NAMES)
        self.assertEqual(f["is_https"],1); self.assertEqual(f["punycode"],1)
        self.assertEqual(f["user_info_count"],1); self.assertEqual(f["encoding_count"],1)
        self.assertEqual(f["path_length"],3); self.assertGreater(f["digit_ratio"],0)
        transform=self.api.LexicalTransformer(self.parser)
        a=transform.transform([parsed.model_url]); b=transform.transform(["HTTPS://User:Pass@xn--bcher-kva.de:443/A1?Token=X%20#Part"])
        import numpy as np
        np.testing.assert_equal(a,b)
        self.assertEqual(a.shape,(1,len(f)))
        self.assertFalse({"label","source_ref","FILENAME"} & set(f))

    def test_ip_unknown_suffix_and_empty_ratios_finite(self):
        import numpy as np
        for url in ("http://[2001:db8::1]/","http://localhost/","http://example.org/"):
            f=self.api.lexical_features(self.parser.normalize(url))
            self.assertTrue(all(np.isfinite(list(f.values()))))
        self.assertEqual(self.api.lexical_features(self.parser.normalize("http://127.0.0.1/"))["ip_host"],1)

if __name__=="__main__": unittest.main()
