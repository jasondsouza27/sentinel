import unittest
from url_ml_fixtures import HAS_ML

@unittest.skipUnless(HAS_ML,"Optional URL ML environment is not installed")
class CalibrationTests(unittest.TestCase):
    def setUp(self):
        try: from sentinel.url_ml import calibration
        except ImportError: self.fail("Held-out calibration is missing")
        self.api=calibration

    def test_positive_mapping_raw_decision_and_reverse_guard(self):
        import numpy as np
        labels=np.array([0]*100+[1]*100); scores=np.array([.2]*100+[.8]*100)
        cal=self.api.fit_calibration(labels,scores,.8)
        self.assertEqual(cal.status,"available"); self.assertGreater(cal.slope,0)
        mapped=self.api.apply_calibration(cal,np.array([.2,.8]))
        self.assertLess(mapped[0],mapped[1]); self.assertAlmostEqual(cal.threshold,mapped[1])
        reversed_cal=self.api.fit_calibration(labels,1-scores,.8)
        self.assertEqual(reversed_cal.status,"unavailable")
        self.assertIsNone(self.api.apply_calibration(reversed_cal,scores))
        self.assertEqual(reversed_cal.report["reason"],"nonpositive_or_invalid_slope")

    def test_constant_imbalanced_scores_do_not_manufacture_confidence(self):
        cal=self.api.fit_calibration([0]*180+[1]*20,[.1]*200,None)
        self.assertEqual(cal.status,"unavailable")
        self.assertEqual(cal.report["reason"],"insufficient_score_variation")
        self.assertIsNone(cal.slope); self.assertIsNone(cal.intercept)
        self.assertIsNone(self.api.apply_calibration(cal,[.1,.5,.9]))

    def test_clipped_and_numerically_tied_logits_are_unavailable(self):
        for scores in ([0]*100+[1e-8]*100,[1]*100+[1-1e-8]*100,[.1]*100+[.1+1e-12]*100):
            with self.subTest(scores=scores[:1]):
                cal=self.api.fit_calibration([0]*100+[1]*100,scores,.5)
                self.assertEqual(cal.status,"unavailable")
                self.assertEqual(cal.report["reason"],"insufficient_score_variation")
                self.assertIsNone(cal.threshold)

    def test_minimum_support_clipping_and_no_threshold(self):
        import numpy as np
        tiny=self.api.fit_calibration(np.array([0,1]),np.array([0,1]),None)
        self.assertEqual(tiny.status,"unavailable")
        enough=self.api.fit_calibration(np.array([0]*100+[1]*100),np.array([0]*100+[1]*100),None)
        self.assertEqual(enough.status,"available"); self.assertIsNone(enough.threshold)
        self.assertTrue(np.all(np.isfinite(self.api.apply_calibration(enough,np.array([0,1])))))

if __name__=="__main__": unittest.main()
