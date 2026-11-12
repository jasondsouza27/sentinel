"""YouTube Data API v3 adapter (public channel data, API key from YOUTUBE_API_KEY)."""

import os
from urllib.parse import urlencode

from . import AccountData, Post, SourceUnavailable, UpstreamError, parse_time
from .http import request_json

BASE = "https://www.googleapis.com/youtube/v3/"
MAX_VIDEOS = 50


def configured():
    return bool(os.environ.get("YOUTUBE_API_KEY"))


def fetch(account, fetch_json=request_json):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise SourceUnavailable("api_not_configured", "Set YOUTUBE_API_KEY to use the YouTube Data API.")
    selector = {"id": account["username"]} if account["kind"] == "channel_id" else {"forHandle": "@" + account["username"]}
    channels = fetch_json(BASE + "channels?" + urlencode({"part": "snippet,statistics,contentDetails", "key": key, **selector}))
    items = channels.get("items") or []
    if not items:
        raise UpstreamError("not_found", "YouTube did not find that channel.")
    channel = items[0]
    snippet, stats = channel.get("snippet", {}), channel.get("statistics", {})
    data = AccountData(platform="youtube", username=account["username"], source="youtube_api",
                       created_at=parse_time(snippet.get("publishedAt")), display_name=snippet.get("title"),
                       bio=snippet.get("description") or "", has_profile_image=bool(snippet.get("thumbnails")),
                       total_posts=_int(stats.get("videoCount")))
    if stats.get("hiddenSubscriberCount"):
        data.limitations.append("The channel hides its subscriber count.")
    else:
        data.followers = _int(stats.get("subscriberCount"))
    data.limitations.append("YouTube does not expose how many channels an account follows, or verification status, through this API.")
    uploads = (channel.get("contentDetails", {}).get("relatedPlaylists") or {}).get("uploads")
    if uploads:
        playlist = fetch_json(BASE + "playlistItems?" + urlencode({"part": "snippet", "playlistId": uploads,
                                                                   "maxResults": MAX_VIDEOS, "key": key}))
        for item in playlist.get("items") or []:
            s = item.get("snippet", {})
            moment = parse_time(s.get("publishedAt"))
            if moment:
                data.posts.append(Post(timestamp=moment, text=f"{s.get('title', '')}\n{s.get('description', '')}".strip()))
        data.limitations.append(f"Only the latest {MAX_VIDEOS} uploads are analysed; per-video engagement is not fetched.")
    return data


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
