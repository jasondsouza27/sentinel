"""Activity and content features from the cresci post histories (run in .venv-text-ml).

Only cresci-2015 and cresci-2017 include full post histories; the other Bot
Repository sets carry one tweet per account. For each account the most recent
POSTS_PER_ACCOUNT posts are turned into features with the *same* functions the
app applies to uploaded posts (sentinel/bot_detection/features.py), so training
and inference match. Only numeric features are written; no post text is kept.
"""

import csv
import heapq
import io
import json
import tarfile
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ..adapters import Post
from .features import MIN_POSTS, POSTS_PER_ACCOUNT, account_features
from .source import CSV_DATASETS, _sha256, load_csv
TWITTER_TIME = "%a %b %d %H:%M:%S %z %Y"


def _post_time(value):
    text = (value or "").strip().rstrip("L")
    if text.isdigit():
        return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
    try:
        return datetime.strptime(text, TWITTER_TIME)
    except ValueError:
        return None


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _part(args):
    """Worker: stream one part's tweets.csv and return {user_id: features}."""
    archive, part = args
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as outer:
            data = outer.read(part)
    else:
        with tarfile.open(archive) as outer:
            data = outer.extractfile(part).read()
    latest = {}  # user -> min-heap of (timestamp, counter, Post) keeping the newest posts
    counter = 0
    with zipfile.ZipFile(io.BytesIO(data)) as inner:
        member = next((n for n in inner.namelist() if n.endswith("tweets.csv") and "__MACOSX" not in n), None)
        if member is None:  # e.g. cresci-2017 traditional_spambots_2-4 ship profiles only
            return part, None
        reader = csv.DictReader(io.TextIOWrapper(inner.open(member), encoding="utf-8", errors="replace"))
        for row in reader:
            moment = _post_time(row.get("created_at"))
            user = row.get("user_id")
            if moment is None or not user:
                continue
            repost = (row.get("retweeted_status_id") or "NULL").strip() not in ("", "0", "NULL")
            post = Post(timestamp=moment, text=row.get("text") or "", is_repost=repost,
                        likes=_int(row.get("favorite_count")), replies=_int(row.get("reply_count")))
            heap = latest.setdefault(user, [])
            counter += 1
            item = (moment.timestamp(), counter, post)
            if len(heap) < POSTS_PER_ACCOUNT:
                heapq.heappush(heap, item)
            elif item[0] > heap[0][0]:
                heapq.heapreplace(heap, item)
    out = {}
    for user, heap in latest.items():
        if len(heap) >= MIN_POSTS:
            out[user] = account_features([item[2] for item in heap])
    return part, out


def build(raw_dir, out_dir, workers=8):
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    jobs, profiles = [], {}
    for name in ("cresci-2015", "cresci-2017"):  # 2015 first: shared fake followers stay in cresci-2015
        spec = CSV_DATASETS[name]
        archive = raw_dir / spec["file"]
        if _sha256(archive) != spec["sha256"]:
            raise ValueError(f"{archive.name} does not match its pinned checksum")
        for row in load_csv(name, raw_dir)[0]:
            profiles.setdefault(row["user_id"], row)
        jobs += [(str(archive), part) for part in spec["parts"]]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = dict(pool.map(_part, jobs))
    rows, missing = [], Counter()
    no_posts = sorted(part for part, result in results.items() if result is None)
    results = {part: result or {} for part, result in results.items()}
    seen = set()
    for (archive, part) in jobs:
        for user, feats in results[part].items():
            profile = profiles.get(user)
            if profile is None:
                missing["no_profile"] += 1
                continue
            if user in seen:
                missing["duplicate_account"] += 1
                continue
            seen.add(user)
            rows.append({"dataset": profile["dataset"], "subset": profile["subset"], "label": profile["label"],
                         "profile": {k: profile[k] for k in ("followers", "following", "posts", "age_days", "bio",
                                                             "username", "display_name", "has_url")},
                         "activity": feats})
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "activity.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    audit = {"rows": len(rows), "posts_per_account": POSTS_PER_ACCOUNT, "min_posts": MIN_POSTS,
             "by_subset": {f"{d}/{s}/{l}": n for (d, s, l), n in sorted(Counter((r["dataset"], r["subset"], r["label"]) for r in rows).items())},
             "excluded": dict(missing), "parts_without_post_history": no_posts, "activity_sha256": _sha256(path),
             "note": "Numeric features only; no post text is stored."}
    (out_dir / "activity-audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    return audit
