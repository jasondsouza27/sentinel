"""Platform data adapters. Each returns an AccountData built only from official
APIs, user-uploaded data or user-entered metadata. Nothing is scraped or stored."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


class SourceUnavailable(Exception):
    """The requested data source cannot be used (not configured, unsupported, account missing)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class UpstreamError(Exception):
    """An official API failed or rate-limited us."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass
class Post:
    timestamp: datetime
    text: str = ""
    is_repost: bool = False
    likes: int | None = None
    replies: int | None = None
    shares: int | None = None


@dataclass
class AccountData:
    platform: str
    username: str
    source: str  # "youtube_api", "reddit_api", "upload", "manual"
    created_at: datetime | None = None
    display_name: str | None = None
    bio: str | None = None
    has_profile_image: bool | None = None
    default_profile_image: bool | None = None
    verified: bool | None = None
    website: str | None = None
    followers: int | None = None
    following: int | None = None
    total_posts: int | None = None
    follower_history: list = field(default_factory=list)  # [(datetime, count)]
    posts: list = field(default_factory=list)
    limitations: list = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def parse_time(value):
    """ISO-8601 string or Unix seconds -> aware UTC datetime; None if missing/invalid."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        text = str(value).strip()
        if text.replace(".", "", 1).isdigit():  # Unix seconds supplied as text (e.g. from CSV)
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        text = text.replace("Z", "+00:00")
        moment = datetime.fromisoformat(text)
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
