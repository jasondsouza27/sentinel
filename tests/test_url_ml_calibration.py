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

    def test_minimum_support_clipping_and_no_threshold(self):
        import numpy as np
        tiny=self.api.fit_calibration(np.array([0,1]),np.array([0,1]),None)
        self.assertEqual(tiny.status,"unavailable")
        enough=self.api.fit_calibration(np.array([0]*100+[1]*100),np.array([0]*100+[1]*100),None)
        self.assertEqual(enough.status,"available"); self.assertIsNone(enough.threshold)
        self.assertTrue(np.all(np.isfinite(self.api.apply_calibration(enough,np.array([0,1])))))

if __name__=="__main__": unittest.main()
