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


def complete_reviews(root, labels, *, observed_months=None):
    from sentinel.paired.admission import EVIDENCE_FIELDS, finalize_study_reviews, prepare_study_reviews

    rows = read_csv(root / "intake.csv")
    evidence = [
        evidence_case(int(row["case_id"].split("-")[-1]), basis=row["collection_basis"],
                      kind="official_confirmation" if str(label) == "0" else "independent_threat_report")
        for row, label in zip(rows, labels)
    ]
    if observed_months is not None:
        for row, month in zip(evidence, observed_months):
            row["observed_on"] = f"2026-{month:02d}-01" if month else ""
    write_csv(root / "evidence_ledger.csv", evidence, EVIDENCE_FIELDS)
    prepare_study_reviews(root)
    for name, reviewer in (("reviewer_a", "a"), ("reviewer_b", "b")):
        reviews = read_csv(root / f"{name}.csv")
        for review, label in zip(reviews, labels):
            review.update(reviewer_id=reviewer, review_label=str(label), review_reason="Synthetic test decision")
        write_csv(root / f"{name}.csv", reviews, tuple(reviews[0]))
    finalize_study_reviews(root)
