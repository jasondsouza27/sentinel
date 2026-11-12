"""Reddit official API adapter (application-only OAuth; credentials from the environment)."""

import base64
import os
import threading
import time
from urllib.parse import quote, urlencode

from . import AccountData, Post, SourceUnavailable, UpstreamError, parse_time
from .http import request_json

_token = {"value": None, "expires": 0.0}
_lock = threading.Lock()
MAX_ITEMS = 100


def configured():
    return all(os.environ.get(k) for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT"))


def _headers(fetch_json):
    if not configured():
        raise SourceUnavailable("api_not_configured",
                                "Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET and REDDIT_USER_AGENT to use the Reddit API.")
    agent = os.environ["REDDIT_USER_AGENT"]
    with _lock:
        if not _token["value"] or time.time() > _token["expires"] - 60:
            basic = base64.b64encode(f"{os.environ['REDDIT_CLIENT_ID']}:{os.environ['REDDIT_CLIENT_SECRET']}".encode()).decode()
            reply = fetch_json("https://www.reddit.com/api/v1/access_token",
                               headers={"Authorization": "Basic " + basic, "User-Agent": agent,
                                        "Content-Type": "application/x-www-form-urlencoded"},
                               data=b"grant_type=client_credentials")
            if "access_token" not in reply:
                raise UpstreamError("auth_failed", "Reddit did not issue an access token.")
            _token.update(value=reply["access_token"], expires=time.time() + float(reply.get("expires_in", 3600)))
        return {"Authorization": "Bearer " + _token["value"], "User-Agent": agent}


def fetch(account, fetch_json=request_json):
    headers = _headers(fetch_json)
    name = quote(account["username"], safe="")
    about = fetch_json(f"https://oauth.reddit.com/user/{name}/about", headers=headers).get("data") or {}
    if about.get("is_suspended"):
        raise SourceUnavailable("account_suspended", "Reddit reports this account as suspended.")
    icon = (about.get("icon_img") or "").split("?")[0]
    data = AccountData(platform="reddit", username=account["username"], source="reddit_api",
                       created_at=parse_time(about.get("created_utc")),
                       display_name=(about.get("subreddit") or {}).get("title") or None,
                       bio=(about.get("subreddit") or {}).get("public_description") or "",
                       has_profile_image=bool(icon), default_profile_image=("avatar_default" in icon) if icon else None,
                       verified=about.get("verified"))
    data.limitations.append("Reddit does not expose follower or following counts through this API.")
    for kind in ("submitted", "comments"):
        listing = fetch_json(f"https://oauth.reddit.com/user/{name}/{kind}?" + urlencode({"limit": MAX_ITEMS, "raw_json": 1}),
                             headers=headers)
        for child in (listing.get("data") or {}).get("children") or []:
            d = child.get("data") or {}
            moment = parse_time(d.get("created_utc"))
            if not moment:
                continue
            if kind == "comments":
                text = d.get("body") or ""
            else:
                text = f"{d.get('title', '')}\n{d.get('selftext', '')}"
                if d.get("url") and not d.get("is_self"):
                    text += "\n" + d["url"]
            data.posts.append(Post(timestamp=moment, text=text.strip(), is_repost=bool(d.get("crosspost_parent")),
                                   likes=d.get("score"), replies=d.get("num_comments")))
    data.total_posts = len(data.posts) or None
    data.limitations.append(f"At most the latest {MAX_ITEMS} posts and {MAX_ITEMS} comments are analysed.")
    return data
