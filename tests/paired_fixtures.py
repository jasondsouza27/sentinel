"""Synthetic paired-study rows. Never used as research evidence."""

import csv

from sentinel.curation import INTAKE_FIELDS


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def intake_case(number, *, basis="consented", source="source-a"):
    url = f"https://case{number}.example/verify"
    return {
        "case_id": f"case-{number}", "message": f"Synthetic request {number}: {url}",
        "url": url, "source_name": source, "source_ref": f"record-{number}",
        "campaign_group": "", "channel": "sms", "collected_on": "2026-10-01",
        "collection_basis": basis, "pair_evidence": "in_message", "pair_note": "",
        "redaction_reviewed": "yes",
    }


def evidence_case(number, *, basis="consented", kind="consent_record"):
    return {
        "case_id": f"case-{number}", "evidence_id": f"ev-{number}",
        "evidence_type": kind, "verification_ref": f"vault-{number}",
        "observed_on": "2026-09-30", "source_sha256": "a" * 64,
        "source_version": "v1", "permission_basis": basis,
        "redaction_decision": "redacted",
    }


def write_intake(root, rows):
    write_csv(root / "intake.csv", rows, INTAKE_FIELDS)
