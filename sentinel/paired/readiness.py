"""Counts-only feasibility audit; never serializes private cases."""

from collections import Counter, defaultdict
from pathlib import Path

from sentinel import curation, research

from .admission import validate_ledger, verify_finalized_study
from .contracts import PRODUCTION_CRITERIA, StudyCriteria


def _cross(rows, key):
    table = defaultdict(Counter)
    for row in rows:
        table[key(row)][row["label"]] += 1
    return {name: {label: counts.get(label, 0) for label in ("0", "1")}
            for name, counts in sorted(table.items())}


def _predicts_class(table):
    return len(table) >= 2 and all(sum(bool(value) for value in counts.values()) == 1
                                   for counts in table.values())


def _component_count(rows):
    """Conservative preliminary grouping; the pinned parser is used at freeze."""
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen = {}
    for i, row in enumerate(rows):
        keys = {"d:" + item for item in research._domains(row)}
        keys |= {"c:" + item for item in research._campaigns(row)}
        keys.add("w:" + research._normalized(row["message"]))
        for key in keys:
            if key in seen:
                parent[find(i)] = find(seen[key])
            else:
                seen[key] = i
    return len({find(i) for i in range(len(rows))})


def readiness_report(root: Path, criteria: StudyCriteria = PRODUCTION_CRITERIA) -> dict:
    root = Path(root)
    intake = curation._read_csv(root / "intake.csv", curation.INTAKE_FIELDS)
    base = {
        "status": "unavailable", "claim_ready": False, "reasons": [],
        "candidate_cases": len(intake), "admitted_cases": 0,
        "class_counts": {"0": 0, "1": 0},
    }
    if not intake:
        base["reasons"] = ["empty_intake"]
        return base
    if not (root / "study_final_manifest.json").exists():
        if (root / "final_pairs.csv").exists() or (root / "final_audit.json").exists():
            raise ValueError("Partial or historical finalization is not a verified paired study")
        base.update(status="pending_review", reasons=["review_not_finalized"])
        return base

    audit = verify_finalized_study(root)
    admitted = curation._read_csv(root / "final_pairs.csv", curation.FINAL_FIELDS)
    ledger = validate_ledger(root, curation._intake(root))
    counts = Counter(row["label"] for row in admitted)
    if set(counts) - {"0", "1"}:
        raise ValueError("Final labels must be 0 or 1")
    source_names = sorted({row["source_name"] for row in admitted})
    source_ids = {name: f"source_{index + 1}" for index, name in enumerate(source_names)}
    by_source = _cross(admitted, lambda row: source_ids[row["source_name"]])
    by_channel = _cross(admitted, lambda row: row["channel"])
    known = [row for row in admitted if ledger[row["case_id"]]["observed_on"].strip()]
    by_month = _cross(known, lambda row: ledger[row["case_id"]]["observed_on"][:7])
    domain_count = len(set().union(*(research._domains(row) for row in admitted))) if admitted else 0
    group_count = _component_count(admitted)
    verified_legitimate = sum(
        row["label"] == "0" and ledger[row["case_id"]]["evidence_type"] == "official_confirmation"
        for row in admitted
    )
    missing_legitimate = counts["0"] - verified_legitimate
    reasons = []
    if len(admitted) < criteria.min_total:
        reasons.append("insufficient_total")
    for label in ("0", "1"):
        if counts[label] < criteria.min_per_class:
            reasons.append(f"insufficient_class_{label}")
        if counts[label] < 4 * criteria.min_test_per_class:
            reasons.append(f"insufficient_partition_class_{label}")
    if domain_count < criteria.min_test_domains:
        reasons.append("insufficient_distinct_domains")
    if group_count < 4:
        reasons.append("insufficient_independent_groups")
    if _predicts_class(by_source):
        reasons.append("source_label_confounded")
    if _predicts_class(by_month):
        reasons.append("observation_period_confounded")
    if missing_legitimate:
        reasons.append("missing_legitimate_verification")
    base.update(
        status="unavailable" if reasons else "eligible_for_freeze",
        claim_ready=not reasons, reasons=reasons,
        admitted_cases=len(admitted),
        excluded_cases=audit["excluded_cases"],
        class_counts={label: counts[label] for label in ("0", "1")},
        source_class_counts=by_source, channel_class_counts=by_channel,
        month_class_counts=by_month,
        channel_counts=dict(sorted(Counter(row["channel"] for row in admitted).items())),
        observation_dates={"known": len(known), "unknown": len(admitted) - len(known)},
        independent_groups=group_count, distinct_domains=domain_count,
        legitimate_independently_verified=verified_legitimate,
        legitimate_verification_missing=missing_legitimate,
    )
    return base
