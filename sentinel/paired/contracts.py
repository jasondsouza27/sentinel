"""Stable private study file contracts."""

from dataclasses import dataclass

EVIDENCE_FIELDS = (
    "case_id", "evidence_id", "evidence_type", "verification_ref",
    "observed_on", "source_sha256", "source_version", "permission_basis",
    "redaction_decision",
)

PACKET_FIELDS = (
    "case_id", "message", "url", "evidence_id", "evidence_type",
    "verification_ref", "observed_on",
)


@dataclass(frozen=True)
class StudyCriteria:
    min_total: int = 2000
    min_per_class: int = 1000
    min_test_per_class: int = 100
    min_test_domains: int = 30


PRODUCTION_CRITERIA = StudyCriteria()
