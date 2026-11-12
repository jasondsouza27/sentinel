"""Behavioural and content features from AccountData.

Every feature is a number or None. None means the data needed for it was not
available; scoring then leaves the signal out instead of guessing.
"""

import math
import re
import statistics
from collections import Counter
from datetime import timedelta

from ..analysis import PAYMENT_RE, SECRET_RE, URGENCY_RE
from ..network.fingerprint import fingerprint, similarity

URL = re.compile(r"https?://[^\s<>\"']+|\bwww\.[^\s<>\"']+", re.IGNORECASE)
HASHTAG = re.compile(r"(?<!\w)#\w+")
MENTION = re.compile(r"(?<!\w)@\w+")
PROMO = re.compile(r"\b(follow back|f4f|dm for promo|crypto|forex|giveaway|earn \$?\d+|click (the )?link|free followers|onlyfans|nft)\b",
                   re.IGNORECASE)
MIN_POSTS_FOR_TIMING = 5
NEAR_DUPLICATE = 0.8
MAX_PAIRWISE = 400  # posts compared for near-duplicates (pairs grow quadratically)


def _ratio(part, whole):
    return part / whole if whole else None


def username_features(username):
    digits = sum(c.isdigit() for c in username)
    trailing = re.search(r"\d+$", username)
    letters = re.sub(r"[^a-z]", "", username.lower())
    # Long consonant runs and very mixed case suggest generated handles.
    consonant_run = max((len(m) for m in re.findall(r"[bcdfghjklmnpqrstvwxz]+", letters)), default=0)
    return {
        "username_digit_ratio": round(digits / len(username), 3) if username else None,
        "username_trailing_digits": len(trailing.group(0)) if trailing else 0,
        "username_consonant_run": consonant_run,
    }


def profile_features(data):
    present = [bool(data.display_name), bool(data.bio and data.bio.strip()),
               data.has_profile_image is True and data.default_profile_image is not True, bool(data.website)]
    known = [data.display_name is not None, data.bio is not None, data.has_profile_image is not None, data.website is not None]
    age = (data.fetched_at - data.created_at).days if data.created_at else None
    return {
        "account_age_days": max(age, 0) if age is not None else None,
        "profile_completeness": round(sum(p for p, k in zip(present, known) if k) / sum(known), 3) if sum(known) >= 2 else None,
        "default_or_missing_image": (None if data.has_profile_image is None
                                     else float(not data.has_profile_image or data.default_profile_image is True)),
        "bio_promotional": float(bool(PROMO.search(data.bio or "") or URL.search(data.bio or ""))) if data.bio is not None else None,
        "verified": None if data.verified is None else float(bool(data.verified)),
    }


def activity_features(posts, fetched_at):
    if not posts:
        return {}
    times = sorted(p.timestamp for p in posts)
    span_days = max((times[-1] - times[0]).total_seconds() / 86400, 1 / 24)
    out = {"posts_analysed": len(posts), "span_days": round(span_days, 2),
           "posts_per_day": round(len(posts) / span_days, 2) if len(posts) >= MIN_POSTS_FOR_TIMING else None,
           "repost_ratio": round(sum(p.is_repost for p in posts) / len(posts), 3)}
    if len(posts) >= MIN_POSTS_FOR_TIMING:
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
        positive = [g for g in gaps if g > 0]
        mean = statistics.fmean(positive) if positive else 0
        out["interval_cv"] = round(statistics.pstdev(positive) / mean, 3) if len(positive) >= 3 and mean else None
        # Share of gaps within 60 s of the most common gap: clock-driven schedulers repeat one gap.
        if positive:
            common = Counter(round(g / 60) for g in positive).most_common(1)[0][0] * 60
            out["regular_interval_share"] = round(sum(abs(g - common) <= 60 for g in positive) / len(positive), 3)
        out["burst_share"] = round(sum(g < 10 for g in gaps) / len(gaps), 3) if gaps else None
        hours = Counter(t.hour for t in times)
        out["active_hours"] = len(hours)
        probabilities = [c / len(times) for c in hours.values()]
        out["hour_entropy"] = round(-sum(p * math.log2(p) for p in probabilities) / math.log2(24), 3)
        # Humans sleep: the quietest 6-hour window normally holds very few posts.
        out["night_gap_share"] = round(min(sum(hours.get((start + h) % 24, 0) for h in range(6))
                                           for start in range(24)) / len(times), 3)
        out["hour_histogram"] = [hours.get(h, 0) for h in range(24)]
        days = Counter(t.date() for t in times)
        out["daily_counts"] = [[day.isoformat(), days[day]] for day in sorted(days)][-90:]
        recent = sum(1 for t in times if t >= times[-1] - timedelta(days=7))
        earlier_days = max(span_days - 7, 0)
        if earlier_days >= 14:
            earlier_rate = (len(times) - recent) / earlier_days
            out["activity_change_ratio"] = round((recent / 7) / earlier_rate, 2) if earlier_rate else None
    return out


def content_features(posts):
    texts = [p.text for p in posts if p.text and p.text.strip()]
    if len(texts) < 3:
        return {}
    normalised = Counter(re.sub(r"\s+", " ", t.lower()).strip() for t in texts)
    exact_dupes = sum(c - 1 for c in normalised.values() if c > 1)
    sample = texts[-MAX_PAIRWISE:]
    prints = [fingerprint(t) for t in sample]
    near = set()
    for i in range(len(prints)):
        for j in range(i + 1, len(prints)):
            if prints[i] and prints[j] and similarity(prints[i]["signature"], prints[j]["signature"]) >= NEAR_DUPLICATE:
                near.update((i, j))
    urls = [u.lower() for t in texts for u in URL.findall(t)]
    domains = Counter(re.sub(r"^(https?://)?(www\.)?", "", u).split("/")[0] for u in urls)
    tokens = [w for t in texts for w in re.findall(r"[a-z']+", t.lower())]
    spammy = sum(bool(PAYMENT_RE.search(t) or SECRET_RE.search(t) or URGENCY_RE.search(t) or PROMO.search(t)) for t in texts)
    return {
        "exact_duplicate_share": round(exact_dupes / len(texts), 3),
        "near_duplicate_share": round(len(near) / len(sample), 3),
        "hashtags_per_post": round(sum(len(HASHTAG.findall(t)) for t in texts) / len(texts), 2),
        "mentions_per_post": round(sum(len(MENTION.findall(t)) for t in texts) / len(texts), 2),
        "urls_per_post": round(len(urls) / len(texts), 2),
        "top_domain_share": round(domains.most_common(1)[0][1] / len(urls), 3) if len(urls) >= 3 else None,
        "vocabulary_diversity": round(len(set(tokens)) / len(tokens), 3) if len(tokens) >= 50 else None,
        "spam_language_share": round(spammy / len(texts), 3),
    }


def engagement_features(data):
    out = {}
    if data.followers is not None and data.following is not None:
        out["following_to_followers"] = round(data.following / max(data.followers, 1), 2)
        out["following_count"] = data.following
    measured = [p for p in data.posts if p.likes is not None]
    if len(measured) >= 5:
        totals = [p.likes + (p.replies or 0) + (p.shares or 0) for p in measured]
        mean = statistics.fmean(totals)
        if data.followers:
            out["engagement_rate"] = round(mean / data.followers, 4)
        out["engagement_cv"] = round(statistics.pstdev(totals) / mean, 3) if mean > 0 else None
    if len(data.follower_history) >= 2:
        growth = []
        for (t1, c1), (t2, c2) in zip(data.follower_history, data.follower_history[1:]):
            days = (t2 - t1).total_seconds() / 86400
            if days > 0 and c1 is not None and c2 is not None:
                growth.append((c2 - c1) / max(c1, 10) / days)
        if growth:
            out["max_daily_follower_growth"] = round(max(growth), 3)
    return out


def extract(data):
    features = {}
    features.update(username_features(data.username))
    features.update(profile_features(data))
    features.update(activity_features(data.posts, data.fetched_at))
    features.update(content_features(data.posts))
    features.update(engagement_features(data))
    return features
