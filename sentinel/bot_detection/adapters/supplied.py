"""User-supplied data: uploaded post exports (JSON or CSV) and manually entered metadata.

Upload JSON: {"profile": {...}, "posts": [{"timestamp", "text", "is_repost", "likes", "replies", "shares"}]}
Upload CSV: header row with timestamp,text[,is_repost,likes,replies,shares]
Profile keys: created_at, display_name, bio, has_profile_image, default_profile_image, verified,
website, followers, following, total_posts, follower_history [[timestamp, count], ...]
"""

import csv
import io
from datetime import timedelta

from . import AccountData, Post, parse_time

MAX_POSTS = 3000
MAX_TEXT = 5000
MAX_CSV_CHARS = 1_500_000


class InvalidData(ValueError):
    pass


def _count(value, field):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise InvalidData(f"{field} must be a whole number.")
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise InvalidData(f"{field} must be a whole number.") from None
    if number < 0 or number > 10 ** 10:
        raise InvalidData(f"{field} is out of range.")
    return number


def _flag(value, field):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "yes", "1", "y"):
        return True
    if text in ("false", "no", "0", "n"):
        return False
    raise InvalidData(f"{field} must be true or false.")


def _text(value, limit, field):
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        raise InvalidData(f"{field} must be text.")
    return str(value)[:limit]


def apply_profile(data, profile):
    if not isinstance(profile, dict):
        raise InvalidData("profile must be an object.")
    created = profile.get("created_at")
    data.created_at = parse_time(created)
    if created not in (None, "") and data.created_at is None:
        raise InvalidData("created_at must be an ISO date or Unix time.")
    age = _count(profile.get("account_age_days"), "account_age_days")
    if age is not None and data.created_at is None:
        data.created_at = data.fetched_at - timedelta(days=age)
    data.display_name = _text(profile.get("display_name"), 200, "display_name")
    data.bio = _text(profile.get("bio"), 2000, "bio")
    data.website = _text(profile.get("website"), 500, "website")
    data.has_profile_image = _flag(profile.get("has_profile_image"), "has_profile_image")
    data.default_profile_image = _flag(profile.get("default_profile_image"), "default_profile_image")
    data.verified = _flag(profile.get("verified"), "verified")
    data.followers = _count(profile.get("followers"), "followers")
    data.following = _count(profile.get("following"), "following")
    data.total_posts = _count(profile.get("total_posts"), "total_posts")
    history = profile.get("follower_history") or []
    if not isinstance(history, list) or len(history) > 1000:
        raise InvalidData("follower_history must be a list of [timestamp, count] pairs (at most 1000).")
    for entry in history:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2 or parse_time(entry[0]) is None:
            raise InvalidData("follower_history entries must be [timestamp, count].")
        data.follower_history.append((parse_time(entry[0]), _count(entry[1], "follower_history count")))
    data.follower_history.sort()


def _post(row, index):
    if not isinstance(row, dict):
        raise InvalidData(f"Post {index + 1} must be an object.")
    moment = parse_time(row.get("timestamp"))
    if moment is None:
        raise InvalidData(f"Post {index + 1} needs a valid timestamp (ISO-8601 or Unix seconds).")
    return Post(timestamp=moment, text=_text(row.get("text"), MAX_TEXT, "text") or "",
                is_repost=bool(_flag(row.get("is_repost"), "is_repost")),
                likes=_count(row.get("likes"), "likes"), replies=_count(row.get("replies"), "replies"),
                shares=_count(row.get("shares"), "shares"))


def from_upload(account, upload):
    """upload = {"format": "json", "profile": {...}, "posts": [...]} or {"format": "csv", "content": "..."}."""
    if not isinstance(upload, dict):
        raise InvalidData("Upload must be an object.")
    data = AccountData(platform=account["platform"], username=account["username"], source="upload")
    if upload.get("format") == "csv":
        content = upload.get("content")
        if not isinstance(content, str) or len(content) > MAX_CSV_CHARS:
            raise InvalidData("CSV content is missing or too large.")
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames or "timestamp" not in [f.strip().lower() for f in reader.fieldnames]:
            raise InvalidData("The CSV needs a header row with at least a timestamp column.")
        rows = [{(k or "").strip().lower(): v for k, v in row.items()} for row in reader]
    elif upload.get("format", "json") == "json":
        rows = upload.get("posts") or []
        if not isinstance(rows, list):
            raise InvalidData("posts must be a list.")
    else:
        raise InvalidData("Upload format must be json or csv.")
    if len(rows) > MAX_POSTS:
        raise InvalidData(f"At most {MAX_POSTS} posts can be analysed at once.")
    if upload.get("profile") is not None:
        apply_profile(data, upload["profile"])
    data.posts = [_post(row, i) for i, row in enumerate(rows)]
    if data.total_posts is None and data.posts:
        data.total_posts = len(data.posts)
    data.limitations.append("Analysis uses only the data you supplied; Sentinel cannot verify that it is complete or genuine.")
    return data


def from_manual(account, profile):
    data = AccountData(platform=account["platform"], username=account["username"], source="manual")
    apply_profile(data, profile or {})
    data.limitations.append("Only profile metadata was supplied; activity and content patterns cannot be assessed.")
    return data
