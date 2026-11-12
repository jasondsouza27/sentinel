import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

from datetime import datetime, timedelta, timezone

from sentinel.bot_detection.adapters import Post
from sentinel.bot_detection.ml.features import (ACTIVITY_FEATURES, FEATURES, MIN_POSTS, account_features,
                                                activity_vector, vector)
from sentinel.bot_detection.ml.model import BotProfileModel
from sentinel.bot_detection.service import BotDetectionService

ARTIFACT = Path(__file__).resolve().parent.parent / "models" / "bot-ml" / "v1"
ACTIVITY_ARTIFACT = ARTIFACT.parent / "activity-v1"
START = datetime(2016, 5, 1, tzinfo=timezone.utc)


def scheduled_posts(n, minutes=15, likes=None):
    """A clock-driven account: identical promotional posts every `minutes`."""
    return [Post(timestamp=START + timedelta(minutes=minutes * i), text="Win a free phone now #win http://promo.example/x",
                 likes=likes) for i in range(n)]
ACCOUNT = {"followers": 12, "following": 4100, "posts": 9000, "age_days": 20, "bio": "", "username": "acct84629173",
           "display_name": "", "has_url": False}


class FeatureTests(unittest.TestCase):
    def test_vector_matches_feature_list(self):
        v = vector(ACCOUNT)
        self.assertEqual(len(v), len(FEATURES))
        values = dict(zip(FEATURES, v))
        self.assertGreater(values["follow_balance"], 5)
        self.assertEqual(values["username_digits"], 8)
        self.assertEqual(values["has_bio"], 0.0)

    def test_missing_required_counts(self):
        self.assertIsNone(vector({**ACCOUNT, "posts": None}))
        self.assertIsNone(vector({"followers": 3}))


class ActivityFeatureTests(unittest.TestCase):
    def test_account_features_cover_the_activity_feature_list(self):
        features = account_features(scheduled_posts(40, likes=3))
        self.assertTrue(set(ACTIVITY_FEATURES) <= set(features))
        self.assertNotIn("hour_histogram", features)
        self.assertLess(features["interval_cv"], 0.05)
        self.assertGreater(features["near_duplicate_share"], 0.9)
        self.assertAlmostEqual(features["mean_likes_log"], math.log1p(3), places=3)

    def test_only_the_latest_hundred_posts_are_used(self):
        features = account_features(scheduled_posts(250))
        self.assertEqual(features["posts_analysed"], 100)

    def test_vector_layout_and_missing_values(self):
        features = account_features(scheduled_posts(30))  # no likes -> mean_likes_log missing
        v = activity_vector(features, ACCOUNT)
        self.assertEqual(len(v), len(ACTIVITY_FEATURES) + len(FEATURES))
        self.assertTrue(math.isnan(v[ACTIVITY_FEATURES.index("mean_likes_log")]))
        self.assertEqual(v[len(ACTIVITY_FEATURES):], vector(ACCOUNT))
        self.assertIsNone(activity_vector(features, {**ACCOUNT, "followers": None}))


class FakeModel:
    def __init__(self, result):
        self.result, self.manifest, self.error = result, {"model_version": "fake", "release": result.get("state")}, None
        self.calls = []

    def assess(self, platform, account, posts=None):
        self.calls.append((platform, account))
        return self.result


class ServiceIntegrationTests(unittest.TestCase):
    body = {"platform": "x", "account": "@acct84629173", "source": "manual",
            "profile": {"account_age_days": 20, "followers": 12, "following": 4100, "total_posts": 9000}}

    def test_ml_result_is_reported_separately_and_does_not_change_classification(self):
        plain = BotDetectionService().analyze(self.body)
        fake = FakeModel({"state": "released", "bot_probability": 0.99})
        with_ml = BotDetectionService(ml_model=fake).analyze(self.body)
        self.assertEqual(with_ml["ml_model"]["bot_probability"], 0.99)
        self.assertEqual((plain["score"], plain["classification"]), (with_ml["score"], with_ml["classification"]))
        platform, account = fake.calls[0]
        self.assertEqual((platform, account["followers"], account["posts"]), ("x", 12, 9000))
        self.assertIsNone(plain["ml_model"])

    def test_ml_failure_is_contained(self):
        class Broken:
            manifest, error = {}, None
            def assess(self, platform, account, posts=None): raise RuntimeError("boom")
        report = BotDetectionService(ml_model=Broken()).analyze(self.body)
        self.assertEqual(report["ml_model"]["state"], "unavailable")

    def test_missing_or_tampered_artifact(self):
        self.assertEqual(BotProfileModel("/nonexistent").assess("x", ACCOUNT)["state"], "unavailable")
        if not (ARTIFACT / "manifest.json").exists():
            self.skipTest("bot-ml artifact not trained")
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "v1"
            shutil.copytree(ARTIFACT, copy)
            with open(copy / "calibration.json", "a") as stream:
                stream.write(" ")
            self.assertEqual(BotProfileModel(copy).error, "artifact_checksum_mismatch")


class RealArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = BotProfileModel(ARTIFACT)
        if cls.model.model is None:
            raise unittest.SkipTest(f"bot-ml artifact unavailable: {cls.model.error}")

    def test_research_only_model_withholds_its_estimate(self):
        if self.model.released:
            self.skipTest("model passed its release gate")
        result = self.model.assess("x", ACCOUNT)
        self.assertEqual(result["state"], "research_only")
        self.assertNotIn("bot_probability", result)
        self.assertIn("held-out AUC", result["validation"])

    def test_research_mode_and_scope(self):
        research = BotProfileModel(ARTIFACT, research_mode=True)
        probability = research.assess("x", ACCOUNT)["bot_probability"]
        self.assertTrue(0 <= probability <= 1)
        self.assertEqual(research.assess("instagram", ACCOUNT)["state"], "not_applicable")
        self.assertEqual(research.assess("x", {**ACCOUNT, "following": None})["state"], "insufficient_data")

    def test_gate_is_recorded_in_manifest(self):
        gate = self.model.manifest["release_gate"]
        self.assertEqual(gate["passed"], self.model.manifest["release"] == "released")
        self.assertGreaterEqual(gate["min_lodo_auc_each_dataset"], 0.8)


class ActivityArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = BotProfileModel(ACTIVITY_ARTIFACT)
        if cls.model.model is None:
            raise unittest.SkipTest(f"activity artifact unavailable: {cls.model.error}")

    def test_kind_and_gate(self):
        self.assertEqual(self.model.kind, "activity")
        gate = self.model.manifest["release_gate"]
        self.assertEqual(gate["passed"], self.model.manifest["release"] == "released")
        self.assertGreaterEqual(gate["min_auc_every_fold"], 0.8)

    def test_scope_and_minimum_posts(self):
        self.assertEqual(self.model.assess("instagram", ACCOUNT, scheduled_posts(40))["state"], "not_applicable")
        result = self.model.assess("x", ACCOUNT, scheduled_posts(MIN_POSTS - 1))
        self.assertEqual(result["state"], "insufficient_data")
        self.assertEqual(self.model.assess("x", ACCOUNT, None)["state"], "insufficient_data")

    def test_estimate_only_when_released_or_research_mode(self):
        result = self.model.assess("x", ACCOUNT, scheduled_posts(60, likes=0))
        if self.model.released:
            self.assertEqual(result["state"], "released")
            self.assertTrue(0 <= result["bot_probability"] <= 1)
        else:
            self.assertEqual(result["state"], "research_only")
            self.assertNotIn("bot_probability", result)
        research = BotProfileModel(ACTIVITY_ARTIFACT, research_mode=True).assess("x", ACCOUNT, scheduled_posts(60))
        self.assertTrue(0 <= research["bot_probability"] <= 1)

    def test_scheduled_spam_scores_above_irregular_human(self):
        import random
        rng = random.Random(4)
        t, human = START, []
        words = "lecture coffee train exam weekend dinner match family book rain friends project music late".split()
        for _ in range(80):
            t += timedelta(hours=rng.expovariate(1 / 9))
            human.append(Post(timestamp=t, text=" ".join(rng.choice(words) for _ in range(rng.randint(5, 12))),
                              likes=rng.randint(0, 30)))
        person = {"followers": 310, "following": 290, "posts": 4200, "age_days": 1900, "bio": "CS student, cricket",
                  "username": "priya_s", "display_name": "Priya", "has_url": False}
        model = BotProfileModel(ACTIVITY_ARTIFACT, research_mode=True)
        spam = model.assess("x", ACCOUNT, scheduled_posts(100, likes=0))["bot_probability"]
        normal = model.assess("x", person, human)["bot_probability"]
        self.assertGreater(spam, normal)

    def test_service_reports_activity_model_separately(self):
        service = BotDetectionService(ml_activity_model=self.model)
        posts = [{"timestamp": p.timestamp.isoformat(), "text": p.text} for p in scheduled_posts(40)]
        report = service.analyze({"platform": "x", "account": "@acct84629173", "source": "upload",
                                  "upload": {"format": "json", "posts": posts,
                                             "profile": {"account_age_days": 20, "followers": 12, "following": 4100,
                                                         "total_posts": 9000}}})
        self.assertEqual(report["ml_activity_model"]["kind"], "activity_classifier")
        self.assertIn(report["ml_activity_model"]["state"], ("released", "research_only"))
        self.assertIsNone(report["ml_model"])


if __name__ == "__main__":
    unittest.main()
