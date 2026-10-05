"""Build auditable research pairs from public corpora without visiting links."""

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


ASSASSIN_SOURCE = "https://doi.org/10.6084/m9.figshare.25432108.v1"
LINK = re.compile(r"(?<![\w@])(?:https?://|www\.)[^\s<>'\"`]+", re.IGNORECASE)
COMMON_SECOND_LEVEL = {"ac", "co", "com", "edu", "gov", "net", "org"}
FIELDS = ("case_id", "message", "url", "label", "domain_group", "source_row", "pair_method")


def extract_urls(message):
    """Return HTTP(S) links appearing in the original text, without fetching them."""
    found = []
    for match in LINK.finditer(message):
        candidate = match.group().rstrip(".,;:!?)]}'\"")
        if candidate.lower().startswith("www."):
            candidate = "http://" + candidate
        try:
            host = urlsplit(candidate).hostname
        except ValueError:
            continue
        if host and "." in host and candidate not in found:
            found.append(candidate)
    return found


def domain_group(url):
    """Conservatively group common subdomains under the same destination."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    labels = host.split(".")
    if len(labels) < 3:
        return host
    if len(labels[-1]) == 2 and labels[-2] in COMMON_SECOND_LEVEL and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_assassin_pairs(source_path, output_path, audit_path=None, max_message_chars=8000):
    """Import only original message/link pairs for an exploratory spam-vs-ham task.

    Apache SpamAssassin's positive label is spam; it is not a verified phishing
    label. The Figshare CSV remains local because raw mail may contain PII.
    """
    source_path = Path(source_path)
    output_path = Path(output_path)
    csv.field_size_limit(10_000_000)
    excluded = Counter()
    labels = Counter()
    seen_messages = set()
    rows = []
    with source_path.open(encoding="utf-8-sig", errors="replace", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"subject", "body", "label"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Assassin CSV requires subject, body, and label columns")
        for source_row, record in enumerate(reader, start=2):
            label = (record.get("label") or "").strip()
            if label not in ("0", "1"):
                excluded["invalid_label"] += 1
                continue
            message = "\n".join(part for part in ((record.get("subject") or "").strip(), (record.get("body") or "").strip()) if part)
            if not message:
                excluded["empty_message"] += 1
                continue
            if len(message) > max_message_chars:
                excluded["message_too_long"] += 1
                continue
            links = extract_urls(message)
            if not links:
                excluded["no_link_in_message"] += 1
                continue
            if len(links) != 1:
                excluded["multiple_links_in_message"] += 1
                continue
            normalized = " ".join(re.findall(r"[a-z0-9]+", message.lower()))
            if normalized in seen_messages:
                excluded["duplicate_message"] += 1
                continue
            seen_messages.add(normalized)
            url = links[0]
            rows.append({
                "case_id": f"assassin-{source_row:06d}",
                "message": message,
                "url": url,
                "label": label,
                "domain_group": domain_group(url),
                "source_row": str(source_row),
                "pair_method": "link_extracted_from_message",
            })
            labels[label] += 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    audit = {
        "source": ASSASSIN_SOURCE,
        "source_file": source_path.name,
        "source_sha256": _sha256(source_path),
        "output_sha256": _sha256(output_path),
        "task": "exploratory email spam versus ham; not phishing evaluation",
        "label_meaning": {"0": "ham (non-spam)", "1": "spam (not verified phishing)"},
        "pair_method": "single HTTP(S) or www link extracted from the same message",
        "source_cases": len(rows) + sum(excluded.values()),
        "paired_cases": len(rows),
        "class_counts": dict(labels),
        "domain_groups": len({row["domain_group"] for row in rows}),
        "excluded": dict(excluded),
        "max_message_chars": max_message_chars,
    }
    if audit_path:
        audit_path = Path(audit_path)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit


def main():
    parser = argparse.ArgumentParser(description="Extract genuine message/link pairs from the Figshare Assassin CSV")
    parser.add_argument("source", help="Downloaded Assassin.csv (kept local)")
    parser.add_argument("output", help="Local paired CSV output")
    parser.add_argument("--audit-out", help="Write a counts-only JSON provenance audit")
    args = parser.parse_args()
    print(json.dumps(build_assassin_pairs(args.source, args.output, args.audit_out), indent=2))


if __name__ == "__main__":
    main()
