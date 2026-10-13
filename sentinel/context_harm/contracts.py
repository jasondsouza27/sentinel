"""Lightweight immutable contracts shared by research and submitted content."""
from dataclasses import dataclass, field
from pathlib import Path


class HarmError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class HarmCriteria:
    train_per_class: int = 200
    validation_per_class: int = 30
    calibration_per_class: int = 30
    development_components: int = 10
    test_per_class: int = 100
    test_threads: int = 30
    max_component_fraction: float = 0.70


PRODUCTION_CRITERIA = HarmCriteria()


@dataclass(frozen=True)
class ModelText:
    target: str
    context: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversationInput:
    target_id: str | None
    model_input: ModelText
    turns: tuple[dict, ...]
    coverage: dict
    language: str
    language_assumed: bool


@dataclass(frozen=True)
class CadUtterance:
    case_id: str
    thread_id: str
    parent_id: str | None
    root_id: str | None
    author_id: str | None
    order: tuple[str, ...]
    text: str
    split: str
    labels: tuple[str, ...]
    context_tags: tuple[str, ...]
    eligible: bool
    text_supported: bool
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SourceRelease:
    records: tuple[CadUtterance, ...]
    provenance: dict


@dataclass(frozen=True)
class HarmCase:
    case_id: str
    model_input: ModelText
    context_ids: tuple[str, ...]
    thread_id: str
    label: int
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CaseCohort:
    primary: tuple[HarmCase, ...]
    diagnostics: tuple[HarmCase, ...]
    source: SourceRelease
    audit: dict


@dataclass(frozen=True)
class FrozenStudy:
    path: Path
    manifest: dict


@dataclass(frozen=True)
class CandidateRef:
    kind: str
    config_id: str
    directory: Path
    fit_record: dict


@dataclass(frozen=True)
class ScoreBatch:
    case_ids: tuple[str, ...]
    scores: tuple[float | None, ...]
    coverage: tuple[bool, ...]
    runtime: dict


@dataclass(frozen=True)
class Selection:
    candidate: CandidateRef
    raw_threshold: float | None
    validation_report: dict


@dataclass(frozen=True)
class CalibrationRecord:
    status: str
    slope: float | None
    intercept: float | None
    report: dict


@dataclass(frozen=True)
class WorkerLimits:
    deadline_seconds: int
    rss_bytes: int
    native_threads: int = 4


@dataclass(frozen=True)
class WorkerRecord:
    status: str
    reason: str | None
    measurements: dict
    output: dict
