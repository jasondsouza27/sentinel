"""Agent-based simulation of the community scam network.

Virtual users receive messages over virtual time:

- Scam campaigns are seeded from held-out test-split spam and smishing (never
  training data). Each one spreads to hundreds or thousands of users along a
  logistic curve and mutates as it ages: rewording, new numbers and links, then
  leetspeak, look-alike letters and dotted spacing.
- Legitimate bulk messages (bank alerts, OTP notices, college and delivery
  updates) reach many users. They test that the network does not turn ordinary
  mass messages into false campaigns.
- Background ham from the test split adds ordinary noise.
- Optional attackers register new clients and report a legitimate bank template
  to try to get it published (poisoning).

Each user's own detector is the real text-ml-v1 model (scores cached per
distinct text) when it is installed; otherwise detection rates are sampled
(stated in the result). Only users who opted in share fingerprints, and users
refresh the campaign feed on a fixed interval, so they see a slightly stale
feed, as real clients would.
"""

import json
import math
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..text_ml.source import load_dataset
from .client import LocalTransport, NetworkClient
from .fingerprint import fingerprint
from .hub import Hub, RejectedReport

ROOT = Path(__file__).resolve().parents[2]

LEGIT_TEMPLATES = [
    ("bank_alert", "Your A/c XX{n4} is debited for Rs {n3}.00 on {d} by UPI ref {n6}. Not you? Call the number on the back of your card."),
    ("bank_otp", "{n6} is your OTP for the transaction of Rs {n3}. Valid for 10 minutes. Do not share this OTP with anyone. - Bank"),
    ("delivery", "Your order #{n6} has been delivered. Thank you for shopping with us. Rate your experience in the app."),
    ("college", "Reminder: the end-semester exam timetable is on the student portal. Hall tickets can be collected from the office on {d}."),
    ("telecom", "Recharge of Rs {n3} successful for your number. Validity till {d}. Data balance 1.5GB per day."),
    ("pharmacy", "Your prescription order {n6} is ready for pickup at the store. Bring a photo ID when collecting."),
    ("electricity", "Electricity bill of Rs {n3} for consumer no {n6} is due on {d}. Pay through the official app or website."),
    ("salary", "Salary of Rs {n4}0 credited to your A/c XX{n4} on {d}. Available balance updated."),
]
# Invented examples written in the style of publicly reported recent scams (digital
# arrest, "new number" impersonation, task and investment groups). They are not
# real messages; they test campaigns that an older SMS-trained model misses.
MODERN_SCAMS = [
    "Hello, this is officer Sharma from the cyber crime branch. A parcel in your name had illegal items. Stay on the video call and do not tell your family.",
    "hey its me, I lost my phone and this is my new number. can you send me 2000 on gpay urgently, I will return it tonight",
    "Hi dear, I am Priya from the HR team. We have a part time job, just like YouTube videos and earn 500 to 3000 daily. Interested? Reply yes",
    "Dear consumer your electricity will be disconnected tonight at 9.30 because previous month bill was not updated. Please contact our officer immediately on 9876543210",
    "Hello sir, customs has stopped a gift package sent to you from London. Clearance charge has to be paid today otherwise the package will be returned",
    "Hi, I am from the trading mentor group. Our members are getting good daily profit with expert tips. I can add you to the group if you want to learn",
    "Sir your son has been detained at the police station. To settle the matter quietly transfer the amount now and do not inform anyone",
    "Congratulations you are shortlisted for the work from home rating job. Complete three simple tasks and get your first salary today itself",
]
SYNONYMS = {
    "account": ["a/c", "acct", "account"], "verify": ["confirm", "validate", "verify"], "click": ["tap", "visit", "open"],
    "urgent": ["immediately", "urgent", "asap"], "won": ["have been selected for", "won", "qualified for"],
    "prize": ["reward", "gift", "prize"], "free": ["complimentary", "free", "no-cost"], "call": ["ring", "call", "contact"],
    "now": ["today", "now", "right away"], "claim": ["collect", "redeem", "claim"], "your": ["ur", "your"],
    "customer": ["user", "member", "customer"], "please": ["pls", "kindly", "please"], "send": ["share", "send"],
}


@dataclass
class Config:
    users: int = 10000
    hours: int = 72
    tick_minutes: int = 10
    campaigns: int = 30
    legit_broadcasts: int = 12
    background_ham_per_user: float = 1.0
    k: int = 5
    share_rate: float = 0.6
    sync_minutes: int = 30
    mutation: bool = True
    attackers: int = 0
    attack_hour: float = 24.0
    defences: bool = True
    seed: int = 1
    detector: str = "model"  # "model" or "rates"
    model_artifact: str = "v2"  # text-ml artifact folder under models/text-ml
    user_report_rate: float = 0.03   # users who recognise a scam their detector missed and report it
    mistaken_report_rate: float = 0.001  # users who report a legitimate message by mistake
    dispute_rate: float = 0.05  # recipients of a genuine message who mark a network warning on it as wrong
    allowlisted: tuple = ("bank_alert", "bank_otp", "salary", "telecom")  # large senders that registered
    attack_target: str = "pharmacy"  # an unregistered legitimate sender
    rates_recall: tuple = (0.96, 0.85, 0.7, 0.55)
    rates_fpr: float = 0.004
    min_campaign_size: int = 200
    max_campaign_size: int = 2500
    modern_campaigns: int = 8  # campaigns seeded from MODERN_SCAMS (the rest from the SMS test split)
    extra: dict = field(default_factory=dict)


# ---------- message generation ----------

def _fill(template, rng):
    return template.format(n3=rng.randint(100, 999), n4=rng.randint(1000, 9999), n6=rng.randint(100000, 999999),
                           d=f"{rng.randint(1, 28):02d}-{rng.choice(['Jan', 'Feb', 'Mar', 'Apr'])}")


def _reword(text, rng):
    def swap(match):
        word = match.group(0)
        options = SYNONYMS.get(word.lower())
        if not options or rng.random() > 0.6:
            return word
        choice = rng.choice(options)
        return choice.capitalize() if word[0].isupper() else choice
    text = re.sub(r"[A-Za-z]+", swap, text)
    text = re.sub(r"\d", lambda m: str(rng.randint(0, 9)), text)
    text = re.sub(r"(https?://)?(www\.)?[a-z0-9-]+\.(com|net|org|co\.uk|biz|info)\S*",
                  lambda m: f"http://{rng.choice(['secure', 'my', 'id', 'pay'])}-{rng.randint(10, 99)}.{rng.choice(['top', 'xyz', 'info', 'click'])}/{rng.randint(100, 999)}",
                  text, flags=re.IGNORECASE)
    return text


def _disguise(text, rng, level):
    from ..text_ml.training import HOMOGLYPH, LEET
    words = text.split()
    rate = 0.2 if level == 2 else 0.35
    for i, word in enumerate(words):
        if len(word) > 3 and rng.random() < rate:
            kind = rng.choice(["leet", "homoglyph", "spacing"]) if level >= 3 else "leet"
            words[i] = (word.lower().translate(LEET) if kind == "leet" else
                        word.translate(HOMOGLYPH) if kind == "homoglyph" else ".".join(word))
    return " ".join(words)


def campaign_variants(seed_text, rng, mutation=True, per_level=3):
    """Variants by mutation level: 0 original, 1 reworded, 2 + leetspeak, 3 + mixed disguises."""
    if not mutation:
        return [[seed_text]] * 4
    levels = [[seed_text]]
    for level in (1, 2, 3):
        variants = []
        for _ in range(per_level):
            text = _reword(seed_text, rng)
            if level >= 2:
                text = _disguise(text, rng, level)
            variants.append(text)
        levels.append(variants)
    return levels


# ---------- detector ----------

_MODEL_CACHE = {}  # keyed by (artifact, text)
_FP_CACHE = {}


class Detector:
    """Per-text detection, computed once per distinct text (cached across runs)."""

    def __init__(self, config, rng):
        self.config, self.rng, self.cache = config, rng, _MODEL_CACHE
        self.service = None
        if config.detector == "model":
            from ..text_ml.service import TextModelService
            service = TextModelService(ROOT / "models" / "text-ml" / config.model_artifact)
            if service.available:
                self.service = service
            else:
                config.detector = "rates"

    def prepare(self, texts):
        key = self.config.model_artifact
        todo = [t for t in dict.fromkeys(texts) if (key, t) not in self.cache]
        if self.service and todo:
            for text, result in zip(todo, self.service.predict(todo)):
                self.cache[(key, text)] = (result["flagged"], result["category"], result["scam_probability"])

    def __call__(self, text, kind, level):
        if self.service:
            return self.cache[(self.config.model_artifact, text)]
        if kind == "scam":
            hit = self.rng.random() < self.config.rates_recall[level]
            return (hit, "smishing", 0.95 if hit else 0.2)
        hit = self.rng.random() < self.config.rates_fpr
        return (hit, "spam", 0.92 if hit else 0.05)


# ---------- simulation ----------

def run(config=None, db_path=":memory:", live_delay=0.0, progress=None):
    config = config or Config()
    rng = random.Random(config.seed)
    records = {r["id"]: r for r in load_dataset(ROOT / "data" / "text-ml" / "dataset.jsonl")}
    test_ids = json.loads((ROOT / "data" / "text-ml" / "splits.json").read_text())["ids"]["test"]
    test = [records[i] for i in test_ids]
    scam_seeds = [r["text"] for r in test if r["label"] != "ham" and len(r["text"].split()) >= 8]
    ham_pool = [r["text"] for r in test if r["label"] == "ham"]

    hub = Hub(db_path, k=config.k, new_client_weight=0.5 if config.defences else 1.0,
              hourly_limit=20 if config.defences else 10 ** 6, disputes_enabled=config.defences)
    clock = {"hour": 0.0}
    transport = LocalTransport(hub, lambda: clock["hour"])
    feed = NetworkClient(transport)  # the shared, periodically refreshed campaign feed

    users = []
    for _ in range(config.users):
        users.append({"id": hub.register(-48.0), "shares": rng.random() < config.share_rate})

    # ---- build every exposure up front ----
    events = []  # (hour, user index, text, kind, group id, level)
    campaigns = []
    modern = rng.sample(MODERN_SCAMS, min(config.modern_campaigns, len(MODERN_SCAMS)))
    for c in range(config.campaigns):
        seed = modern[c] if c < len(modern) else rng.choice(scam_seeds)
        start = rng.uniform(0, config.hours - 24)
        duration = rng.uniform(12, 36)
        size = min(config.users, int(math.exp(rng.uniform(math.log(config.min_campaign_size), math.log(config.max_campaign_size)))))
        levels = campaign_variants(seed, rng, config.mutation)
        campaigns.append({"id": c, "start": start, "size": size, "published_hour": None, "modern": c < len(modern)})
        for user in rng.sample(range(config.users), size):
            hour = -1.0
            while not start <= hour < config.hours:  # logistic spread, truncated (no pile-up at the start)
                u = min(max(rng.random(), 1e-9), 1 - 1e-9)
                hour = start + duration / 2 + (duration / 8) * math.log(u / (1 - u))
            level = min(int((hour - start) / 6), 3)
            events.append((hour, user, rng.choice(levels[level]), "scam", c, level))
    legit_groups = []
    for g in range(config.legit_broadcasts):
        name, template = LEGIT_TEMPLATES[g % len(LEGIT_TEMPLATES)]
        start = rng.uniform(0, config.hours - 12)
        size = min(config.users, rng.randint(500, 3000))
        legit_groups.append({"id": g, "name": name, "template": template})
        pool = [_fill(template, rng) for _ in range(30)]  # personalised numbers and dates
        for user in rng.sample(range(config.users), size):
            events.append((start + rng.uniform(0, 12), user, rng.choice(pool), "legit", g, 0))
    for _ in range(int(config.users * config.background_ham_per_user)):
        events.append((rng.uniform(0, config.hours), rng.randrange(config.users), rng.choice(ham_pool), "ham", -1, 0))
    events.sort(key=lambda e: e[0])

    detector = Detector(config, rng)
    detector.prepare([e[2] for e in events])
    fps = _FP_CACHE

    def fp_of(text):
        if text not in fps:
            fps[text] = fingerprint(text)
        return fps[text]

    # Verified senders register their templates with the hub (defence).
    target_name, target_template = next(t for t in LEGIT_TEMPLATES if t[0] == config.attack_target)
    if config.defences:
        allow_rng = random.Random(0)
        for name, template in LEGIT_TEMPLATES:
            if name in config.allowlisted:
                for _ in range(3):
                    hub.allow(fingerprint=fingerprint(_fill(template, allow_rng)))

    attackers = []
    origins = {}  # cluster -> reporting sources (simulation bookkeeping only; the hub never sees this)
    stats = {"scam": {"exposures": 0, "model": 0, "combined": 0, "network_only": 0,
                      "by_level": [{"exposures": 0, "model": 0, "combined": 0} for _ in range(4)]},
             "legit": {"exposures": 0, "model_alerts": 0, "network_alerts": 0},
             "ham": {"exposures": 0, "model_alerts": 0, "network_alerts": 0},
             "reports": {"sent": 0, "rejected": {}}}
    series = []
    next_sync = 0.0
    next_tick = 0.0
    tick = config.tick_minutes / 60
    campaign_seen_after = {c["id"]: [0, 0] for c in campaigns}  # exposures after publication, protected

    for hour, user_index, text, kind, group, level in events:
        while next_tick <= hour:
            clock["hour"] = next_tick
            if next_tick >= next_sync:
                feed.sync()
                next_sync += config.sync_minutes / 60
            if config.attackers and not attackers and next_tick >= config.attack_hour - 1:
                attackers = [hub.register(next_tick) for _ in range(config.attackers)]
            if attackers and next_tick >= config.attack_hour:
                target = fingerprint(_fill(target_template, rng), "smishing", 0.95)
                for client in attackers:
                    try:
                        hub.report(client, target, next_tick)
                    except RejectedReport as error:
                        stats["reports"]["rejected"][str(error)] = stats["reports"]["rejected"].get(str(error), 0) + 1
            series.append({"hour": round(next_tick, 3), "scam_exposures": stats["scam"]["exposures"],
                           "model": stats["scam"]["model"], "combined": stats["scam"]["combined"],
                           "published": sum(1 for c in campaigns if c["published_hour"] is not None)})
            if live_delay:
                hub.set_clock(next_tick)
                hub._set_meta("simulation", json.dumps(_live_summary(config, stats, series, campaigns)))
                time.sleep(live_delay)
            next_tick += tick
        clock["hour"] = hour
        user = users[user_index]
        flagged, category, score = detector(text, kind, level)
        fp = fp_of(text)
        matched = feed.match(text, fp) is not None if fp else False
        if kind == "scam":
            s = stats["scam"]
            s["exposures"] += 1; s["by_level"][level]["exposures"] += 1
            s["model"] += flagged; s["by_level"][level]["model"] += flagged
            protected = flagged or matched
            s["combined"] += protected; s["by_level"][level]["combined"] += protected
            s["network_only"] += matched and not flagged
            origin = s.setdefault("by_origin", {}).setdefault("modern" if campaigns[group]["modern"] else "sms_test_split",
                                                             {"exposures": 0, "model": 0, "combined": 0})
            origin["exposures"] += 1; origin["model"] += flagged; origin["combined"] += protected
            camp = campaigns[group]
            if camp["published_hour"] is not None and hour >= camp["published_hour"] + config.sync_minutes / 60:
                campaign_seen_after[group][0] += 1
                campaign_seen_after[group][1] += protected
        else:
            bucket = stats[kind]
            bucket["exposures"] += 1
            bucket["model_alerts"] += flagged
            bucket["network_alerts"] += matched
            if matched and user["shares"] and fp and rng.random() < config.dispute_rate:
                try:
                    hub.dispute(user["id"], fp, hour)
                    stats["reports"]["disputes"] = stats["reports"].get("disputes", 0) + 1
                except RejectedReport as error:
                    stats["reports"]["rejected"][str(error)] = stats["reports"]["rejected"].get(str(error), 0) + 1
        manual = (not flagged and user["shares"] and fp is not None and
                  rng.random() < (config.user_report_rate if kind == "scam" else config.mistaken_report_rate))
        if manual:
            stats["reports"]["manual"] = stats["reports"].get("manual", 0) + 1
        if (flagged or manual) and user["shares"] and fp:
            report = dict(fp, category="user" if manual else category if category in ("spam", "smishing") else "spam")
            if not manual:
                report["score_bucket"] = min(int(score * 10), 9) / 10
            try:
                cluster = hub.report(user["id"], report, hour)
                stats["reports"]["sent"] += 1
                origins.setdefault(cluster, {}).setdefault(f"{kind}:{group}", 0)
                origins[cluster][f"{kind}:{group}"] += 1
                if kind == "scam" and campaigns[group]["published_hour"] is None:
                    status = hub.db.execute("SELECT status, published_hour FROM clusters WHERE id=?", (cluster,)).fetchone()
                    if status[0] == "published":
                        campaigns[group]["published_hour"] = status[1]
                        campaigns[group]["cluster"] = cluster
            except RejectedReport as error:
                stats["reports"]["rejected"][str(error)] = stats["reports"]["rejected"].get(str(error), 0) + 1
        if progress and stats["scam"]["exposures"] % 5000 == 0 and kind == "scam":
            progress(hour)

    # ---- results ----
    exposures_before = {}
    for hour, _, _, kind, group, _ in events:
        if kind == "scam":
            published = campaigns[group]["published_hour"]
            if published is None or hour < published:
                exposures_before[group] = exposures_before.get(group, 0) + 1
    detection = []
    for camp in campaigns:
        first = min((e[0] for e in events if e[3] == "scam" and e[4] == camp["id"]), default=camp["start"])
        known = camp["published_hour"] is not None and camp["published_hour"] <= first
        detection.append({"campaign": camp["id"], "modern": camp["modern"], "size": camp["size"], "published": camp["published_hour"] is not None,
                          # Already covered: a related earlier campaign was published before this one began.
                          "already_covered": known,
                          "hours_to_publish": None if camp["published_hour"] is None or known else round(camp["published_hour"] - first, 2),
                          "exposures_before_publish": exposures_before.get(camp["id"], 0),
                          "linked_sources": origins.get(camp.get("cluster"), {}), "first_exposure": round(first, 2),
                          "published_hour": camp["published_hour"]})
    published = [d for d in detection if d["published"] and not d["already_covered"]]
    after = [v for v in campaign_seen_after.values() if v[0]]
    clusters = dict(hub.db.execute("SELECT status, COUNT(*) FROM clusters GROUP BY status").fetchall())
    legit_published = _legit_published(hub, legit_groups, rng)
    s = stats["scam"]
    result = {
        "config": {k: v for k, v in asdict(config).items() if k != "extra"},
        "detector_version": (detector.service.manifest["model_version"] if detector.service else "rates"),
        "scam": {
            "exposures": s["exposures"],
            "model_only_protection": _rate(s["model"], s["exposures"]),
            "model_plus_network_protection": _rate(s["combined"], s["exposures"]),
            "network_only_saves": s["network_only"],
            "by_mutation_level": [{"level": i, "exposures": b["exposures"], "model": _rate(b["model"], b["exposures"]),
                                   "combined": _rate(b["combined"], b["exposures"])} for i, b in enumerate(s["by_level"])],
            "protection_after_publication": _rate(sum(v[1] for v in after), sum(v[0] for v in after)),
            "by_campaign_origin": {name: {"exposures": b["exposures"], "model": _rate(b["model"], b["exposures"]),
                                          "combined": _rate(b["combined"], b["exposures"])}
                                   for name, b in s.get("by_origin", {}).items()},
        },
        "campaigns": {"total": len(campaigns), "newly_published": len(published),
                      "already_covered_by_earlier_campaign": sum(d["already_covered"] for d in detection),
                      "never_published": sum(not d["published"] for d in detection),
                      "median_hours_to_publish": _median([d["hours_to_publish"] for d in published]),
                      "median_exposures_before_publish": _median([d["exposures_before_publish"] for d in published]),
                      "detail": detection},
        "legit": {**stats["legit"], "false_alert_rate_model": _rate(stats["legit"]["model_alerts"], stats["legit"]["exposures"]),
                  "false_alert_rate_network": _rate(stats["legit"]["network_alerts"], stats["legit"]["exposures"]),
                  "templates_published_as_campaigns": legit_published,
                  "templates_ever_published": _legit_published(hub, legit_groups, rng, ("published", "disputed")),
                  "templates_held_for_review": _legit_published(hub, legit_groups, rng, ("held_for_review",))},
        "ham": {**stats["ham"], "false_alert_rate_network": _rate(stats["ham"]["network_alerts"], stats["ham"]["exposures"])},
        "poisoning": {"attackers": config.attackers, "defences": config.defences,
                      "target": target_name, "target_published_at_end": target_name in legit_published,
                      "target_ever_published": target_name in _legit_published(hub, legit_groups, rng, ("published", "disputed"))},
        "hub": {"clusters": clusters, "reports": stats["reports"],
                "published_cluster_origins": _origin_summary(hub, origins)},
        "privacy": privacy_audit(hub, [e[2] for e in events]),
        "series": series[:: max(1, len(series) // 150)],
    }
    if live_delay:
        hub.set_clock(config.hours)
        hub._set_meta("simulation", json.dumps({**_live_summary(config, stats, series, campaigns), "finished": True}))
    return result


def _origin_summary(hub, origins):
    """What kind of traffic built each published cluster (scam / legit / ham / mixed)."""
    summary = {}
    for (cluster,) in hub.db.execute("SELECT id FROM clusters WHERE status='published'"):
        kinds = {key.split(":")[0] for key in origins.get(cluster, {})} or {"attack"}
        label = kinds.pop() if len(kinds) == 1 else "mixed"
        summary[label] = summary.get(label, 0) + 1
    return summary


def _legit_published(hub, groups, rng, statuses=("published",)):
    """Legitimate senders whose messages match a cluster in one of `statuses`."""
    from .fingerprint import similarity
    marks = ",".join("?" * len(statuses))
    rows = hub.db.execute(f"SELECT signature FROM clusters WHERE status IN ({marks})", statuses).fetchall()
    names = set()
    for (signature,) in rows:
        signature = json.loads(signature)
        for group in groups:
            if similarity(fingerprint(_fill(group["template"], rng))["signature"], signature) >= 0.4:
                names.add(group["name"])
    return sorted(names)


def privacy_audit(hub, texts, sample=3000):
    """Confirm no message text is stored: no 3-word sequence of any message appears in the hub database."""
    dump = "\n".join(hub.db.iterdump()).lower()
    rng = random.Random(0)
    found = 0
    checked = 0
    for text in rng.sample(list(dict.fromkeys(texts)), min(sample, len(set(texts)))):
        words = re.findall(r"[a-z]{3,}", text.lower())
        for i in range(0, max(len(words) - 2, 0), 3):
            checked += 1
            if " ".join(words[i:i + 3]) in dump:
                found += 1
    return {"columns": hub.stored_columns(), "three_word_sequences_checked": checked,
            "found_in_hub_database": found, "passed": found == 0}


def _live_summary(config, stats, series, campaigns):
    s = stats["scam"]
    return {"users": config.users, "hours": config.hours, "k": config.k, "detector": config.detector,
            "scam_exposures": s["exposures"], "model_protected": s["model"], "combined_protected": s["combined"],
            "network_only_saves": s["network_only"],
            "campaigns_published": sum(1 for c in campaigns if c["published_hour"] is not None),
            "campaigns_total": len(campaigns), "series": series[:: max(1, len(series) // 200)] + series[-1:]}


def _rate(part, whole):
    return round(part / whole, 4) if whole else None


def _median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else round((values[mid - 1] + values[mid]) / 2, 2)
