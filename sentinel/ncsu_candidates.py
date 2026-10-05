"""Select local, unreviewed message–link candidates from the NC State SMS release."""

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from .curation import INTAKE_FIELDS
from .datasets import LINK, domain_group, extract_urls
from .research import _normalized


SOURCE_URL = "https://github.com/wspr-ncsu/sms-phishing"
SOURCE_NAME = "NC State SMS phishing research release"


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_candidates(source_path, output_path, audit_path=None, limit=100, seed=42):
    """Write a diverse candidate sheet; no candidate is approved or labelled."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()
    audit_path = Path(audit_path).resolve() if audit_path else None
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if output_path.name.lower() == "intake.csv" or (audit_path and audit_path.name.lower() == "intake.csv"):
        raise ValueError("Refusing to write intake.csv; candidates need separate review")
    if output_path == source_path or (audit_path and audit_path in (source_path, output_path)):
        raise ValueError("Source, candidate, and audit paths must be different")
    existing = [path.name for path in (output_path, audit_path) if path and path.exists()]
    if existing:
        raise FileExistsError("Refusing to overwrite " + ", ".join(existing))

    csv.field_size_limit(10_000_000)
    excluded = Counter()
    seen_ids = set()
    seen_pairs = set()
    eligible = []
    source_cases = 0
    with source_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"messageID", "message"}.issubset(reader.fieldnames or []):
            raise ValueError("Source CSV needs messageID and message columns")
        for record in reader:
            source_cases += 1
            identifier = (record.get("messageID") or "").strip()
            message = (record.get("message") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier) or identifier in seen_ids:
                excluded["invalid_or_duplicate_id"] += 1
                continue
            seen_ids.add(identifier)
            if not message or len(message) > 8000:
                excluded["empty_or_long_message"] += 1
                continue
            link_occurrences = len(LINK.findall(message))
            if not link_occurrences:
                excluded["no_link"] += 1
                continue
            if link_occurrences != 1:
                excluded["multiple_links"] += 1
                continue
            links = extract_urls(message)
            if not links:
                excluded["no_link"] += 1
                continue
            url = links[0]
            try:
                parts = urlsplit(url)
                _ = parts.port
                valid_url = parts.scheme in ("http", "https") and parts.hostname and "." in parts.hostname
            except ValueError:
                valid_url = False
            if not valid_url:
                excluded["malformed_link"] += 1
                continue
            wording = _normalized(message)
            pair = (wording, url.lower())
            if pair in seen_pairs:
                excluded["duplicate_pair"] += 1
                continue
            seen_pairs.add(pair)
            eligible.append((identifier, message, url, domain_group(url), wording))

    if not eligible:
        raise ValueError("No single-link message candidates found")
    eligible.sort(key=lambda item: item[0])
    random.Random(seed).shuffle(eligible)
    selected = []
    used_domains = set()
    used_wording = set()
    for identifier, message, url, domain, wording in eligible:
        if domain in used_domains or wording in used_wording:
            continue
        used_domains.add(domain)
        used_wording.add(wording)
        selected.append({
            "case_id": f"ncsu-{identifier}", "message": message, "url": url,
            "source_name": SOURCE_NAME, "source_ref": f"phishing_messages.csv:messageID={identifier}",
            "campaign_group": "", "channel": "sms", "collected_on": "",
            "collection_basis": "", "pair_evidence": "in_message", "pair_note": "",
            "redaction_reviewed": "",
        })
        if len(selected) >= limit:
            break

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=INTAKE_FIELDS)
        writer.writeheader()
        writer.writerows(selected)
    audit = {
        "source": SOURCE_URL,
        "source_sha256": _sha256(source_path),
        "output_sha256": _sha256(output_path),
        "source_cases": source_cases,
        "eligible_cases": len(eligible),
        "selected_cases": len(selected),
        "selected_domain_groups": len(used_domains),
        "excluded": dict(excluded),
        "seed": seed,
        "limit": limit,
        "status": "unreviewed phishing candidates; no legitimate class or performance claim",
    }
    if audit_path:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(audit, indent=2))
    return audit


def main():
    parser = argparse.ArgumentParser(description="Select unreviewed NC State SMS message–link candidates")
    parser.add_argument("source", help="Local phishing_messages.csv from the NC State release")
    parser.add_argument("output", help="Local candidate CSV; do not use intake.csv")
    parser.add_argument("--audit-out", help="Write a counts-only JSON audit")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        audit = build_candidates(args.source, args.output, args.audit_out, args.limit, args.seed)
    except (ValueError, FileExistsError, FileNotFoundError, UnicodeError, csv.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
