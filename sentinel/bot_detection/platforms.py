"""Supported platforms and safe parsing of account identifiers.

A profile URL is only *parsed* to extract the account name; it is never fetched.
Hosts must match an exact allowlist, so a URL cannot point the server anywhere
else (no SSRF). Adapters call fixed official API hosts with the parsed name.
"""

import re
from urllib.parse import unquote, urlsplit


class InvalidAccount(ValueError):
    pass


PLATFORMS = {
    "x": {
        "name": "X (Twitter)", "hosts": {"x.com", "twitter.com", "mobile.twitter.com"},
        "username": re.compile(r"^[A-Za-z0-9_]{1,15}$"), "api": None,
        "api_note": "X's API requires a paid plan; upload an export of the account's posts or enter metadata.",
    },
    "instagram": {
        "name": "Instagram", "hosts": {"instagram.com"},
        "username": re.compile(r"^(?!.*\.\.)[A-Za-z0-9._]{1,30}$"), "api": None,
        "api_note": "Instagram's Graph API only covers accounts you manage; upload data or enter metadata.",
    },
    "facebook": {
        "name": "Facebook", "hosts": {"facebook.com", "m.facebook.com", "fb.com"},
        "username": re.compile(r"^[A-Za-z0-9.]{5,50}$"), "api": None,
        "api_note": "Facebook's Graph API only covers pages and accounts you manage; upload data or enter metadata.",
    },
    "reddit": {
        "name": "Reddit", "hosts": {"reddit.com", "old.reddit.com", "new.reddit.com"},
        "username": re.compile(r"^[A-Za-z0-9_-]{3,20}$"), "api": "reddit",
        "api_note": "Official Reddit API (needs REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET and REDDIT_USER_AGENT).",
    },
    "youtube": {
        "name": "YouTube", "hosts": {"youtube.com", "m.youtube.com"},
        "username": re.compile(r"^[A-Za-z0-9._-]{3,30}$"), "api": "youtube",
        "api_note": "Official YouTube Data API v3 (needs YOUTUBE_API_KEY).",
    },
}
RESERVED_PATHS = {"home", "explore", "search", "settings", "login", "signup", "i", "intent", "share", "hashtag",
                  "p", "reel", "reels", "stories", "watch", "results", "feed", "r", "messages", "notifications"}
CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


def _from_url(platform, value):
    try:
        parts = urlsplit(value)
    except ValueError as error:
        raise InvalidAccount("The profile URL could not be parsed.") from error
    if parts.scheme not in ("http", "https"):
        raise InvalidAccount("Only http(s) profile URLs are accepted.")
    if parts.username or parts.password or parts.port:
        raise InvalidAccount("Profile URLs must not contain credentials or a port.")
    host = (parts.hostname or "").lower().rstrip(".")
    host = host[4:] if host.startswith("www.") else host
    spec = PLATFORMS[platform]
    if host not in spec["hosts"]:
        raise InvalidAccount(f"That URL is not a profile address on {spec['name']}.")
    segments = [unquote(s) for s in parts.path.split("/") if s]
    if not segments:
        raise InvalidAccount("The URL does not name an account.")
    if platform == "reddit":
        if len(segments) < 2 or segments[0] not in ("user", "u"):
            raise InvalidAccount("Use a Reddit profile URL such as reddit.com/user/name.")
        return {"username": segments[1], "kind": "username"}
    if platform == "youtube":
        first = segments[0]
        if first.startswith("@"):
            return {"username": first[1:], "kind": "handle"}
        if first == "channel" and len(segments) > 1 and CHANNEL_ID.match(segments[1]):
            return {"username": segments[1], "kind": "channel_id"}
        if first in ("c", "user") and len(segments) > 1:
            return {"username": segments[1], "kind": "handle"}
        raise InvalidAccount("Use a YouTube channel URL such as youtube.com/@handle.")
    if platform == "facebook" and segments[0] == "profile.php":
        raise InvalidAccount("Numeric Facebook profile links are not supported; enter the page username.")
    if segments[0].lower() in RESERVED_PATHS:
        raise InvalidAccount("The URL points to a page, not an account.")
    return {"username": segments[0], "kind": "username"}


def parse_account(platform, value):
    """Return {platform, username, kind} or raise InvalidAccount. Never performs network access."""
    if platform not in PLATFORMS:
        raise InvalidAccount("Unsupported platform.")
    if not isinstance(value, str) or not value.strip():
        raise InvalidAccount("Enter a username or a profile URL.")
    value = value.strip()
    if len(value) > 300:
        raise InvalidAccount("The account identifier is too long.")
    looks_like_url = "://" in value or value.lower().startswith(("www.",) + tuple(h + "/" for h in PLATFORMS[platform]["hosts"]))
    if looks_like_url:
        parsed = _from_url(platform, value if "://" in value else "https://" + value)
    else:
        name = value
        for prefix in ("@", "/u/", "u/"):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        kind = "channel_id" if platform == "youtube" and CHANNEL_ID.match(name) else (
            "handle" if platform == "youtube" else "username")
        parsed = {"username": name, "kind": kind}
    if parsed["kind"] != "channel_id" and not PLATFORMS[platform]["username"].match(parsed["username"]):
        raise InvalidAccount(f"That is not a valid username on {PLATFORMS[platform]['name']}.")
    return {"platform": platform, **parsed}


def describe(api_available):
    """Platform list for the UI, including which data sources are usable right now."""
    return [{"id": key, "name": spec["name"],
             "sources": (["api"] if spec["api"] and api_available.get(spec["api"]) else []) + ["upload", "manual"],
             "api_configured": bool(spec["api"] and api_available.get(spec["api"])),
             "api_note": spec["api_note"]}
            for key, spec in PLATFORMS.items()]
