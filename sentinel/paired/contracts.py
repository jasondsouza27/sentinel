"""Stable private study file contracts."""

EVIDENCE_FIELDS = (
    "case_id", "evidence_id", "evidence_type", "verification_ref",
    "observed_on", "source_sha256", "source_version", "permission_basis",
    "redaction_decision",
)

PACKET_FIELDS = (
    "case_id", "message", "url", "evidence_id", "evidence_type",
    "verification_ref", "observed_on",
)
