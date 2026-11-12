"""Verified acquisition and audit of public bot-detection datasets (Bot Repository, OSoMe).

Terms: "provided for academic research only"; most sets are CC BY-NC-ND 4.0. Raw
data stays local and git-ignored; nothing derived from it is redistributed.

Only profile metadata that Sentinel can also obtain when analysing an account is
kept (counts, account age, default picture, bio, username, display name, link).
Likes, list counts and "verified" are deliberately excluded (see features.py).
"""

import csv
import hashlib
import json
import tarfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://botometer.osome.iu.edu/bot-repository/datasets/{0}/{0}.tar.gz"
DATASETS = {
    # name: (sha256 of the archive, licence as published)
    "gilani-2017": ("98ce982074b4e611c58f6aa88bedbaaeca0aff9ecbe95e017f1be99e48af60ea", "not stated (Bot Repository: academic research only)"),
    "cresci-rtbust-2019": ("0462f9844e77c7ad16fe81a09319df4a1b933d88aee13478e735700325641ed0", "not stated (Bot Repository: academic research only)"),
    "cresci-stock-2018": ("91b202a17596fe03371e18b42854b4f20231fbf93956e5e733f5f498ba0b452c", "not stated (Bot Repository: academic research only)"),
    "midterm-2018": ("c7788b852b4aee15816230457c18f1d8487757574b1e918799d21a72bc8c4f64", "CC BY-NC-ND 4.0"),
    "botwiki-2019": ("9120919c72a176d779e7f19c48c6a47ba518c8e0ead2b1afc9f4815c30330e8a", "CC BY-NC-ND 4.0"),
    "verified-2019": ("f0e897883f33feef26e15bf4fe44cc2c69727ba6620f07a6cb7ef2ad3f0c2a52", "CC BY-NC-ND 4.0"),
    "pronbots-2019": ("4960434af710685f978cecb6a5ebdcb0e99efd93d2340093a37c5298ada6003e", "CC BY-NC-ND 4.0"),
    "political-bots-2019": ("e175aaba996aa3f2fdb007416e63d3a7aa5212ac2fbe45d7ef81f6f5ba152bd5", "CC BY-NC-ND 4.0"),
    "vendor-purchased-2019": ("6758cc640a8ba07e2b660d4f400b34be61efc8b00ee7408b50bdd3c429ddb44f", "CC BY-NC-ND 4.0"),
    "celebrity-2019": ("8990daab49aa45a4536ecb93f7a8bb2ff947bde477ae50b8075f3330bf64c3de", "CC BY-NC-ND 4.0"),
    "botometer-feedback-2019": ("36e8160f0d903c9e4a3d8a882c71352670b85b0c80ff99f78fb66b1c65a88a0f", "CC BY-NC-ND 4.0"),
}
# Cresci datasets: CSV user tables inside nested zips (The Fake Project, IIT-CNR).
CSV_DATASETS = {
    "cresci-2015": {"file": "cresci-2015.csv.tar.gz", "sha256": "c6ee52e7feb96b7b071a625af563c5be8b793c4cfe900096a45029ad81d75fb6",
                    "url": "https://botometer.osome.iu.edu/bot-repository/datasets/cresci-2015/cresci-2015.csv.tar.gz",
                    "licence": "For research purposes only; no redistribution without the IIT-CNR disclaimer",
                    "parts": {"E13.csv.zip": "human", "TFP.csv.zip": "human", "FSF.csv.zip": "bot",
                              "INT.csv.zip": "bot", "TWT.csv.zip": "bot"}},
    "cresci-2017": {"file": "cresci-2017.csv.zip", "sha256": "f80ad99dce3be884c88f1e544a7ff418b8220b444f2ecff26f7dc84317f11c3e",
                    "url": "https://botometer.osome.iu.edu/bot-repository/datasets/cresci-2017/cresci-2017.csv.zip",
                    "licence": "For research purposes only; no redistribution without the IIT-CNR disclaimer",
                    "parts": {"datasets_full.csv/genuine_accounts.csv.zip": "human", "datasets_full.csv/fake_followers.csv.zip": "bot", "datasets_full.csv/social_spambots_1.csv.zip": "bot", "datasets_full.csv/social_spambots_2.csv.zip": "bot", "datasets_full.csv/social_spambots_3.csv.zip": "bot", "datasets_full.csv/traditional_spambots_1.csv.zip": "bot", "datasets_full.csv/traditional_spambots_2.csv.zip": "bot", "datasets_full.csv/traditional_spambots_3.csv.zip": "bot", "datasets_full.csv/traditional_spambots_4.csv.zip": "bot"}},
}
TWITTER_TIME = "%a %b %d %H:%M:%S %z %Y"
MIDTERM_TIME = "%a %b %d %H:%M:%S %Y"


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _time(value, fmt):
    try:
        moment = datetime.strptime(value, fmt)
    except (TypeError, ValueError):
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()  # naive times are UTC


def _record(name, label, user_id, profile):
    """Keep only fields Sentinel can obtain at inference."""
    return {"dataset": name, "label": label, "user_id": str(user_id), **profile}


def load(name, raw_dir):
    archive = Path(raw_dir) / f"{name}.tar.gz"
    expected, _ = DATASETS[name]
    if _sha256(archive) != expected:
        raise ValueError(f"{archive.name} does not match its pinned checksum")
    rows, excluded = [], Counter()
    with tarfile.open(archive) as bundle:
        labels = {}
        for line in bundle.extractfile(f"{name}.tsv").read().decode().splitlines():
            parts = line.strip().split("\t")
            if len(parts) == 2 and parts[1] in ("bot", "human"):
                labels[parts[0]] = parts[1]
            else:
                excluded["unusable_label_line"] += 1
        member = (f"{name}_processed_user_objects.json" if name == "midterm-2018" else f"{name}_tweets.json")
        objects = json.load(bundle.extractfile(member))
    seen = set()
    for obj in objects:
        if name == "midterm-2018":
            user, user_id = obj, obj.get("user_id")
            created, probed = _time(obj.get("user_created_at"), MIDTERM_TIME), _time(obj.get("probe_timestamp"), MIDTERM_TIME)
            default_image = None  # not present in the processed objects
        else:
            user = obj.get("user") or {}
            user_id = user.get("id_str") or user.get("id")
            created, probed = _time(user.get("created_at"), TWITTER_TIME), _time(obj.get("created_at"), TWITTER_TIME)
            default_image = user.get("default_profile_image")
        user_id = str(user_id)
        if user_id in seen:
            continue
        seen.add(user_id)
        label = labels.get(user_id)
        if label is None:
            excluded["no_label"] += 1
            continue
        if created is None or probed is None or probed < created:
            excluded["bad_dates"] += 1
            continue
        rows.append(_record(name, label, user_id, {
            "followers": user.get("followers_count"), "following": user.get("friends_count"),
            "posts": user.get("statuses_count"), "age_days": (probed - created) / 86400,
            "default_profile_image": default_image, "bio": user.get("description") or "",
            "username": user.get("screen_name") or "", "display_name": user.get("name") or "",
            "has_url": bool(user.get("url")), "probe_year": datetime.fromtimestamp(probed, tz=timezone.utc).year}))
    excluded["labels_without_profile"] = len(set(labels) - seen)
    return rows, excluded


def load_csv(name, raw_dir):
    """Cresci-format datasets: an archive of <part>.csv.zip files, each holding users.csv."""
    import io
    import zipfile
    spec = CSV_DATASETS[name]
    archive = Path(raw_dir) / spec["file"]
    if _sha256(archive) != spec["sha256"]:
        raise ValueError(f"{archive.name} does not match its pinned checksum")
    rows, excluded = [], Counter()
    opener = zipfile.ZipFile(archive) if archive.suffix == ".zip" else tarfile.open(archive)
    with opener as outer:
        for part, label in spec["parts"].items():
            data = outer.read(part) if isinstance(outer, zipfile.ZipFile) else outer.extractfile(part).read()
            with zipfile.ZipFile(io.BytesIO(data)) as inner:
                member = next(n for n in inner.namelist() if n.endswith("users.csv") and "__MACOSX" not in n)
                reader = csv.DictReader(io.TextIOWrapper(inner.open(member), encoding="utf-8", errors="replace"))
                for user in reader:
                    created = _created_time(user.get("created_at"))
                    probed = _probe_time(user)
                    if created is None or probed is None or probed < created:
                        excluded["bad_dates"] += 1
                        continue
                    try:
                        counts = [int(float(user[k])) for k in ("followers_count", "friends_count", "statuses_count")]
                    except (KeyError, ValueError):
                        excluded["bad_counts"] += 1
                        continue
                    rows.append(_record(name, label, user.get("id"), {
                        "followers": counts[0], "following": counts[1], "posts": counts[2],
                        "age_days": (probed - created) / 86400,
                        "default_profile_image": user.get("default_profile_image") in ("1", "True", "true"),
                        "bio": user.get("description") or "", "username": user.get("screen_name") or "",
                        "display_name": user.get("name") or "", "has_url": bool((user.get("url") or "").strip() not in ("", "NULL")),
                        "probe_year": datetime.fromtimestamp(probed, tz=timezone.utc).year,
                        "subset": part.rsplit("/", 1)[-1].split(".")[0]}))
    return rows, excluded


def _created_time(value):
    """Twitter date string, or epoch milliseconds such as '1183552203000L' (cresci-2017 traditional spambots)."""
    text = (value or "").strip().rstrip("L")
    if text.isdigit():
        return int(text) / 1000
    return _time(value, TWITTER_TIME)


def _probe_time(user):
    """When the profile was collected. cresci-2017 records it in 'crawled_at' ('updated' is a later database
    update and 'timestamp' is the creation time); cresci-2015 records it in 'updated'."""
    for key in ("crawled_at", "updated"):
        value = (user.get(key) or "").strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", TWITTER_TIME):
            moment = _time(value, fmt)
            if moment is not None:
                return moment
    return None


def build(raw_dir, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_rows, audit = [], {"datasets": {}}
    sources = [(name, "json") for name in DATASETS] + [(name, "csv") for name in CSV_DATASETS]
    for name, kind in sources:
        if kind == "csv" and not (Path(raw_dir) / CSV_DATASETS[name]["file"]).exists():
            audit["datasets"][name] = {"skipped": "archive not downloaded"}
            continue
        rows, excluded = load(name, raw_dir) if kind == "json" else load_csv(name, raw_dir)
        meta = ({"url": BASE_URL.format(name), "sha256": DATASETS[name][0], "licence": DATASETS[name][1]} if kind == "json"
                else {k: CSV_DATASETS[name][k] for k in ("url", "sha256", "licence")})
        audit["datasets"][name] = {**meta, "rows": len(rows), "labels": dict(Counter(r["label"] for r in rows)),
                                   "excluded": dict(excluded)}
        all_rows.extend(rows)
    # The same account in two datasets: keep one copy; drop accounts with conflicting labels.
    by_user = {}
    for row in all_rows:
        by_user.setdefault(row["user_id"], []).append(row)
    kept, conflicts, duplicates = [], 0, 0
    for user_id, rows in by_user.items():
        if len({r["label"] for r in rows}) > 1:
            conflicts += len(rows)
            continue
        duplicates += len(rows) - 1
        kept.append(rows[0])
    for row in kept:  # pseudonymous id; raw Twitter ids are not needed after deduplication
        row["user_id"] = hashlib.sha256(row["user_id"].encode()).hexdigest()[:16]
    path = out_dir / "accounts.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for row in kept:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    audit.update(rows=len(kept), labels=dict(Counter(r["label"] for r in kept)),
                 cross_dataset_duplicates_removed=duplicates, conflicting_label_rows_removed=conflicts,
                 accounts_sha256=_sha256(path),
                 excluded_fields=["favourites_count", "listed_count", "verified", "lang", "geo_enabled", "profile colours"],
                 note="astroturf was not used: it has labels but no profile objects. cresci-2017 (465 MB) not used.")
    (out_dir / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    return audit


def load_accounts(path):
    with open(path, encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]
