import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sentinel.bot_detection import features as F
from sentinel.bot_detection.adapters import AccountData, Post, SourceUnavailable, UpstreamError, http, reddit, youtube
from sentinel.bot_detection.adapters.supplied import InvalidData, from_manual, from_upload
from sentinel.bot_detection.platforms import InvalidAccount, describe, parse_account
from sentinel.bot_detection.scoring import HeuristicScorer, load_config
from sentinel.bot_detection.service import BadRequest, BotDetectionService, RateLimiter

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "bot_accounts.json").read_text())
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def upload_request(name, account="@someone_1", platform="x"):
    return {"platform": platform, "account": account, "source": "upload", "upload": {"format": "json", **FIXTURES[name]}}


class PlatformTests(unittest.TestCase):
    def test_accepts_urls_and_usernames(self):
        cases = {("x", "https://x.com/jack"): "jack", ("x", "twitter.com/jack/"): "jack", ("x", "@jack"): "jack",
                 ("reddit", "https://old.reddit.com/u/spez"): "spez", ("reddit", "u/spez"): "spez",
                 ("youtube", "https://www.youtube.com/@MrBeast"): "MrBeast", ("instagram", "natgeo"): "natgeo"}
        for (platform, value), expected in cases.items():
            self.assertEqual(parse_account(platform, value)["username"], expected, value)
        self.assertEqual(parse_account("youtube", "https://youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA")["kind"], "channel_id")

    def test_rejects_ssrf_and_invalid_input(self):
        for platform, value in [("x", "https://evil.example/jack"), ("x", "https://x.com@evil.example/jack"),
                                ("x", "http://127.0.0.1/jack"), ("x", "https://x.com:8443/jack"), ("x", "file:///etc/passwd"),
                                ("x", "javascript:alert(1)"), ("x", "https://x.com/home"), ("x", "a" * 16), ("x", ""),
                                ("x", None), ("reddit", "https://reddit.com/r/python"), ("youtube", "https://youtube.com/watch?v=x"),
                                ("instagram", "bad..name"), ("myspace", "tom"), ("x", "x" * 400)]:
            with self.assertRaises(InvalidAccount, msg=value):
                parse_account(platform, value)

    def test_platform_list_reflects_api_configuration(self):
        listed = {p["id"]: p for p in describe({"youtube": True, "reddit": False})}
        self.assertEqual(listed["youtube"]["sources"], ["api", "upload", "manual"])
        self.assertEqual(listed["reddit"]["sources"], ["upload", "manual"])
        self.assertEqual(listed["x"]["sources"], ["upload", "manual"])
        self.assertIn("paid", listed["x"]["api_note"])


class HttpClientTests(unittest.TestCase):
    def test_only_allowlisted_https_hosts(self):
        for url in ("http://www.googleapis.com/x", "https://evil.example/x", "https://127.0.0.1/x"):
            with self.assertRaises(UpstreamError) as caught:
                http.request_json(url)
            self.assertEqual(caught.exception.code, "blocked_host")

    def test_status_codes_map_to_safe_errors(self):
        class Opener:
            def __init__(self, code): self.code = code
            def open(self, request, timeout):
                raise urllib.error.HTTPError(request.full_url, self.code, "x", {}, io.BytesIO(b""))
        for status, code in ((429, "rate_limited"), (403, "auth_failed"), (404, "not_found"), (500, "api_error"), (302, "api_error")):
            with self.assertRaises(UpstreamError) as caught:
                http.request_json("https://www.googleapis.com/youtube/v3/channels?key=SECRET", opener=Opener(status))
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("SECRET", str(caught.exception))

    def test_oversized_response_is_refused(self):
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        class Opener:
            def open(self, request, timeout): return Response(b"x" * (http.MAX_BYTES + 10))
        with self.assertRaises(UpstreamError) as caught:
            http.request_json("https://www.googleapis.com/x", opener=Opener())
        self.assertEqual(caught.exception.code, "response_too_large")


class AdapterTests(unittest.TestCase):
    def test_youtube_requires_key_and_maps_channel(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SourceUnavailable):
                youtube.fetch({"username": "chan", "kind": "handle"})
        calls = []

        def fake(url):
            calls.append(url)
            if "/channels?" in url:
                return {"items": [{"snippet": {"publishedAt": "2020-01-01T00:00:00Z", "title": "Chan", "description": "hi",
                                               "thumbnails": {"default": {}}},
                                   "statistics": {"subscriberCount": "1200", "videoCount": "40"},
                                   "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]}
            return {"items": [{"snippet": {"publishedAt": f"2026-10-{d:02d}T10:00:00Z", "title": f"Video {d}"}} for d in range(1, 11)]}
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "k"}):
            data = youtube.fetch({"username": "chan", "kind": "handle"}, fetch_json=fake)
        self.assertIn("forHandle=%40chan", calls[0])
        self.assertTrue(all(url.startswith("https://www.googleapis.com/") for url in calls))
        self.assertEqual((data.followers, data.total_posts, len(data.posts)), (1200, 40, 10))
        self.assertIsNone(data.following)

    def test_youtube_unknown_channel(self):
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "k"}):
            with self.assertRaises(UpstreamError) as caught:
                youtube.fetch({"username": "nobody", "kind": "handle"}, fetch_json=lambda url: {"items": []})
        self.assertEqual(caught.exception.code, "not_found")

    def test_reddit_flow_and_suspension(self):
        env = {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret", "REDDIT_USER_AGENT": "sentinel-test/1.0"}
        reddit._token.update(value=None, expires=0)

        def fake(url, headers=None, data=None):
            if url.endswith("access_token"):
                self.assertEqual(data, b"grant_type=client_credentials")
                return {"access_token": "tok", "expires_in": 3600}
            self.assertEqual(headers["Authorization"], "Bearer tok")
            if url.endswith("/about"):
                return {"data": {"created_utc": 1600000000, "verified": True, "icon_img": "https://x/avatar_default_1.png"}}
            return {"data": {"children": [{"data": {"created_utc": 1700000000 + i * 3600, "body": f"comment {i}", "title": "t",
                                                    "score": i}} for i in range(5)]}}
        with patch.dict(os.environ, env):
            data = reddit.fetch({"username": "someone", "kind": "username"}, fetch_json=fake)
            self.assertEqual(len(data.posts), 10)
            self.assertTrue(data.default_profile_image)
            reddit._token.update(value=None, expires=0)
            with self.assertRaises(SourceUnavailable):
                reddit.fetch({"username": "gone", "kind": "username"},
                             fetch_json=lambda url, headers=None, data=None: {"access_token": "t"} if "token" in url
                             else {"data": {"is_suspended": True}})
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SourceUnavailable):
                reddit.fetch({"username": "x", "kind": "username"})


class SuppliedDataTests(unittest.TestCase):
    account = {"platform": "x", "username": "someone"}

    def test_csv_and_json_uploads(self):
        csv_text = "timestamp,text,is_repost,likes\n2026-10-01T10:00:00Z,hello,false,3\n1759320000,world,yes,\n"
        data = from_upload(self.account, {"format": "csv", "content": csv_text})
        self.assertEqual(len(data.posts), 2)
        self.assertTrue(data.posts[1].is_repost)
        data = from_upload(self.account, {"format": "json", "profile": {"followers": "120", "verified": "yes"},
                                          "posts": [{"timestamp": "2026-10-01T10:00:00", "text": "hi"}]})
        self.assertEqual((data.followers, data.verified, data.total_posts), (120, True, 1))

    def test_invalid_uploads(self):
        bad = [{"format": "xml"}, {"format": "csv", "content": "text\nno timestamp column"},
               {"format": "json", "posts": [{"timestamp": "yesterday"}]}, {"format": "json", "posts": "nope"},
               {"format": "json", "profile": {"followers": -5}, "posts": []},
               {"format": "json", "profile": {"followers": True}, "posts": []},
               {"format": "json", "posts": [{"timestamp": 1}] * 3001}, "not an object"]
        for upload in bad:
            with self.assertRaises(InvalidData, msg=str(upload)[:60]):
                from_upload(self.account, upload)

    def test_manual_metadata(self):
        data = from_manual(self.account, {"account_age_days": 10, "followers": 5})
        self.assertEqual((data.fetched_at - data.created_at).days, 10)
        self.assertIn("Only profile metadata", data.limitations[0])


def account_with(posts, **profile):
    data = AccountData(platform="x", username="someone", source="upload", **profile)
    data.posts = posts
    return data


class FeatureTests(unittest.TestCase):
    def test_regular_schedule_vs_irregular(self):
        regular = [Post(NOW - timedelta(minutes=30 * i), "x") for i in range(60)]
        f = F.activity_features(regular, NOW)
        self.assertLess(f["interval_cv"], 0.05)
        self.assertGreater(f["regular_interval_share"], 0.95)
        import random
        rng = random.Random(3)
        t, irregular = NOW, []
        for _ in range(60):
            t -= timedelta(hours=rng.expovariate(1 / 6))
            irregular.append(Post(t, "x"))
        self.assertGreater(F.activity_features(irregular, NOW)["interval_cv"], 0.6)

    def test_too_few_posts_give_no_timing_features(self):
        f = F.activity_features([Post(NOW, "a"), Post(NOW - timedelta(hours=1), "b")], NOW)
        self.assertIsNone(f["posts_per_day"])
        self.assertNotIn("interval_cv", f)

    def test_duplicates_and_content(self):
        posts = [Post(NOW - timedelta(hours=i), f"Win a free phone now #win #free #deal http://promo.example/{i % 2}")
                 for i in range(10)] + [Post(NOW - timedelta(days=2), "Completely different thoughts about the weather")]
        f = F.content_features(posts)
        self.assertGreater(f["near_duplicate_share"], 0.8)
        self.assertEqual(f["top_domain_share"], 1.0)
        self.assertGreaterEqual(f["hashtags_per_post"], 2.5)

    def test_missing_profile_data_is_none(self):
        f = F.profile_features(AccountData(platform="x", username="a", source="manual"))
        self.assertIsNone(f["account_age_days"])
        self.assertIsNone(f["profile_completeness"])
        self.assertIsNone(f["default_or_missing_image"])

    def test_follower_growth(self):
        data = account_with([], followers=1000, following=10)
        data.follower_history = [(NOW - timedelta(days=2), 100), (NOW - timedelta(days=1), 900)]
        self.assertGreater(F.engagement_features(data)["max_daily_follower_growth"], 5)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.service = BotDetectionService()

    def test_known_examples(self):
        bot = self.service.analyze(upload_request("bot", "@promo84629173"))
        human = self.service.analyze(upload_request("human", "@priya_sharma"))
        coordinated = self.service.analyze(upload_request("coordinated", "@citizen_truth"))
        self.assertGreaterEqual(bot["score"], 75)
        self.assertEqual(bot["classification"]["id"], "likely_automated")
        self.assertEqual(bot["confidence"]["level"], "High")
        self.assertLess(human["score"], 30)
        self.assertEqual(human["classification"]["id"], "likely_human")
        self.assertEqual(coordinated["classification"]["id"], "suspicious_or_coordinated")
        self.assertTrue(coordinated["coordination_flag"])
        self.assertEqual(bot["suspicious_indicators"][0]["id"], max(bot["signals"], key=lambda s: s["contribution"])["id"])
        self.assertTrue(human["human_indicators"])

    def test_sparse_data_withholds_score(self):
        report = self.service.analyze({"platform": "instagram", "account": "someone", "source": "manual", "profile": {"followers": 10}})
        self.assertIsNone(report["score"])
        self.assertEqual(report["classification"]["id"], "insufficient_data")
        self.assertEqual(report["confidence"]["level"], "Very low")
        self.assertIn("not enough data", report["explanation"])

    def test_profile_only_never_reaches_high_confidence(self):
        report = self.service.analyze({"platform": "x", "account": "@abc12345678", "source": "manual",
                                       "profile": {"account_age_days": 3, "followers": 2, "following": 3000,
                                                   "has_profile_image": False, "bio": "", "display_name": ""}})
        self.assertIn(report["confidence"]["level"], ("Low", "Very low"))
        self.assertTrue(any("not assessed" in item or "No posts" in item for item in report["limitations"]))

    def test_verified_only_lowers_score(self):
        scorer = HeuristicScorer()
        base = {"account_age_days": 20, "profile_completeness": 0.2, "default_or_missing_image": 1.0, "username_trailing_digits": 8}
        unverified = scorer.score(base, 0)["indicative_score"] or scorer.score(base, 0)["score"]
        verified = scorer.score({**base, "verified": 1.0}, 0)
        self.assertLess(verified["score"] if verified["score"] is not None else verified["indicative_score"], unverified)
        self.assertEqual(scorer.score({**base, "verified": 0.0}, 0)["coverage"], scorer.score(base, 0)["coverage"])

    def test_config_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "w.json"
            config = json.loads(Path(load_config.__defaults__[0]).read_text())
            config["signals"][0]["direction"] = "sideways"
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                load_config(path)


class ServiceTests(unittest.TestCase):
    def test_validation_errors(self):
        service = BotDetectionService()
        for body, code in [("x", "invalid_request"), ({"platform": "myspace", "account": "a", "source": "upload"}, "unsupported_platform"),
                           ({"platform": "x", "account": "a", "source": "scrape"}, "invalid_source"),
                           ({"platform": "x", "account": "https://evil.example/a", "source": "upload"}, "invalid_account"),
                           ({"platform": "x", "account": "@a", "source": "api"}, "api_not_available"),
                           ({"platform": "x", "account": "@a", "source": "upload", "upload": {"format": "csv", "content": "x"}}, "invalid_data")]:
            with self.assertRaises(BadRequest) as caught:
                service.analyze(body)
            self.assertEqual(caught.exception.code, code, body)

    def test_rate_limit(self):
        clock = [0.0]
        service = BotDetectionService(limiter=RateLimiter(limit=2, window_seconds=60, clock=lambda: clock[0]))
        body = {"platform": "x", "account": "@a", "source": "manual", "profile": {"followers": 1}}
        service.analyze(body); service.analyze(body)
        with self.assertRaises(BadRequest) as caught:
            service.analyze(body)
        self.assertEqual((caught.exception.code, caught.exception.status), ("rate_limited", 429))
        clock[0] = 61
        service.analyze(body)

    def test_upstream_errors_map_to_status(self):
        class Failing:
            def __init__(self, code): self.code = code
            def configured(self): return True
            def fetch(self, account): raise UpstreamError(self.code, "upstream said no")
        for code, status in (("rate_limited", 429), ("network_error", 502), ("not_found", 400)):
            service = BotDetectionService(adapters={"youtube": Failing(code), "reddit": Failing(code)})
            with self.assertRaises(BadRequest) as caught:
                service.analyze({"platform": "youtube", "account": "@channel", "source": "api"})
            self.assertEqual((caught.exception.code, caught.exception.status), (code, status))

    def test_logs_never_contain_username_or_content(self):
        with self.assertLogs("sentinel.bot_detection", level="INFO") as logs:
            BotDetectionService().analyze(upload_request("bot", "@secretname123"))
        joined = " ".join(logs.output)
        self.assertNotIn("secretname123", joined)
        self.assertNotIn("giveaway", joined)
        self.assertIn("platform=x", joined)


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sentinel.server import create_server
        cls.directory = tempfile.TemporaryDirectory()
        cls.server = create_server(port=0, db_path=Path(cls.directory.name) / "cases.db")
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.worker.join(3); cls.directory.cleanup()

    def post(self, path, body):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        with urlopen(Request(self.base + path, data=data, headers={"Content-Type": "application/json"}), timeout=10) as response:
            return response.status, json.load(response)

    def test_platforms_and_page(self):
        with urlopen(self.base + "/api/bot/platforms", timeout=5) as response:
            listed = json.load(response)
        self.assertEqual({p["id"] for p in listed["platforms"]}, {"x", "instagram", "facebook", "reddit", "youtube"})
        with urlopen(self.base + "/bot", timeout=5) as response:
            self.assertIn(b"Social media bot account detection", response.read())

    def test_analyze_large_upload_and_errors(self):
        status, report = self.post("/api/bot/analyze", upload_request("bot", "@promo84629173"))
        self.assertEqual(status, 200)
        self.assertEqual(report["classification"]["id"], "likely_automated")
        with self.assertRaises(HTTPError) as caught:
            self.post("/api/bot/analyze", {"platform": "x", "account": "https://evil.example/a", "source": "upload"})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(json.load(caught.exception)["code"], "invalid_account")

    def test_existing_endpoints_keep_their_body_limit(self):
        big = json.dumps({"message": "x" * 250000}).encode()
        with self.assertRaises(HTTPError) as caught:
            self.post("/api/analyze", big)
        self.assertEqual(caught.exception.code, 400)

    def test_nothing_is_saved(self):
        self.post("/api/bot/analyze", upload_request("human", "@priya_sharma"))
        with urlopen(self.base + "/api/cases", timeout=5) as response:
            self.assertEqual(json.load(response), [])


if __name__ == "__main__":
    unittest.main()
