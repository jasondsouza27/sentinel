"""Profile-metadata features shared by training and inference (stdlib only).

Inputs are what Sentinel can obtain for an account: follower, following and post
counts, account age, bio, username, display name and whether a link is set.

Deliberately excluded:
- verified: in the training data nearly all verified accounts come from the
  human-only verified/celebrity sets, so it would leak the dataset label;
- default profile picture: missing for every midterm-2018 account (84% bots),
  so "unknown" would identify that dataset;
- likes and list counts: Sentinel's inputs do not collect them.
"""

import math
import re

FEATURES = ["log_followers", "log_following", "log_posts", "log_age_days", "log_posts_per_day",
            "log_followers_per_day", "log_following_per_day", "follow_balance", "bio_length", "has_bio",
            "username_length", "username_digits", "username_digit_ratio", "display_name_length",
            "display_name_digits", "has_url"]
REQUIRED = ("followers", "following", "posts", "age_days")


def vector(account):
    """Feature list in FEATURES order, or None if a required count is missing."""
    if any(account.get(k) is None for k in REQUIRED):
        return None
    followers, following, posts = (max(int(account[k]), 0) for k in ("followers", "following", "posts"))
    age = max(float(account["age_days"]), 1.0)
    bio = account.get("bio") or ""
    username = account.get("username") or ""
    name = account.get("display_name") or ""
    digits = sum(c.isdigit() for c in username)
    return [math.log1p(followers), math.log1p(following), math.log1p(posts), math.log1p(age),
            math.log1p(posts / age), math.log1p(followers / age), math.log1p(following / age),
            math.log1p(following) - math.log1p(followers), min(len(bio), 300), float(bool(bio.strip())),
            len(username), digits, digits / len(username) if username else 0.0,
            len(name), len(re.findall(r"\d", name)), float(bool(account.get("has_url")))]


# ---------- activity + content features (from post histories) ----------
ACTIVITY_FEATURES = ["posts_per_day", "repost_ratio", "interval_cv", "regular_interval_share", "burst_share",
                     "active_hours", "hour_entropy", "night_gap_share", "exact_duplicate_share",
                     "near_duplicate_share", "hashtags_per_post", "mentions_per_post", "urls_per_post",
                     "top_domain_share", "vocabulary_diversity", "spam_language_share", "mean_likes_log"]
POSTS_PER_ACCOUNT = 100
MIN_POSTS = 20


def account_features(posts):
    """Activity/content features from the most recent POSTS_PER_ACCOUNT posts, using the same
    functions the app applies to uploads (training and inference share this)."""
    from .. import features as app_features
    posts = sorted(posts, key=lambda p: p.timestamp)[-POSTS_PER_ACCOUNT:]
    out = app_features.activity_features(posts, posts[-1].timestamp)
    out.update(app_features.content_features(posts))
    for key in ("hour_histogram", "daily_counts"):
        out.pop(key, None)
    likes = [p.likes for p in posts if p.likes is not None]
    out["mean_likes_log"] = round(sum(math.log1p(max(v, 0)) for v in likes) / len(likes), 4) if likes else None
    return out


def activity_vector(activity, profile):
    """Activity features (NaN when missing) followed by the profile features."""
    base = vector(profile)
    if base is None:
        return None
    return [float("nan") if activity.get(k) is None else float(activity[k]) for k in ACTIVITY_FEATURES] + base
