"""Verified acquisition and audit of the SMS scam-text corpus.

Primary source: Mishra & Soni (2022), "SMS PHISHING DATASET FOR MACHINE LEARNING
AND PATTERN RECOGNITION", Mendeley Data, doi:10.17632/f45bkkt8pr.1, CC BY 4.0.
Labels: ham, spam, smishing.
Cross-check: Almeida & Hidalgo (2011), UCI SMS Spam Collection, CC BY 4.0.
Most Mendeley messages also appear in UCI; the audit records how their labels
agree. UCI rows are not added to training: its spam label does not separate spam
from smishing, and adding one source's rows to only some classes would let the
model learn source style instead of content.
"""

import csv
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

from . import LABELS

SOURCES = {
    "mendeley": {
        "file": "mendeley-smishing.zip",
        "member": "Dataset_5971.csv",
        "sha256": "9bbf3188fdad81495d8e82825648b9b63b53fc86841a3d26c02629990b233cc3",
        "url": "https://data.mendeley.com/public-files/datasets/f45bkkt8pr/files/edb361de-918d-469f-9106-e84823830665/file_downloaded",
        "citation": "Mishra, S. & Soni, D. (2022). SMS Phishing Dataset for Machine Learning and Pattern Recognition. Mendeley Data, V1. doi:10.17632/f45bkkt8pr.1",
        "license": "CC BY 4.0",
    },
    "uci": {
        "file": "uci-sms.zip",
        "member": "SMSSpamCollection",
        "sha256": "1587ea43e58e82b14ff1f5425c88e17f8496bfcdb67a583dbff9eefaf9963ce3",
        "url": "https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip",
        "citation": "Almeida, T. & Hidalgo, J. (2011). SMS Spam Collection. UCI Machine Learning Repository. doi:10.24432/C5CC84",
        "license": "CC BY 4.0",
    },
    "india14": {
        "file": "india14.csv",
        "member": None,
        "sha256": "50b633a3a17be7b8622a99757295a73d78567f27c13d6f7b12935ba4f688d190",
        "url": "https://huggingface.co/datasets/anmolshrivastav/scam_ham_india_14_languages/resolve/34e2c413aefd2e8f2a6e93177a155f29733290a5/scam_ham_india_14_languages.csv",
        "citation": "anmolshrivastav (2026). Indian Multilingual Scam & Ham SMS Dataset (14 Languages). Hugging Face, revision 34e2c41. Tagged synthetic.",
        "license": "MIT",
    },
}
MAX_CHARS = 1000
INDIA14_LANGUAGES = ("English", "Hinglish")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_member(raw_dir, name):
    spec = SOURCES[name]
    archive = Path(raw_dir) / spec["file"]
    data = archive.read_bytes()
    digest = sha256_bytes(data)
    if digest != spec["sha256"]:
        raise ValueError(f"{spec['file']} checksum {digest} does not match the pinned source")
    if spec["member"] is None:
        return data.decode("utf-8")
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        return bundle.read(spec["member"]).decode("utf-8")


def clean_text(text):
    """Normalize Unicode and whitespace; keep the message content otherwise unchanged."""
    text = unicodedata.normalize("NFKC", text).replace("�", "")
    return re.sub(r"\s+", " ", text).strip()


def match_key(text):
    """Key for exact duplicates after case, punctuation and spacing are ignored."""
    return re.sub(r"[^a-z0-9]+", " ", clean_text(text).lower()).strip()


def template_key(text):
    """Key for templated messages: numbers, URLs and phone numbers are masked.

    Spam campaigns resend one template with different prize codes, numbers and
    links. All rows with one template key stay in the same split.
    """
    text = clean_text(text).lower()
    text = re.sub(r"(https?://|www\.)\S+", " url ", text)
    text = re.sub(r"\b[\w.-]+\.(com|net|org|co\.uk|biz|info|ly|me)\S*", " url ", text)
    text = re.sub(r"\d+", " 0 ", text)
    return " ".join(re.sub(r"[^a-z0 ]+", " ", text).split())


def load_mendeley(raw_dir):
    rows = list(csv.DictReader(io.StringIO(read_member(raw_dir, "mendeley"))))
    records, excluded = [], Counter()
    for index, row in enumerate(rows):
        label = (row.get("LABEL") or "").strip().lower()
        text = clean_text(row.get("TEXT") or "")
        if label not in LABELS:
            excluded["unknown_label"] += 1
            continue
        if not text:
            excluded["empty_text"] += 1
            continue
        records.append({"source_row": index, "text": text[:MAX_CHARS], "label": label,
                        "truncated": len(text) > MAX_CHARS})
    return records, excluded


def load_uci(raw_dir):
    out = []
    for line in read_member(raw_dir, "uci").splitlines():
        if "\t" in line:
            label, text = line.split("\t", 1)
            out.append((label.strip().lower(), clean_text(text)))
    return out


def build(raw_dir, out_dir):
    """Write dataset.jsonl and audit.json; resolve duplicates; record exclusions."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records, excluded = load_mendeley(raw_dir)

    # Exact duplicates: keep the first occurrence. Conflicting labels exclude the whole key.
    by_key = {}
    for record in records:
        by_key.setdefault(match_key(record["text"]), []).append(record)
    kept = []
    duplicate_rows = conflicting_keys = 0
    for key, group in by_key.items():
        labels = {r["label"] for r in group}
        if len(labels) > 1:
            conflicting_keys += 1
            excluded["conflicting_duplicate_labels"] += len(group)
            continue
        duplicate_rows += len(group) - 1
        kept.append(group[0])
    excluded["exact_duplicate"] = duplicate_rows

    for record in kept:
        record["id"] = sha256_bytes(f"mendeley:{record['source_row']}".encode())[:16]
        record["group"] = sha256_bytes(template_key(record["text"]).encode())[:16]

    uci = {}
    for label, text in load_uci(raw_dir):
        uci.setdefault(match_key(text), set()).add(label)
    agreement, conflicts = Counter(), 0
    for record in kept:
        found = uci.get(match_key(record["text"])) or set()
        agreement[f"{record['label']}->{'/'.join(sorted(found)) or 'absent'}"] += 1
        # UCI has only ham/spam: a conflict is ham against spam in either direction.
        conflicts += (record["label"] == "ham" and "spam" in found) or (record["label"] != "ham" and "ham" in found)

    with (out_dir / "dataset.jsonl").open("w", encoding="utf-8") as stream:
        for record in kept:
            stream.write(json.dumps({k: record[k] for k in ("id", "group", "label", "text", "truncated")},
                                    ensure_ascii=False) + "\n")
    audit = {
        "sources": {name: {k: spec[k] for k in ("file", "sha256", "url", "citation", "license")}
                    for name, spec in SOURCES.items()},
        "rows_read": len(records) + sum(v for k, v in excluded.items() if k in ("unknown_label", "empty_text")),
        "rows_kept": len(kept),
        "label_counts": dict(Counter(r["label"] for r in kept)),
        "template_groups": len({r["group"] for r in kept}),
        "excluded": dict(excluded),
        "conflicting_duplicate_keys": conflicting_keys,
        "truncated_rows": sum(r["truncated"] for r in kept),
        "uci_cross_check": {"label_pairs": dict(agreement), "ham_spam_conflicts": conflicts},
        "dataset_sha256": sha256_bytes((out_dir / "dataset.jsonl").read_bytes()),
    }
    (out_dir / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return audit


def load_dataset(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


# ---------- v2: add synthetic Indian transactional and modern-scam messages ----------

def build_v2(raw_dir, out_dir):
    """dataset-v2.jsonl = v1 rows (unchanged ids, source 'mendeley') + English and
    Hinglish rows of the india14 synthetic dataset (source 'india14').

    india14 'scam' rows are fraud attempts (KYC, digital arrest, task jobs,
    impersonation), so they map to 'smishing'; 'ham' maps to 'ham'. Exact
    duplicates are removed; a row whose text duplicates a v1 row is dropped.
    """
    out_dir = Path(out_dir)
    v1 = load_dataset(out_dir / "dataset.jsonl")
    seen = {match_key(r["text"]) for r in v1}
    rows = list(csv.DictReader(io.StringIO(read_member(raw_dir, "india14"))))
    added, excluded = [], Counter()
    for index, row in enumerate(rows):
        if row["language"] not in INDIA14_LANGUAGES:
            excluded["other_language"] += 1
            continue
        text = clean_text(row["text"])[:MAX_CHARS]
        key = match_key(text)
        if not text or key in seen:
            excluded["duplicate"] += 1
            continue
        seen.add(key)
        label = {"ham": "ham", "scam": "smishing"}.get(row["label"].strip().lower())
        if label is None:
            excluded["unknown_label"] += 1
            continue
        added.append({"id": sha256_bytes(f"india14:{index}".encode())[:16],
                      "group": sha256_bytes(template_key(text).encode())[:16],
                      "label": label, "text": text, "truncated": False,
                      "source": "india14", "language": row["language"]})
    records = [{**r, "source": "mendeley"} for r in v1] + added
    path = out_dir / "dataset-v2.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    audit = {
        "sources": {name: {k: spec[k] for k in ("file", "sha256", "url", "citation", "license")}
                    for name, spec in SOURCES.items()},
        "india14": {"rows_read": len(rows), "rows_added": len(added), "excluded": dict(excluded),
                    "label_counts": dict(Counter(r["label"] for r in added)),
                    "language_counts": dict(Counter(r["language"] for r in added)),
                    "template_groups": len({r["group"] for r in added}),
                    "note": "Synthetic, template-style data; used to add genuine transactional ham and modern scams."},
        "rows_total": len(records),
        "label_counts": dict(Counter(r["label"] for r in records)),
        "dataset_sha256": sha256_bytes(path.read_bytes()),
    }
    (out_dir / "audit-v2.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return audit
