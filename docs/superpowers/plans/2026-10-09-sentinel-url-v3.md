# Sentinel URL v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a reproducible Mendeley/PhreshPhish URL experiment with protected historical domains, defensible coverage checks and either measured frozen evaluation or an explicit unavailable outcome.

**Architecture:** Add a focused `sentinel/url_v3/` orchestration package. Reuse the v2 catalog/observation/audit serialization, offline parser, component allocation utilities and existing model/metric factories; implement v3 ownership and integrity boundaries explicitly. Extend shared provenance/artifact dispatch and worker monitoring without changing v1/v2 schema meanings or default application startup.

**Tech Stack:** Windows x64 CPython 3.11; stdlib HTTP/CSV/JSON/SQLite/unittest; existing pinned NumPy/scikit-learn/joblib/psutil/threadpoolctl/idna/tldextract. Use the verified 17-pin union environment; no dependency installation or lock change is planned.

**Spec:** [Approved URL-v3 specification](../specs/2026-10-09-sentinel-url-v3-design.md), approved on 2026-10-09. [Source investigation](../../url-data-expansion-feasibility-2026-10-09.md) provides reconnaissance, not frozen performance evidence.

**Status:** Approved by the user with implement on 2026-10-09. Execution in progress, inline with one independent final review.

## Global Constraints

- Preserve v1 artifact/environment, v2 sources/audit/protocol, cases and the empty paired-message intake; learned application warnings remain disabled.
- Ryzen 7 7435HS, 16 GiB RAM, CPU-first; four native training threads; `8589934592` bytes maximum fitting process-tree memory; sequential fresh-process fits.
- Windows CPython 3.11; keep `requirements-ml-win-py311.lock.txt` and `requirements-url-data-win-py311.lock.txt` unchanged.
- HTTP(S) strings at most `2048` characters; no submitted destination, DNS, HTML, DOM/pickle dataset, dataset script or paid-service requests.
- PhreshPhish revision `eabec4b7a66324b79cc8a0ad856d1731dc26fe1a`; exact labels `benign -> 0` and `phish -> 1`; reuse complete original observations, including exclusions.
- Mendeley source `mendeley-webpage-2020`, revision `c2gw7fy2j4.3`, DOI `10.17632/c2gw7fy2j4.3`, Hannousse/Yahiouche, CC BY 4.0.
- Only `dataset_B_05_2020.csv`, file ID `575316f4-ee1d-453e-a04f-7b950915b61b`, `3661166` bytes, SHA-256 `21093e2902e5441c86a6daf95e86e7c332046e477fdf109a579d7bd81e586d6c`; changed identity fails.
- Inventory `https://data.mendeley.com/public-api/datasets/c2gw7fy2j4/files?folder_id=root&version=3`; file request `https://data.mendeley.com/public-files/datasets/c2gw7fy2j4/files/575316f4-ee1d-453e-a04f-7b950915b61b/file_downloaded`.
- HTTPS/443 only on `data.mendeley.com` and `prod-dcd-datasets-public-files-eu-west-1.s3.eu-west-1.amazonaws.com`; no credentials/downgrade/other hosts; close intermediate redirect bodies without reading them.
- Identity encoding, `30` second timeouts, `3` total attempts/resource, `2097152` byte metadata/page cap, `4194304` byte CSV cap, durable `16777216` byte acquisition received-body budget including retries/rejected final bodies.
- Strict UTF-8, optional BOM; exactly one `url` and `status` header, no duplicate/empty headers; consistent record width; `16384` byte fields, at most `20000` logical data records.
- Exact Mendeley labels `legitimate -> 0` and `phishing -> 1`; unknown/missing cells retain exclusions. Row dates/opaque IDs null; May 2020 is source documentary evidence only.
- Unchanged parser and private-inclusive PSL SHA-256 `e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66`.
- Keep `url-source-catalog-v2`/`url-dataset-v2` serialization; study schemas `url-ml-config-v3`, `url-protocol-v3`, `url-development-envelope-v3`, `url-provenance-v3`, `url-artifact-v3`, `url-format-diagnostic-v3`, `url-final-evaluation-v3`, `url-research-status-v3`.
- Exact development keys `{train, validation, calibration}`; exact final keys `{primary, supplemental}`; no v2 verifier expecting `external`.
- Ownership priority: all old primary-reserved domains, then fixed Mendeley supplemental reservation, then pooled development; complete connected components only.
- Supplemental selection: SHA-256 ASCII `url-v3-mendeley-final|42|` + component ID; first eight bytes unsigned big-endian < `2**63`. Never retry seeds or borrow final rows.
- Development cap `200000`; include all eligible Mendeley development components and their eligible rows first. Overflow fails `mandatory_development_components_exceed_cap`; fill with seeded whole Phresh-only components.
- Target train/validation/calibration `80/10/10`, seed `42`; record actual fractions.
- Train: `1000` rows/`100` domain groups per class. Validation, calibration, primary, supplemental: `100` rows/`30` domain groups per class.
- Actual train, pooled development and both final tracks: legitimate minimum `100` non-root paths, `100` non-www URLs, `30` queries. Both sources in pooled development: `100` rows/`30` domains per class.
- Verify all physical inputs and all gates before any learner/pilot; frozen failures produce null metrics/no artifact and cannot be repaired in place.
- Six character TF-IDF/logistic and four lexical HGB configurations; whole-component pilot <= `2000` training rows; select validation recall under `0.05` FPR, record `0.01` sensitivity; calibration partition only.
- Both learned branches must have admissible candidates; four-feature format diagnostic is never deployable. Source IDs, dates, ordinals, labels, partitions and domain-group IDs are not features.
- Artifacts: six shared files plus `protocol.json`, `diagnostic.json`, `diagnostic.joblib`; exact membership/hashes and metadata checked before locally trusted deserialization.
- Final tracks scored separately; whole-component bootstrap `1000` replicates/seed `42`; legitimate-query subgroup reports false positives, denominator and uncertainty, not phishing recall/F1.
- Private final-access receipt precedes scoring; no subsequent fitting to that protocol; only identical artifact/protocol/settings can resume a failed evaluation; output renaming does not reset access.
- New ignored `data/url-ml-v3/` and immutable ignored `models/url-ml/url-v3`; public aggregates under `output/research/url-ml-v3/` contain no row URLs, identifiers, tokens or private paths. Documentation/cards may contain bibliographic links.
- ISCX/Phish360 acquisition, v1 transfer comparison, contemporary collection, other ML modules and activation are separate milestones.

## Review Focus

1. Interrupted downloads, orphan files and competing acquisition processes must not bypass the durable byte budget or publish a partial source (Task 3).
2. Quoted multiline CSV, BOMs and multibyte fields must retain logical ordinals and enforce byte limits without guessing labels (Task 4).
3. A contradiction removing the last old primary row must not release its protected domain, or create a Mendeley-only primary case (Tasks 2 and 5).
4. Opaque links creating a component larger than the remaining cap must preserve the entire component; mandatory overflow fails rather than truncates (Task 5).
5. Failure during first final scoring, concurrent fit/evaluation and a renamed report destination must preserve final access and prevent refitting (Tasks 6 and 9).

---

## File map and execution context

Paths are relative to `C:\Users\Jason Dsouza\Desktop\major project` or its isolated execution checkout. The empty OneDrive chat directory is not the repository. After plan approval, use the worktree skill and inspect applicable `AGENTS.md`; plan preparation itself needs no worktree.

| File | Responsibility |
| --- | --- |
| `sentinel/url_v3/__init__.py`, `contracts.py`, `configs/url-ml-v3.json` | Stdlib v3 records, exact settings and schema boundaries |
| `sentinel/url_v3/binding.py` | Read-only historical verification and complete primary-domain anchors |
| `sentinel/url_v3/transport.py`, `mendeley.py` | Durable bounded official transport and URL/status projection |
| `sentinel/url_v3/sources.py` | Joint catalog and original observation stream; shared disk audit |
| `sentinel/url_v3/protocol.py` | V3 components, ownership, mandatory cap, gates and frozen publication |
| `sentinel/url_v3/compat.py`, `access.py` | Reverification, development envelope and final-access/stage locks |
| `sentinel/url_v3/training.py` | Whole-component pilot, bounded reused learners/calibration/diagnostic |
| `sentinel/url_v3/artifacts.py`, `evaluation.py` | V3 sidecars, two-track evaluation and aggregate publication |
| `sentinel/url_v3/cli.py` | Explicit research stages and sanitized failures |
| `sentinel/url_ml/provenance.py`, `artifacts.py` | Explicit v3 schema dispatch preserving v1/v2 |
| `sentinel/url_ml/training.py` | Shared process-tree resource enforcement |
| `tests/url_v3_fixtures.py`, `tests/test_url_v3_*.py` | Synthetic software fixtures and boundary/regression tests |
| `docs/url-v3-workflow.md`, `docs/url-v3-delivery-record.md` | Reproduction, attribution, measured outcome and review record |
| `output/research/url-ml-v3/research-status.json`, `model-card.md` | Inspected aggregate status; evaluation only when actually completed |

Modify `.gitignore` in Task 1; README/next steps in Task 11. No web/extension/database/intake/launcher edits. Reuse existing v2 storage, audit, `Union`, `choose_components` and `_allocation` helpers directly; do not copy entire modules.

PowerShell commands below use:

```powershell
$sentinelPython = 'C:\Users\Jason Dsouza\Desktop\major project\.venv-url-v2-check\Scripts\python.exe'
$sentinelNode = 'C:\Users\Jason Dsouza\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
```

Run from the execution checkout. Scoped tests use `& $sentinelPython -m unittest discover -s tests -p '<test_filename>' -v` because existing fixtures are imported from the tests directory. Full suite: `& $sentinelPython -m unittest discover -s tests -v`. Node: `& $sentinelNode --test tests/web_client.test.mjs`. Check exit codes and skip counts; do not assume an unavailable environment passed.

## Shared interfaces

Reuse `SourceCatalog`, `Observation`, `AuditBundle`, `ResearchRun` from v2 and `UrlRow`, `SplitBundle`, `RunBundle`, `DatasetError`, `UrlParser` from URL ML. New frozen records:

- `V2Binding(root: Path, v2_root: Path, catalog: SourceCatalog, anchor_domains: tuple[str, ...], primary_owners: dict[str, tuple[str, ...]], manifest: dict)`. `primary_owners` maps original primary case IDs to original owning Phresh test observation IDs.
- `V3Splits(development: SplitBundle, tracks: dict[str, tuple[UrlRow, ...]], component_by_case: dict[str, str], sources_by_case: dict[str, tuple[str, ...]], manifest: dict, root: Path | None = None, audit_root: Path | None = None, study_root: Path | None = None)`.
- Every staged directory has `manifest.json` and checked file digests. Binding manifest includes original catalog/projection/audit/protocol identities, sorted `anchors.jsonl` checksum and original `primary-owners.jsonl` checksum. Protocol preserves those hashes and v3 config/source identities.
- Test helpers in `tests/url_v3_fixtures.py`: `synthetic_v2_root(root: Path) -> tuple[Path, dict, UrlParser]`; `synthetic_study(root: Path, *, scenario: str = "balanced") -> tuple[V3Splits, dict, UrlParser]`; `small_v3_research(root: Path) -> tuple[ResearchRun, V3Splits, dict, UrlParser]`. Add each helper as its owning binding/protocol/training implementation lands. Synthetic config reductions stay inside test construction; production `load_config` accepts only the declared values.

### Task 1: Versioned settings and provenance

**Files:** Create `sentinel/url_v3/__init__.py`, `contracts.py`, `configs/url-ml-v3.json`, `tests/url_v3_fixtures.py`, `tests/test_url_v3_contracts.py`. Modify `sentinel/url_ml/provenance.py:validate_provenance` and `.gitignore`.

**Interfaces:** Produce `default_config() -> dict` and `load_config(path: Path) -> dict` in v3 contracts and the shared records above; extend `validate_provenance(value: dict, *, stage: str) -> None` with v3-specific required hashes/schema pairing.

- [x] Write failing `ContractTests` pinning production config, exact key shape, boolean-as-number rejection, foreign v2 schema rejection and digest meanings:
  `assert config["schema"] == "url-ml-config-v3"`; `assert config["training"]["native_threads"] == 4`; `assert config["training"]["max_peak_bytes"] == 8589934592`; `assert config["split"]["development_max_rows"] == 200000`. V3 provenance without `parent_v2_protocol_sha256`/`protected_domains_sha256` or with `source_sha256` must raise `DatasetError`.
- [x] Run `& $sentinelPython -m unittest discover -s tests -p 'test_url_v3_contracts.py' -v`; expect missing v3 contracts/schema support.
- [x] Implement exact config validation with Mendeley source pins/transport/CSV settings, split/source gates and unchanged model-grid values; reuse v1 training settings as the nested factory configuration. Add ignored v3 data root and v3 provenance branch without relaxing old validation.
- [x] Run the contract command and existing `test_url_v2_contracts.py`; expect all pass.
- [x] Commit only these paths: `feat: define frozen URL v3 contracts and provenance`.

### Task 2: Read-only v2 binding and protected anchors

**Files:** Create `sentinel/url_v3/binding.py` and `tests/test_url_v3_binding.py`; extend binding fixtures.

**Interfaces:** Consume existing `load_catalog(root)`, `iter_phresh_observations(root, catalog)`, `load_audit(root, catalog, parser)` and `load_protocol(audit, catalog, root, config)`. Produce `bind_v2(v2_root: Path, output_dir: Path, config: dict, parser: UrlParser) -> V2Binding` and `load_v2_binding(root: Path, config: dict, parser: UrlParser) -> V2Binding`.

- [x] Write failing tests proving failed v2 support remains valid historical input, changed projection/audit/ownership bytes fail, and excluded primary-component members contribute anchors:
  `assert binding.anchor_domains == tuple(sorted(expected_reserved_domains))`; `assert binding.primary_owners == expected_original_primary_owners`; `assert before_hashes == after_hashes`. A fabricated anchor list fails loading; a primary case whose sole row is later conflicted still has its domain reserved. Verify exactly one original primary track without treating an unavailable v2 training gate as corruption.
- [x] Run `& $sentinelPython -m unittest discover -s tests -p 'test_url_v3_binding.py' -v`; expect missing binding implementation.
- [x] Implement loaders without `assert_training_ready`. Verify historical catalog/projection/audit/protocol semantics; reconstruct the original combined catalog with v2 merge behavior for historical verification, retaining the primary catalog for projection. Consume the complete original projection, and derive anchors from all original primary-reserved components, including overlap exclusions. Atomically write sorted anchors/primary owners and binding hashes; never write to the v2 input root.
- [x] Run the binding command and existing `test_url_v2_protocol.py`; expect all pass and unchanged fixture input hashes.
- [x] Commit `binding.py` and its fixtures/tests: `feat: bind URL v2 history and protected domains read only`.

### Task 3: Bounded official Mendeley transport

**Files:** Create `sentinel/url_v3/transport.py` and `tests/test_url_v3_transport.py`.

**Interfaces:** Produce `AcquisitionSession(root: Path, config: dict)` with context-manager lock ownership, `fetch(url: str, target: Path, *, resource: str, max_bytes: int) -> dict` and `snapshot() -> dict`. A receipt records complete-body bytes/SHA and durable cumulative received bytes; it never records signed URLs. Reuse approved redirect logic/atomic storage primitives.

- [x] Write failing transport tests for all five urllib redirect statuses, credentials/downgrade/port/host rejection, oversized/chunked/rejected final bodies, three total attempts, and crash/orphan/concurrent recovery:
  `assert session.snapshot()["received_body_bytes"] <= 16777216`; `assert attempts == 3`; `assert redirect_body.read_calls == 0`; `assert not partial_source_published`. Pre-existing unregistered target is not trusted; complete verified receipts may be reused; interrupted bytes remain charged.
- [x] Run `& $sentinelPython -m unittest discover -s tests -p 'test_url_v3_transport.py' -v`; expect missing session.
- [x] Implement exclusive acquisition lock and atomic durable ledger updates while reading bounded chunks. Include bytes from retries/errors, identity encoding, timeout 30 and resource limits. Close redirects without draining; use bounded unique pending files and checksum/size validation before replacing only unregistered temporary targets.
- [x] Run transport tests and existing `test_url_v2_ranges.py`; expect pass.
- [x] Commit `transport.py`/tests: `feat: meter and bound official Mendeley acquisition`.

### Task 4: CSV projection and provenance-preserving joint audit

**Files:** Create `sentinel/url_v3/mendeley.py`, `sources.py`, `tests/test_url_v3_sources.py`. Extend source fixtures; reuse `sentinel/url_v2/audit.py` unchanged unless a reproducible shared-contract bug requires its own regression.

**Interfaces:** Consume `AcquisitionSession`/`V2Binding`. Produce `acquire_mendeley(root: Path, config: dict) -> SourceCatalog`, `load_mendeley(root: Path, config: dict) -> SourceCatalog`, `iter_mendeley_observations(root: Path, catalog: SourceCatalog) -> Iterator[Observation]`, `joint_catalog(binding: V2Binding, mendeley: SourceCatalog) -> SourceCatalog` and `audit_v3(binding: V2Binding, source_root: Path, config: dict, parser: UrlParser, output_dir: Path) -> AuditBundle`.

- [x] Write failing tests for official inventory/file identity and full size/SHA; invalid UTF-8/header/record widths; empty URL/status and unknown labels; BOM, embedded quoted newlines, multibyte field > `16384` bytes and record `20001`. Assert ordinals `[1, 2]` for two logical records despite quoted newlines, dates/opaque IDs `is None` and observation identity `manifest_hash({"source_id": ..., "revision": ..., "reference": ...})`. Use Mendeley `original_partition="source"` and reference keys `{"file_id": pinned_id, "file_sha256": pinned_sha, "record": ordinal}`; observation IDs remain the shared identity hash. Cross-source canonical conflict with malformed ancillary metadata must exclude both labels and retain original reasons.
- [x] Run `& $sentinelPython -m unittest discover -s tests -p 'test_url_v3_sources.py' -v`; expect missing adapter.
- [x] Implement exact official page/inventory attribution and pinned download under Task 3 budgets. Publish complete CSV/projection/receipts atomically, project only URL/status/pinned reference and ignore the 87 features. Stream original Phresh observations and all Mendeley observations into shared disk audit. Compose explicit multi-source catalog without v2's misleading external-only role field.
- [x] Run source tests and existing `test_url_v2_audit.py`; expect pass and no destination requests.
- [x] Commit adapter/fixtures/tests: `feat: project Mendeley URL labels and audit joint sources`.

### Task 5: Frozen v3 ownership, cap and support gates

**Files:** Create `sentinel/url_v3/protocol.py` and `tests/test_url_v3_protocol.py`; extend `synthetic_study`.

**Interfaces:** Consume shared `iter_records`/`iter_provenance`, `Union`, `choose_components`, `_allocation` and verified binding. Produce `supplemental_reserved(component_id: str) -> bool`, `freeze_protocol(audit: AuditBundle, catalog: SourceCatalog, binding: V2Binding, config: dict, output_dir: Path, *, study_root: Path) -> V3Splits`, `load_protocol(audit, catalog, binding, root: Path, config: dict, *, study_root: Path) -> V3Splits` and `assert_training_ready(splits: V3Splits) -> None`.

- [x] Write failing tests asserting primary IDs are a subset of original primary IDs, primary owners are surviving old Phresh test IDs, supplemental owners are Mendeley only and every component has one destination. Pin the hash by computing independently from `b"url-v3-mendeley-final|42|"` and first-eight-byte big-endian comparison. Conflict removal never releases an anchor; a new Mendeley row on it is reserved but not added to primary.
- [x] Add failing gate/cap tests: `1000/100` train and `100/30` other per-class row/domain minima; query support `29` fails for actual train or either final track despite pooled support; missing source class support fails. Mandatory sum `200001` raises `mandatory_development_components_exceed_cap`; a nonmandatory oversized component is skipped whole; reversing input order preserves assignments.
- [x] Run `& $sentinelPython -m unittest discover -s tests -p 'test_url_v3_protocol.py' -v`; expect missing freeze.
- [x] Implement component reservation/ownership, retaining all original primary removals and observation-pruning reasons. Keep whole mandatory Mendeley components before Phresh-only cap fill and existing 80/10/10 allocation. Publish assignments/components/owners/pruning/exclusions plus measured source/class/format/domain/component support with parent/anchor hashes.
- [x] Run protocol and existing `test_url_v2_protocol.py` tests; expect all ownership, cap, deterministic allocation and support assertions pass.
- [x] Commit protocol/fixtures/tests: `feat: freeze protected URL v3 cohorts and coverage gates`.

### Task 6: Verified development boundary and final-access guard

**Files:** Create `sentinel/url_v3/compat.py`, `access.py`, `tests/test_url_v3_integrity.py`.

**Interfaces:** Produce `verify_frozen_splits(splits: V3Splits, config: dict, parser: UrlParser) -> dict`; `development_bundle(splits, config, parser) -> SplitBundle`; `study_guard(splits: V3Splits, *, stage: str) -> ContextManager[None]`; `assert_unscored(splits: V3Splits) -> None`; `begin_final_access(splits: V3Splits, artifact_sha256: str, settings_sha256: str) -> dict`; `finish_final_access(splits: V3Splits, *, status: str, report_sha256: str | None = None) -> None`.

- [x] Write failing tests for absent roots, extra `external`/shadow keys, changed labels/URLs, owners/components/assignments, parser/config/source/parent/anchor files and in-memory mutation. Assert learner/deserializer spies have `call_count == 0`. After a final access receipt, `assert_unscored` raises `final_protocol_already_accessed` even if report destination changes; differing artifact/settings cannot resume; concurrent study guards fail.
- [x] Run `& $sentinelPython -m unittest discover -s tests -p 'test_url_v3_integrity.py' -v`; expect missing boundary.
- [x] Implement v3-specific verification using original source/audit/protocol loaders and full row identity; expose only train/validation/calibration through the development envelope. Store exclusive final-access receipts keyed by protocol hash under the private study root, outside immutable protocol files. Hold one stage lock around pilot/train/evaluate; scoring failure preserves access, while identical artifact/protocol/settings may resume.
- [x] Run integrity tests and existing `test_url_v2_compatibility.py`; expect pass.
- [x] Commit boundary/tests: `feat: verify v3 fitting inputs and preserve final access`.

### Task 7: Process-tree bounded pilot and training

**Files:** Create `sentinel/url_v3/training.py` and `tests/test_url_v3_training.py`; modify `sentinel/url_ml/training.py:fit_candidate`/worker monitoring; extend existing training regressions and `small_v3_research`.

**Interfaces:** Keep shared `fit_candidate(rows, branch, params, parser, native_threads=4, max_peak_bytes=8589934592, *, pipeline_factory=None) -> tuple[object | None, dict]` compatible. Produce `component_pilot_rows(splits: V3Splits, maximum: int = 2000) -> tuple[UrlRow, ...]`, `pilot_v3(splits, config, parser) -> dict` and `train_v3(splits, config, parser) -> ResearchRun`. Internally produce `fit_checked(splits: V3Splits, config: dict, parser: UrlParser, rows: tuple[UrlRow, ...], branch: str, params: dict, *, pipeline_factory=None) -> tuple[object | None, dict]` to reverify before each monitored candidate/diagnostic fit.

- [x] Write failing tests with synthetic child processes whose combined RSS exceeds the ceiling while each individually fits; assert `status == "memory_budget_exceeded"`, `model is None` and descendants stopped. Use mocked process-memory samples or a deliberately small test ceiling, never an 8 GiB test allocation. Pin `6` char/`4` lexical configurations, four native threads, pilot whole train components <= `2000`, and no final-row fitting. Mutated/failing/scored study spies must record zero fits, including a sidecar changed between two candidate fits. Missing score variation/nonpositive calibration slope gives unavailable numerical confidence; diagnostic never wins deployment selection. A worker exception containing a URL, signed query or private path must not leak through progress stdout.
- [x] Run `& $sentinelPython -m unittest discover -s tests -p 'test_url_v3_training.py' -v`; expect missing trainer or process-tree regression.
- [x] Strengthen shared monitoring to sample worker plus descendants, retain tree/worker measurements, enforce ceiling before accepting returned models and clean up descendants. In v3 hold stage guard, verify gates/unscored inputs, reuse model factories, threshold/tie policy, calibration and four-feature format factory. Reverify physical inputs and unscored status at every learner entry, including later candidates, diagnostic and calibration, rather than only at train-command startup. Both learned branches require valid candidates; retain convergence/failure records and 5%/1% validation points; sanitize progress/failure stdout; validate v3 provenance/config and calibration-ID digests.
- [x] Run v3 and existing `test_url_ml_training.py`/`test_url_v2_training.py`; assert missing score variation/nonpositive calibration slope gives unavailable numerical confidence, and diagnostic never wins deployment selection. Expect pass.
- [x] Commit trainer/monitoring/tests: `feat: train URL v3 under process-tree resource limits`.

### Task 8: Trusted v3 artifacts and inference compatibility

**Files:** Create `sentinel/url_v3/artifacts.py`, `tests/test_url_v3_artifacts.py`, `tests/test_url_v3_compatibility.py`. Modify `sentinel/url_ml/artifacts.py:_validate_metadata, export_artifact, load_artifact` through explicit schema dispatch.

**Interfaces:** Produce `validate_research_metadata(provenance: dict, protocol: dict, diagnostic: dict, selection: dict, baselines: dict) -> None`, `validate_research_sidecars(root: Path, manifest: dict) -> tuple[dict, dict]`, `export_v3_artifact(research: ResearchRun, parser: UrlParser, output_dir: Path, version: str) -> dict` and `load_v3_artifact(path: Path) -> ResearchRun`. Preserve generic `load_artifact(path: Path) -> RunBundle` and service API.

- [x] Write failing tests asserting schema `url-artifact-v3` and exact six shared plus three sidecar files; missing/extra/hash/schema/provenance/config/threshold/parent mismatches fail with `joblib.load.call_count == 0`. Generic inference reads only `pipeline.joblib`; diagnostic is never deserialized there. Research loader rejects wrong diagnostic feature names/deployment eligibility.
- [x] Run `& $sentinelPython -m unittest discover -s tests -p 'test_url_v3_artifacts.py' -v`; expect unsupported v3 export/loading.
- [x] Implement shared schema-to-validator mapping with unchanged v1/v2 membership/trust/dependency/platform checks. Validate all v3 sidecars before pickle boundaries, then rebind unchanged offline parser. Document historical label/coverage limitations and source attribution in immutable card; artifact cannot overwrite or auto-activate.
- [x] Run v3 artifact/compatibility tests and old `test_url_ml_artifacts.py`, `test_url_v2_artifacts.py`, `test_url_v2_compatibility.py`. In a subprocess block Arrow import and assert explicit v3 inference works; `-S` default server still imports no NumPy/sklearn/Arrow, returns its original three analysis keys and leaves cases empty. Expect pass.
- [x] Commit artifact/compatibility paths: `feat: persist trusted URL v3 artifacts with compatible inference`.

### Task 9: Two-track frozen evaluation and honest subgroups

**Files:** Create `sentinel/url_v3/evaluation.py` and `tests/test_url_v3_evaluation.py`.

**Interfaces:** Consume shared `component_metrics`/`bootstrap_weights`/metric utilities and Task 6 access guard. Produce `legitimate_query_metrics(rows: tuple[UrlRow, ...], scores, threshold: float | None, groups, *, replicates: int = 1000, seed: int = 42) -> dict`, `evaluate_v3(splits: V3Splits, config: dict, parser: UrlParser, artifact_path: Path) -> dict`, `publish_evaluation(report: dict, output_dir: Path) -> dict` and `render_card(report: dict) -> str`.

- [x] Write failing tests pinning exact `primary/supplemental` report keys, both learned/rule/diagnostic comparisons and unchanged thresholds. On legitimate queries assert `false_positives == 1`, `rows == 4`, `false_positive_rate == 0.25` and no invented recall/F1. Bootstrap has `replicates == 1000`/`seed == 42`; small/constant support warns. First score exception leaves an accessed receipt; identical resumed scoring is allowed but a changed artifact or renamed-output refit is refused.
- [x] Run `& $sentinelPython -m unittest discover -s tests -p 'test_url_v3_evaluation.py' -v`; expect missing evaluator.
- [x] Implement pre-deserialization frozen verification, load trusted research artifact, bind calibration/protocol/config hashes, and record final access before scores. Score two tracks separately with fixed thresholds and shared whole-component uncertainty; add query-only FP bootstrap/denominators, full/pruned source counts, format/class errors, calibration where available, cold/warm latency and tree resources. Private score files bind IDs/artifact/protocol; public report/card contain aggregates only and correct same-source-held-out/temporal-unavailable limitations.
- [x] Run v3 evaluation and existing `test_url_v2_evaluation.py`. Publication refuses overwrite and raw URL/ID/private path payloads; scoring resume preserves prior failure/access receipts and publishes only a complete fixed report. Expect pass.
- [x] Commit evaluator/tests: `feat: evaluate frozen URL v3 tracks and query false positives`.

### Task 10: Explicit research CLI and reproducible workflow

**Files:** Create `sentinel/url_v3/cli.py`, `tests/test_url_v3_cli.py`, `docs/url-v3-workflow.md`; include attribution and all stage preconditions.

**Interfaces:** Produce `main(argv: list[str] | None = None) -> int`, `publish_research_status(splits: V3Splits | None, config: dict, output_dir: Path, *, stage: str, status: str, reason: str | None = None, metrics: dict | None = None) -> dict` in `evaluation.py`. Use shared private `save_failure` and sanitized aggregate stdout.

- [x] Write failing CLI tests for `bind-v2`, `acquire-mendeley`, `audit`, `freeze`, `pilot`, `train`, `evaluate`, `predict`; `--root` required except predict, `--v2-root` required only bind, paths with spaces, foreign schema/wrong Python, staged failures and zero automatic startup work. Failed gates assert `metrics is None`, `models_fitted is False` and preserved diagnostic/nonzero pilot/train exit.
- [x] Run `& $sentinelPython -m unittest discover -s tests -p 'test_url_v3_cli.py' -v`; expect missing CLI.
- [x] Implement common `--config`/`--psl` defaults; immutable `binding`, `sources/mendeley`, `audited`, `protocol` directories under root. `train --artifact` exports a candidate; `evaluate --artifact --output` scores without fitting; `predict --artifact --url` uses only trusted artifact. Freeze can record successful freezing with `training_ready: false`, while pilot/train refuse it. Publish truthful aggregate failure/unavailable status with no raw/private stdout values.
- [x] Run CLI/compatibility tests and full Python/Node suites; expect every installed-environment test passes with zero dependency skips. Verify both lock hashes and unchanged protected assets; inspect tracked diff for source/model data.
- [x] Commit CLI/workflow/status paths: `feat: expose explicit URL v3 research workflow`.

### Task 11: Real measured run, final independent review and delivery

**Files:** Create `docs/url-v3-delivery-record.md` and measured aggregate `output/research/url-ml-v3/research-status.json`/`model-card.md`; final `evaluation.json` only if completed. Update `README.md`, `docs/next-steps.md` and this plan's checked tasks/ledger.

**Interfaces:** Execute Task 10 stages against preserved primary v2 input, new v3 private root and immutable candidate path. Public status fields include `schema`, `stage`, `status`, `models_fitted`, `metrics`, measured support and identities; never insert reconnaissance counts as real-run measurements.

- [x] Record pre-run hashes of v1 artifact/locks, v2 catalog/projection/audit/protocol files, `data/cases.db` (plus present SQLite sidecars) and `data/curation/intake.csv` state; validate interpreter/dependency versions. Use a new private execution root and keep original v2 input read-only. Do not copy model/source bytes into tracked output.
- [x] Run and log actual `bind-v2` -> `acquire-mendeley` -> `audit` -> `freeze` sequentially using workflow commands; verify CSV `3661166` bytes/pinned SHA, all source counts, parent binding and measured primary-reserved domain extraction against reconnaissance `78202`. A mismatch is investigated, never normalized away.
- [x] Inspect all frozen class/domain/source/format gates and publish measured status. If any fails, preserve failed protocol, null metrics and no artifact, skip pilot/train/evaluate and continue delivery/review of the functioning software plus negative research outcome. No alternate seed/cap/reservation/source rescue belongs to this study.
- [x] If every gate passes, run resource pilot then ten-configuration training, export `models/url-ml/url-v3`, verify artifact and score final tracks once. On resource/model/calibration/evaluation failure preserve receipts, report actual completed stage and follow only specified identical-input recovery; never claim a completed evaluation that did not run.
- [x] Run the full Python and 12-check Node suite after any final code changes; confirm zero skips and stdlib-only compatibility. Verify protected file hashes unchanged, no tracked raw URLs/IDs/private paths/binaries, and default learned warnings disabled. Save exact commands, outcomes, timings and limitations in delivery record.
- [x] Use `superpowers:requesting-code-review` for the single independent final reviewer already selected by the user. Request spec/plan coverage, source/ownership/leakage, input/artifact boundaries, process-tree budget, access ledger, truthful measurements and regression review. Apply substantiated fixes with targeted/full checks under receiving-review and verification skills; record each disposition. No extra task-by-task agents or repeated clean review.
- [ ] Commit scoped code/docs/aggregate deliverables, integrate using the finishing-branch skill and existing repository authorization, and push the verified branch to the existing private repo. Preserve ignored proof/source/model assets before removing an execution worktree; compare copied digests and actual root coverage.
- [ ] Record final local/remote commit equality and completed outcome in the plan/delivery ledger. Report measured result or specific unavailable stage, existing limitations and the next separately scoped milestone; application activation still requires its own validation decision.

## Self-review and completion criteria

All source/transport/CSV/provenance requirements map to Tasks 1-4; reservation/ownership/cap/source/format gates to Task 5; mutable inputs and access to Task 6; modelling/resource/calibration to Task 7; trusted compatibility to Task 8; frozen metrics/privacy/resume to Task 9; explicit failures/workflow to Task 10; real outcome, protection and independent review to Task 11. Each Review Focus item has a named owning test. Interfaces use the same records/signatures throughout; v3 never calls the v2 training guard.

Software completion requires tested implemented stages and preserved prior assets. Research completion requires actual gate-passing fitting/frozen evaluation; otherwise the deliverable is an explicit negative or incomplete research outcome with unavailable metrics, never synthetic accuracy. This plan does not promise the supplemental/training query gates will pass.

## Plan-scoped execution ledger

Implementation authorized on 2026-10-09. Execution is isolated in the Sentinel URL-v3 worktree; the plan-scoped ledger records task proofs. The actual source admission and freeze passed every predeclared gate. Pilot, ten-configuration training and one-time frozen evaluation completed on 2026-10-11 local time. The measured supplemental false-positive rate blocks learned application warnings.

Task 1 evidence: 4 v3 and 6 v2 contract checks passed; full Python suite 134/134, zero skips, 114.774s. Baseline web checks 12/12. No source acquisition or fitting performed.

Tasks 2-10 implemented and committed on `codex/url-v3` through `64800cc`: read-only v2 binding, bounded Mendeley acquisition/CSV, joint observation audit, fixed ownership/cohorts, mutable-input/final-access guards, process-tree-bounded training, trusted artifacts, frozen evaluation and explicit CLI. Their per-task RED/GREEN checks and rulings are in the private plan workspace ledger. After Task 10, the whole Python suite passed 189/189 and the Node web suite 12/12 with zero skips.

Task 11 source run: 27 original assets and 17 exact installed pins snapshotted before any new stage. `bind-v2` verified 78,202 protected domain groups and 166,369 original primary cases. The pinned Mendeley CSV was fully checksummed (3,661,166 bytes, 11,430 observations). Joint audit admitted 671,521 canonical URLs from 677,745 observations, with 63 non-conflicting duplicates. Freeze retained all old primary cases, reserved 4,348 supplemental cases, and produced a 200,000-row development set with all gates passing; legitimate queries number 54 in development and 43 in training. The protocol digest and exact stage timings are in [the delivery record](../../url-v3-delivery-record.md). The single final access is complete: primary F1 0.9271/FPR 5.76%, supplemental F1 0.8388/FPR 22.39%; legitimate-query false positives 13/52 and 27/44. The candidate remains disabled in the app.

Task 11 final run: pilot 2,000 whole-component rows succeeded within the 8 GiB tree cap. All ten training configurations fitted; the immutable candidate manifest is `1ccaa15e08e6baae002d6cbe9505e4161ef44f2539a590feed8a2e7e9d124896`. The one-time evaluation published 166,369 primary and 4,348 supplemental cases; its JSON SHA-256 is `a6308501297956298e78bb9f6ff05e155cd92a2881f55f8e8df7c8c1d651b204`. The final-access receipt is complete; 27 protected files, 17 exact package pins and the empty paired intake are unchanged. Whole suite after review fix: 191 Python and 12 Node checks, zero skips. One benign `example.com` smoke inference was falsely flagged; live activation is excluded. Independent review found one Important buffered-read budget bug, fixed with a real HTTPResponse regression; integration remains.
