"""Shared stdlib-only URL research and serving records."""
from dataclasses import dataclass, asdict

DATASET_SCHEMA = "url-dataset-v1"
SPLIT_SCHEMA = "url-splits-v1"
ARTIFACT_SCHEMA = "url-artifact-v1"
FEATURE_SCHEMA = "url-lexical-v1"
MAX_URL_CHARS = 2048

class UnsupportedUrl(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)

class DatasetError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)

@dataclass(frozen=True)
class ParsedUrl:
    model_url: str
    host: str
    domain_group: str
    flags: tuple[str, ...]

@dataclass(frozen=True)
class UrlRow:
    case_id: str
    original_url: str
    url: str
    label: int
    domain_group: str
    source_ref: str
    source_date: str | None = None

@dataclass(frozen=True)
class DatasetBundle:
    rows: tuple[UrlRow, ...]
    manifest: dict

@dataclass(frozen=True)
class SplitBundle:
    partitions: dict[str, tuple[UrlRow, ...]]
    manifest: dict

@dataclass
class Selection:
    model: object
    branch: str
    raw_threshold: float | None
    config: dict
    report: dict

@dataclass(frozen=True)
class Calibration:
    status: str
    slope: float | None
    intercept: float | None
    threshold: float | None
    report: dict

@dataclass
class RunBundle:
    selection: Selection
    calibration: Calibration
    provenance: dict

@dataclass(frozen=True)
class UrlAssessment:
    state: str
    decision: str | None
    model_version: str | None
    evidence: tuple[str, ...]
    uncertainty: tuple[str, ...]
    unavailable_checks: tuple[str, ...]
    recommended_action: str
    probability: float | None = None

    def to_dict(self):
        value = asdict(self)
        if self.probability is None:
            del value["probability"]
        return value
