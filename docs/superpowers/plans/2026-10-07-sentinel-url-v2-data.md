# Sentinel URL v2 Data and Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver reproducible URL-only imports, a provenance-preserving frozen v2 experiment and measured robustness reports without activating a learned model in the application.

**Architecture:** Add `sentinel/url_v2/` beside `sentinel/url_ml/`. Keep acquisition/Parquet decoding in a separate environment; convert validated development data to existing training records and reuse the two CPU factories. Extend artifact provenance explicitly while retaining v1 validation/loading.

**Tech Stack:** Windows x64 CPython 3.11, stdlib HTTP/CSV/JSON/SQLite/unittest, pinned PyArrow for acquisition, existing locked scikit-learn/NumPy/idna/tldextract/joblib/psutil for modelling.

**Spec:** [Approved URL v2 design](../specs/2026-10-07-sentinel-url-v2-data-design.md), approved on 2026-10-07. [Source audit](../../url-v2-source-audit.md) records feasibility evidence.

**Status:** Approved by the user on 2026-10-07 for inline implementation with one independent final review. Execution in progress; checked tasks and the plan-scoped ledger record verified deliverables.

## Global Constraints

- Preserve v1 data, assignments, artifact, results and model dependency lock. New ignored root `data/url-ml-v2/`; immutable versions under `models/url-ml/`.
- Ryzen 7 7435HS, 16 GiB RAM, CPU-first: "at most four native training threads" and "at most 8 GiB training-process RAM" (`8589934592` bytes). One fit/shard read at a time; no compulsory paid service.
- "HTTP(S) inputs capped at 2,048 characters"; "no request to a submitted destination." No dataset scripts, source pickle, HTML columns, rendering, crawling or DNS checks.
- PhreshPhish revision `eabec4b7a66324b79cc8a0ad856d1731dc26fe1a`; columns `url`, `label`, `date`, `sha256`; `benign -> 0`, `phish -> 1`. Labels are historical annotations.
- Only documented ISCX benign/phishing categories; official local acquisition and audited member mapping required. No forms, mirrors or guessed labels/dates/schemes. Unknown schemas fail.
- HTTPS allowlist `huggingface.co`, `us.aws.cdn.hf.co`; additional hosts require endpoint audit. Signed query strings never enter manifests/logs.
- "30-second network timeout," "at most three retries per failed range," "2 MiB footer limit," "32 MiB individual selected-column range limit," "2 GiB total acquired response bytes for one projection run." Byte limits `2097152`, `33554432`, `2147483648`; count retries/rejected bodies, persist cumulative budget on resume.
- "Decode at most 4,096 rows per batch with decoding threads disabled." Disable prebuffering; refuse excluded-column ranges; no whole-file fallback or concurrent shards.
- Freeze corrected parser code hash/revision and private-inclusive PSL SHA-256 `e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66`; no suffix auto-update.
- Retain all observation provenance; exclude all canonical-URL label conflicts. Catalog and individual file digests have separate names. Source IDs/splits/dates are never features.
- Reserve published PhreshPhish test. Development target `80/10/10`, seed `42`, whole-group cap `200000`. Domain/IP/equivalent URL/same-source opaque-ID links cannot cross partitions/tracks.
- Training: `1000` rows/`100` components per class; validation/calibration/evaluable final tracks: `100` rows/`30` components per class. Development and primary-test benign coverage: `100` non-root paths, `100` non-www hosts, `30` query-bearing URLs; overlapping strata allowed.
- Authentic date semantics and strict development-before-test separation are required for a temporal claim. Unknown/failed chronology means unavailable, never a score-dependent cutoff change.
- Reuse six character TF-IDF/logistic and four lexical HGB configurations; validation budgets `.05` primary and `.01` sensitivity. Thresholds use validation only; calibration uses separate rows and existing support/variation/positive-slope guards.
- Frozen evaluation: `1000` whole-component bootstrap replicates, seed `42`; disclose constant outcomes/tiny subgroups. Separate sources alone do not prove independence.
- No accuracy evidence from synthetic fixtures/staged examples/personal cases. Raw URLs/tokens/row errors stay private. No automatic v2 activation or safe verdict; negative/incomplete research outcomes are valid.

## Review Focus

1. Expiring signed redirects/interrupted bodies must not reset budgets, reuse partial bytes or leak query strings (Task 2).
2. Footers naming external files, overlapping chunks or excluded HTML must fail before data requests (Task 3).
3. Cross-source contradictory duplicates/ambiguous dates need retained provenance, conflict exclusion and honest chronology (Task 5).
4. Opaque IDs joining domains into giant components cannot be cut to rescue size/class/format targets (Task 6).
5. Missing external data, changed frozen assignments and repeated evaluation cannot become passed tracks or overwrite evidence (Tasks 8-10).

## File map and execution context

Paths below are relative to `C:\Users\Jason Dsouza\Desktop\major project` or its isolated execution checkout. The stale OneDrive chat directory is not the repository. Use the worktree skill at execution time after plan approval; recheck scoped `AGENTS.md`. Do not create a worktree merely for plan review.

| File | Responsibility |
| --- | --- |
| `sentinel/url_v2/__init__.py`, `contracts.py`, `storage.py` | Stdlib records/config, immutable publication/failure journals |
| `catalog.py`, `ranges.py` | Pinned inventory, bounded source transport/cache |
| `projection.py` | Footer/layout validation and metadata-only decoding |
| `iscx.py` | Audited local member adapter, no acquisition network |
| `audit.py` | Canonical rows, all observations/exclusions, source/format audits |
| `protocol.py`, `compat.py` | Frozen components/ownership/gates; development-only training envelope |
| `format_baseline.py`, `training.py` | Four-feature diagnostic, reused fits, validation sensitivity |
| `artifacts.py`, `evaluation.py`, `cli.py` | V2 sidecars, frozen metrics, explicit commands |
| `sentinel/url_ml/provenance.py` | Stdlib legacy/v2 provenance validation |
| `sentinel/url_ml/training.py`, `artifacts.py` | Backward-compatible factory hook/schema dispatch |
| `configs/url-ml-v2.json`, two data requirements files | Exact protocol and separate acquisition lock |
| `tests/url_v2_fixtures.py`, `tests/test_url_v2_*.py` | Synthetic boundary/isolation/regression fixtures |
| `docs/url-v2-workflow.md`, existing source audit | Reproduction, attribution and measured access status |
| `output/research/url-ml-v2/` | Inspected aggregate reports/card/delivery record |

Modify `.gitignore`, README/next steps and existing URL tests only in their owning tasks. No web app, extension, intake, case database or default launcher changes.

PowerShell test commands run from the execution checkout. `.venv-url-data\Scripts\python.exe` runs Arrow/acquisition tests; `.venv-ml\Scripts\python.exe` runs model tests. Create these checkout-local runtimes during execution using the known base CPython 3.11 executable in the existing reproduction guide; do not assume `python` on PATH. Scoped red/green checks precede each commit.

## Shared contracts

Frozen stdlib dataclasses in `contracts.py`; reuse v1 `DatasetError`, `UrlRow`, `DatasetBundle`, `SplitBundle`, `RunBundle`, `UrlParser`:

- `SourceFile(source_id: str, revision: str, path: str, original_partition: str, size: int, expected_sha256: str | None, object_id: str | None)`; approved relative source/member path, never a row URL.
- `SourceCatalog(sources: tuple[dict, ...], files: tuple[SourceFile, ...], manifest: dict)`; digest is the immutable canonical JSON manifest hash, not a CSV hash.
- `Observation(observation_id: str, source_id: str, revision: str, original_partition: str, reference: dict, original_url: str, original_label: str, source_date: str | None, opaque_id: str | None)`; reference binds shard/row or original member/line. Source date semantics are in the catalog.
- `Record(row: UrlRow, observation_ids: tuple[str, ...], flags: tuple[str, ...])`; case ID is SHA-256 of canonical URL UTF-8 bytes. Keep excluded/duplicate observations privately.
- `AuditBundle(root: Path, manifest: dict)`; `iter_records(audit: AuditBundle) -> Iterator[Record]`, `iter_observations(audit: AuditBundle) -> Iterator[Observation]` stream JSONL.
- `V2Splits(development: SplitBundle, tracks: dict[str, tuple[UrlRow, ...]], component_by_case: dict[str, str], sources_by_case: dict[str, tuple[str, ...]], manifest: dict)`; tracks `primary`, `external` have explicit status even when empty.
- `ResearchRun(run: RunBundle, format_model: object, format_report: dict, protocol: dict)`; diagnostic format model is ineligible for deployed candidate choice.
- Schemas: `url-ml-config-v2`, `url-source-catalog-v2`, `url-projection-v2`, `url-dataset-v2`, `url-protocol-v2`, `url-provenance-v2`, `url-artifact-v2`, `url-final-evaluation-v2`.

V2 provenance fields: `provenance_schema`, `source_catalog_sha256`, `dataset_manifest_sha256`, `derived_sha256`, `psl_sha256`, `parser_code_sha256`, `protocol_sha256`; fitted runs add `split_manifest_sha256`, config/calibration-ID hashes. Never populate `source_sha256` with a catalog digest. Individual file hashes remain in the catalog. Legacy artifacts without an explicit provenance schema retain their existing fields/exact file set.

Config top-level keys are `schema`, `sources`, `parser`, `projection`, `split`, `support`, `training`. `training` copies the existing model-config fields/grid with added sensitivity budgets `[0.05, 0.01]`; wrappers pass only the validated training block to v1 functions. Source entries name `source_id`, `revision`, `label_map`, `date_semantics` (`meaning`, `evidence_ref`, `timezone`, `authenticated`). Unverified date semantics default to `authenticated=False`, never an inferred timezone. `sources_by_case` describes only retained owning observations in that track; complete raw provenance remains in the audit.

The protocol manifest excludes its own hash. Its canonical hash becomes `protocol_sha256` in the separate development envelope (`url-development-envelope-v2`); `split_manifest_sha256` hashes that envelope. `derived_sha256` hashes audited `rows.jsonl` bytes. Run config hash is `training_config_sha256`; loaders verify it against frozen `training_config`. This prevents self-referential hashes and accidental substitution of digest meanings.

Fixture helpers live in `tests/url_v2_fixtures.py`: `synthetic_observation(**overrides) -> Observation`, `synthetic_catalog(root: Path) -> SourceCatalog`, `synthetic_audit(root: Path, parser: UrlParser) -> AuditBundle`, `write_parquet_fixture(path: Path) -> dict`. The last imports Arrow lazily and returns its original rows/column spans for request assertions. Model fixtures supply enough invented components to exercise support gates; smaller isolation fixtures test the allocator separately without weakening production CLI minima.

### Task 1: Records, config and isolated data environment

**Files:** Create package marker, `contracts.py`, `storage.py`, config, `requirements-url-data.in`, `requirements-url-data-win-py311.lock.txt`, fixtures and `tests/test_url_v2_contracts.py`; modify `.gitignore`.

**Interfaces:** Shared records; `load_config(path: Path) -> dict`, `manifest_hash(value: dict) -> str`, `publish_jsonl_directory(output_dir: Path, files: dict[str, Iterable[dict]], manifest: dict) -> dict`, `save_failure(root: Path, stage: str, diagnostics: dict) -> Path`. Exclusive/atomic publication; exclusive failures outside immutable outputs.

- [x] Prepare the execution checkout's `.venv-ml` using the unchanged existing lock before its first test. Base interpreter: `C:\Users\Jason Dsouza\AppData\Roaming\uv\python\cpython-3.11.17-windows-x86_64-none\python.exe`; verify Python 3.11 first. If this checkout already has a verified matching environment, reuse it. Otherwise run:

```powershell
$sentinelPython311 = 'C:\Users\Jason Dsouza\AppData\Roaming\uv\python\cpython-3.11.17-windows-x86_64-none\python.exe'
& $sentinelPython311 -m venv .venv-ml
.venv-ml\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-ml-win-py311.lock.txt
```

- [x] Write `test_v2_contract_bounds_and_immutable_failure`, with separate schema rejection, immutable publication and stdlib import cases:

```python
def test_v2_contract_bounds_and_immutable_failure(self):
    self.assertEqual(config['projection']['batch_rows'], 4096)
    self.assertEqual(config['projection']['max_response_bytes'], 2147483648)
    self.assertEqual(config['split']['fractions'], {'train': .8, 'validation': .1, 'calibration': .1})
    self.assertEqual(config['split']['development_max_rows'], 200000)
    self.assertNotIn('source_sha256', v2_provenance)
    self.assertNotEqual(first_failure_path, second_failure_path)
    self.assertNotIn('pyarrow', child_imported_modules)
```

- [x] Run `.venv-ml\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_contracts.py -v`; expect new-interface assertions/imports to fail, not a missing interpreter.
- [x] Implement records/config/storage with exact spec limits/current grids; reject unknown keys, Boolean numeric values, nonfinite values, bad relative paths/revisions/checksums/label maps. Acquisition UTC timestamps are metadata, not row dates. Atomic publication errors preserve diagnostics; fixtures are invented and excluded from research evidence.
- [x] Create `.venv-url-data` with CPython 3.11. Select an official PyArrow release with a Windows x64 CPython 3.11 binary wheel and required reader options; record wheel name/hash and exact direct pin. Pin `idna==3.20`, `tldextract==5.4.0`, constrain overlapping transitive packages to the ML lock, install binary wheels only, freeze a separate data lock. Smoke-check imports/options in a fresh data runtime. Stop with compatibility diagnostics if resolution fails; do not retarget Python/change the ML lock. Ignore `.venv-url-data/`, `.venv-url-v2-check/`, `data/url-ml-v2/` and existing binary model paths.
- [x] Run contract tests and clean `-S` package/server import checks; expect PASS/no optional imports. Verify existing ML-lock byte hash unchanged and private paths recognized by `git check-ignore`.
- [x] Commit scoped files: `feat(url-v2): define research contracts and isolated data runtime`.

### Task 2: Pinned catalog and bounded range transport

**Files:** Create `catalog.py`, `ranges.py`, `tests/test_url_v2_ranges.py`, `tests/test_url_v2_catalog.py`; extend range fixtures/storage journals.

**Interfaces:** `fetch_phresh_catalog(output_dir: Path, config: dict) -> SourceCatalog`; `load_catalog(root: Path) -> SourceCatalog`; `RangeSession(catalog: SourceCatalog, cache_dir: Path, config: dict)`; `RangeSession.read_range(file: SourceFile, start: int, length: int) -> bytes`; `RangeSession.snapshot() -> dict`. Session binds revision, inventory/config hashes and cumulative received bytes. Charge catalog metadata payload receipts once when starting a projection journal; resume retains that charge. Pilot and full projection have separate declared run purposes/journals.

- [x] Write fake-transport tests for valid 206; 200/compressed/wrong Content-Range; wrong size/weak or changed identity; HTTPS/userinfo/port/redirect rejection; interrupted bodies/expired signed locations; corrupt cache; traversal/unknown files. Assert:

```python
def test_resume_budget_cache_and_signed_redirect_redaction(self):
    self.assertEqual(session.snapshot()['response_bytes'], failed_body_bytes + successful_body_bytes)
    self.assertLessEqual(attempt_count, 4)  # Initial attempt plus at most three retries.
    self.assertEqual(resumed_session.snapshot()['response_bytes'], previous_bytes)
    self.assertNotIn('signature=SECRET', serialized_diagnostics)
    self.assertEqual(cached_range_bytes, newly_verified_bytes)
    self.assertFalse(completed_manifest.exists())
```

- [x] Run `.venv-url-data\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_ranges.py -v` and `.venv-url-data\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_catalog.py -v`; expect missing transport/catalog behavior to fail.
- [x] Implement pinned dataset-revision API inventory and pinned card acquisition; validate returned revision; allow only `data/(train|test)-NNN.parquet` members. Bound JSON at 2 MiB/card at 256 KiB; account their payload bytes. Record sizes/object identifiers/expected full-file hashes when supplied. Reject undeclared Parquet members, malformed sizes and absent train/test inventory. Fixed metadata requests may return 200; shard ranges require 206. Persist logical pinned paths/approved response host, never signed query strings.
- [x] Implement half-open `[start,start+length)` range validation, identity encoding, exact requested length/Content-Range/size and a strong ETag bound to the pinned object; fail if identity cannot be established. Retry only transient transport/timeout/5xx failures at most three times with bounded backoff; protocol/identity errors are terminal. Close rejected responses promptly and account every payload byte actually read, including partial attempts. Persist budget/journal on failure/resume; verify cache checksums before reuse and reject cross-identity/config/partial entries.
- [x] Repeat both exact module commands above; expect PASS/no live requests/full-body fallback. A resumed run cannot bypass its 2 GiB cap by starting another process.
- [x] Commit: `feat(url-v2): add pinned catalog and bounded range acquisition`.

### Task 3: Parquet footer planning and metadata projection

**Files:** Create `projection.py`, `tests/test_url_v2_projection.py`; add lazy Arrow fixture writer.

**Interfaces:** `plan_projection(file: SourceFile, session: RangeSession, config: dict) -> dict`; `project_phresh(catalog: SourceCatalog, session: RangeSession, output_dir: Path, config: dict, *, pilot: bool = False) -> dict`; `iter_phresh_observations(projection_root: Path, catalog: SourceCatalog) -> Iterator[Observation]`. Pilot has its own status/purpose; never a complete-corpus manifest.

- [x] Write a tiny real local Parquet fixture with multiple row groups, four selected fields, distinct HTML/lang columns. Spy on every range and compare projected values against four local columns. Test bad magic/footer length, missing/nested fields, external `file_path`, impossible/overlapping offsets, encryption, oversized footer/chunk and truncated data. Assert no requested span intersects any excluded column, batches are at most `4096`, and `full_file_checksum_verified is False` even when an expected full-object hash exists.

```python
def test_projected_columns_never_request_html(self):
    self.assertEqual(projected_columns, ['url', 'label', 'date', 'sha256'])
    self.assertFalse(any(intersects_excluded(span) for span in requested_ranges))
    self.assertLessEqual(max(batch_lengths), 4096)
    self.assertIs(manifest['full_file_checksum_verified'], False)
```

- [x] Run `.venv-url-data\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_projection.py -v`; expect missing projection behavior to fail.
- [x] Read exact header, last eight bytes and footer. Parse an **in-memory metadata-only envelope** (`PAR1 + verified footer + footer length + PAR1`) with bounded `ParquetFile` metadata parsing; prevent Arrow's normal large footer window from fetching data columns. Pass that parsed metadata to the original-object reader. For every row-group/column use the earliest dictionary/data offset plus compressed size; reject external files, negative/out-of-file offsets, selected/excluded overlaps, encryption, missing/nested projected fields. Thrift string/container limits `2097152` bytes/`100000` entries; disable Arrow extension decoding/code.
- [x] Implement a seekable permitted-range view: verified header/footer spans first, then audited selected spans. Refuse all other reads; cache one bounded column range at a time without joining gaps. Use `ParquetFile(..., metadata=metadata, pre_buffer=False, buffer_size=0)`, `columns=['url','label','date','sha256']`, `batch_size=4096`, `use_threads=False`, `use_pandas_metadata=False`. Keep shard/1-based row ordinal. Record nullable string/date/timestamp scalar representation; non-scalar projected schemas fail and dates are never invented.
- [x] Project shards sequentially into private JSONL; publish only when every inventory shard verifies/decodes. Abort preserves cache/errors. Pilot first sorted train/test shard, explicitly as a transport/schema pilot; full projection still requires every shard. Incompatible Arrow access or limits stop with attempted spans/diagnostics; never widen HTML access or report partial data as complete.
- [x] Run tests; expect PASS/zero excluded-column requests. Crash/resume yields identical projected content hashes and no complete manifest for a partial run.
- [x] Commit: `feat(url-v2): project URL metadata without fetching HTML`.

Metadata, projection and buffering interfaces are documented in [Apache Arrow's ParquetFile reference](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetFile.html). The restricted envelope/transport is Sentinel's design: real Arrow fixtures must prove it works; the documentation alone does not.

### Task 4: Official local ISCX admission adapter

**Files:** Create `iscx.py`, `tests/test_url_v2_iscx.py`; extend catalog loading for local sources.

**Interfaces:** `admit_iscx(mapping_path: Path, output_dir: Path) -> SourceCatalog`; `iter_iscx_observations(catalog: SourceCatalog, admitted_root: Path) -> Iterator[Observation]`; `merge_catalogs(primary: SourceCatalog, external: SourceCatalog | None) -> SourceCatalog` in `catalog.py` validates both immutable catalogs and combines source-scoped file entries in sorted order, retaining child manifest hashes. Mapping schema `iscx-local-mapping-v1`: official URL, acquisition basis/date, original archive/member identity, local path/SHA-256, documented category and explicit `csv` (URL column/header/encoding) or `lines` format.

- [x] Write tests for absent files/mapping/evidence, swapped hash, renamed member without original identity, CSV wrong header, explicit line format, unsupported schema/category, unsafe member path and positive-only inputs. Assert `benign -> 0`, `phishing -> 1`, spam/malware/defacement excluded/countable and acquisition date never becomes a row date. Patch network calls to fail if invoked.

```python
def test_local_mapping_preserves_identity_without_inventing_dates(self):
    self.assertEqual(label_map, {'benign': 0, 'phishing': 1})
    self.assertIsNone(observation.source_date)
    self.assertEqual(network_call_count, 0)
    self.assertEqual(observation.reference['member'], original_member)
```

- [x] Run `.venv-url-data\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_iscx.py -v`; expect missing adapter behavior to fail.
- [x] Require documented category-to-original-member mapping and exact hashes; copy verified local members into exclusive private storage and stream the explicitly declared encoding/format. Record original line/member references and absent authentic dates. Do not extract arbitrary archives, infer schemas/labels from names or certify mapping evidence as externally verified. Unsupported/unaudited inputs stay unavailable. Positive-only data can be audited; Task 6 determines whether it is an evaluable binary holdout.
- [x] Run tests; expect PASS/zero network requests. Without official audited files, acquisition status remains pending.
- [x] Commit: `feat(url-v2): admit explicitly mapped local ISCX records`.

### Task 5: Streaming canonical audit with complete provenance

**Files:** Create `audit.py`, `tests/test_url_v2_audit.py`; extend storage/source fixtures.

**Interfaces:** `audit_sources(catalog: SourceCatalog, observations: Iterable[Observation], parser: UrlParser, output_dir: Path) -> AuditBundle`; `load_audit(root: Path, catalog: SourceCatalog, parser: UrlParser) -> AuditBundle`; shared streaming functions; `format_flags(url: str) -> tuple[str, ...]` for `https`, `www_host`, `non_root_path`, `query_present` using URL structure.

- [x] Test exact/normalized cross-source duplicates, conflicting labels in reversed input order, stable IDs, source-scoped opaque IDs, bad/missing/oversized fields, malformed/unknown dates and preserved path/query. Assert all conflict observations excluded, all nonconflicting duplicate observation IDs retained, input counts reconciled and both source label maps identical. V1 `load_dataset` must reject v2 manifests.

```python
def test_all_conflicting_observations_excluded_and_duplicates_retained(self):
    self.assertNotIn(conflicting_url, canonical_urls)
    self.assertEqual(excluded_conflict_ids, all_conflict_ids)
    self.assertEqual(retained_record.observation_ids, expected_duplicate_ids)
    self.assertEqual(reconciled_observation_count, input_observation_count)
```

- [x] Run `.venv-url-data\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_audit.py -v`; expect missing audit behavior to fail.
- [x] Use private indexed SQLite staging to avoid retaining every raw observation in RAM. Observation IDs bind source/revision/shard/member/ordinal. Reuse `UrlParser.normalize`; retain original fields/parser flags/distinct exclusion codes. Publish canonical rows/provenance/exclusions with hashes and input/source/class/format counts. Keep all accepted references per canonical row; conflicts produce no model row. Exclude scheme-less URLs without repair.
- [x] Parse supported ISO date/datetime representations, preserving originals/semantics. Missing stays missing; invalid representation is `malformed_source_date`; valid naive/date-only values without documented timezone/meaning remain chronology-unknown. Authenticated date-only chronology uses a conservative full-day interval, never midnight assumption. Parsing alone cannot authenticate collection-date meaning. Record unknown suffix limitations and actual parser code/PSL hashes.
- [x] Run tests; expect PASS. Loader rechecks catalog/files, canonical URL/domain/label/ID mapping and totals; tampered bytes or missing provenance fail before data reuse.
- [x] Commit: `feat(url-v2): audit canonical URLs and retain source observations`.

### Task 6: Frozen component protocol and availability gates

**Files:** Create `protocol.py`, `tests/test_url_v2_protocol.py`; private assignments/component/owner-observation sidecars.

**Interfaces:** `freeze_protocol(audit: AuditBundle, catalog: SourceCatalog, config: dict, output_dir: Path) -> V2Splits`; `load_protocol(audit: AuditBundle, catalog: SourceCatalog, root: Path, config: dict) -> V2Splits`; `assert_training_ready(splits: V2Splits) -> None`. Manifest binds components/assignments/exclusions/catalog/parser/config/file hashes, support/formats and per-track status/reasons.

- [x] Test domain/equivalent URL overlaps; one opaque ID linking different domains; equal IDs from different sources remaining distinct; external priority; component exceeding `200000`; reordered-input determinism; tampered assignments; missing rows/classes/groups/formats; missing/ambiguous/equal/interleaved dates; positive-only external data:

```python
def test_frozen_component_ownership_and_unavailable_tracks(self):
    self.assertEqual(parts_for_component, {'primary'})  # Published test ownership wins.
    self.assertEqual(set(splits.development.partitions), {'train', 'validation', 'calibration'})
    self.assertFalse(development_components & primary_components)
    self.assertFalse(external_components & (primary_components | development_components))
    self.assertLessEqual(development_rows, 200000)
    self.assertEqual(missing_external['status'], 'unavailable')
    self.assertEqual(ambiguous_dates['temporal']['status'], 'unavailable')
    self.assertEqual(first_assignment_bytes, reordered_assignment_bytes)
```

- [x] Run `.venv-url-data\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_protocol.py -v`; expect missing protocol behavior to fail.
- [x] Connect canonical domain/IP and same-source opaque IDs; equivalent URLs already canonicalized. Component ID hashes sorted canonical case IDs. Priority **primary reserved test > development > external**. Any component with published primary-test observations loses its development observations; retain published test rows. External rows connected to primary or eligible development are excluded externally. Keep observation-level ownership/pruning audits; duplicate provenance never produces copies across tracks. Holdout labels never select a fitted model.
- [x] Sort eligible training component IDs, shuffle with `Random(42)`, retain each whole component only if it fits the cap; record all skips. Allocate retained components at `80/10/10` with the current split algorithm's class-count squared-deviation objective, descending size/seeded ties; fixed tie order train/validation/calibration. Store observed ratios; neither cap nor allocation cuts a component or falls back to random rows.
- [x] Freeze owner-observation IDs and derive source/date summaries from those owners. Check every specified support/format minimum before training. Temporal complete requires authenticated semantics and max development date-interval end strictly before min retained primary-test interval start; no download/filename/model-inferred dates. Missing external source permits primary research but leaves external robustness incomplete; failed development/primary gates block fitting. Failed chronology allows group/source evaluation with an unavailable temporal claim.
- [x] Reload/revalidate hashes and every isolation link; reject config/parser/catalog mismatch, duplicate/incomplete assignments. Run tests; expect PASS, including giant-component infeasibility without relaxing grouping.
- [x] Commit: `feat(url-v2): freeze isolated development and robustness tracks`.

### Task 7: Compatible learned training and format diagnostic

**Files:** Create `compat.py`, `format_baseline.py`, `training.py`, `sentinel/url_ml/provenance.py`, `tests/test_url_v2_training.py`; modify optional factory hook in `sentinel/url_ml/training.py`; extend old training regressions.

**Interfaces:** `development_bundle(splits: V2Splits) -> SplitBundle`; `validate_provenance(value: dict, *, stage: str) -> None` (`development` or `artifact`); `train_v2(splits: V2Splits, config: dict, parser: UrlParser) -> ResearchRun`; `pilot_v2(splits: V2Splits, config: dict, parser: UrlParser) -> dict`; `build_format_pipeline(branch: str, params: dict, parser: UrlParser) -> object`. Extend `fit_candidate(rows: tuple[UrlRow, ...], branch: str, params: dict, parser: UrlParser, native_threads: int = 4, max_peak_bytes: int = 8589934592, *, pipeline_factory: Callable | None = None) -> tuple[object | None, dict]` preserving positional/default behavior; supplied factory is top-level/picklable for the spawned worker.

- [x] Spy learners/calibrators prove fit sees train only, selection validation only, calibration its partition only, never final tracks. Test both sensitivity thresholds from frozen validation scores:

```python
def test_training_boundaries_and_validation_operating_points(self):
    self.assertEqual(selected_branch_set, {'char_tfidf', 'lexical_hgb'})
    self.assertEqual(set(sensitivity_thresholds), {'0.05', '0.01'})
    self.assertNotIn('source_sha256', run.provenance)
    self.assertEqual(format_feature_names, ['https', 'www_host', 'non_root_path', 'query_present'])
    self.assertFalse(pilot_component_was_cut)
    self.assertEqual(fit_record['native_threads'], 4)
    self.assertLessEqual(fit_record['max_peak_bytes'], 8589934592)
```

- [x] Run `.venv-ml\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_training.py -v`; expect missing training/provenance behavior to fail.
- [x] Validate development-only envelope before fitting. Reuse `train_run`, selection/rules/calibration/grids without final rows or source/date features. Preserve recall/precision/configuration-index tie policy at 5%. For selected/per-branch frozen candidates compute extra 1% validation thresholds in the selection report, without another model search/test calibration.
- [x] Define `FormatTransformer(parser: UrlParser)` in `format_baseline.py`, with `fit(X: list[str], y: object = None) -> FormatTransformer`, `transform(X: list[str]) -> numpy.ndarray`, `get_feature_names_out(input_features: object = None) -> numpy.ndarray`; fixed four-column Boolean matrix, no source metadata. Diagnostic worker branch is `format_only`, excluded from deployment branches. Four-feature pipeline: `CanonicalTransformer -> FormatTransformer -> LogisticRegression(C=1, class_weight=None, solver='liblinear', max_iter=1000, random_state=42)`. Fit once on train through the same fresh-process resource worker with explicit factory; choose both validation thresholds. Exclude from candidate grid/deployable branches/numerical calibration; retain resources and validation diagnostics.
- [x] Select whole components for resource pilot capped at `2000`, require both labels, and pass only that preselected subset to existing pilot code. Preserve failed fit parameters/sanitized underlying error/available RAM/time in `DatasetError.diagnostics`. Legacy calls and failure behavior remain unchanged.
- [x] Run new tests and `.venv-ml\Scripts\python.exe -m unittest discover -s tests -p test_url_ml_training.py -v` plus the same command with patterns `test_url_ml_failure_reports.py` and `test_url_ml_calibration.py`; expect PASS, including tied scores/unavailable calibration and legacy workers.
- [x] Commit: `feat(url-v2): reuse bounded training with explicit provenance and format controls`.

### Task 8: Immutable v2 artifacts with v1 compatibility

**Files:** Create `sentinel/url_v2/artifacts.py`, `tests/test_url_v2_artifacts.py`; modify common `sentinel/url_ml/artifacts.py`; extend provenance validators/old artifact tests.

**Interfaces:** `export_v2_artifact(research: ResearchRun, parser: UrlParser, output_dir: Path, version: str) -> dict`; `load_v2_artifact(path: Path) -> ResearchRun`. Common `export_artifact(run: RunBundle, parser: UrlParser, output_dir: Path, version: str, *, research_payload: dict | None = None) -> dict` gains an optional payload containing `format_model`, `format_report`, `protocol`; v1 omits it. Common `load_artifact(path: Path) -> RunBundle` keeps its return type.

- [x] Test round-trip/equal scores for both versions, wrong schema/catalog/protocol/config/PSL, missing/tampered diagnostics, unsafe paths/thresholds/dependencies and overwrite. Patch `joblib.load`: no deserialization before all file/schema/dependency/provenance checks. Verify legacy prediction CLI with spaces in paths.

```python
def test_tampered_v2_sidecar_rejected_before_any_deserialization(self):
    with patch('joblib.load') as loader:
        with self.assertRaises(DatasetError):
            load_v2_artifact(tampered_artifact)
        loader.assert_not_called()
```

- [x] Run `.venv-ml\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_artifacts.py -v`; expect missing v2 behavior to fail.
- [x] Dispatch by explicit artifact/provenance schema. V1 retains exact file set/meanings. V2 adds `protocol.json`, `diagnostic.json`, `diagnostic.joblib` to existing files, binding source/protocol/parser hashes and both sensitivity thresholds. Preserve selected/learned-baselines joblib payload shape; diagnostic pickle is locally generated only. Validate every file including diagnostics before selected-pipeline load; generic inference need not deserialize diagnostics/import PyArrow. V2 research loader checks diagnostic four-feature pipeline/labels after shared validation.
- [x] Check frozen protocol/config/catalog before export; inference never substitutes current config for artifact provenance. Preserve exclusive publication, runtime/dependency checks, bundled PSL rebinding/unavailable calibration. Research card names incomplete tracks; final metrics stay outside immutable artifact. No default selector/launcher changes.
- [x] Run the same discover command with patterns `test_url_v2_artifacts.py`, `test_url_ml_artifacts.py`, `test_url_ml_integration.py`, `test_url_ml_service.py`; expect PASS/identical legacy reload scores. Diagnostic models cannot become the selected service branch.
- [x] Commit: `feat(url-v2): persist research artifacts without changing v1 contracts`.

### Task 9: Frozen robustness metrics and valid v1 comparison

**Files:** Create `evaluation.py`, `tests/test_url_v2_evaluation.py`; reuse metrics/calibration, preserve old reports.

**Interfaces:** `evaluate_robustness(research: ResearchRun, splits: V2Splits, artifact_path: Path, *, v1_run: RunBundle | None = None, v1_data: tuple[DatasetBundle, SplitBundle] | None = None) -> dict`; `render_card(report: dict) -> str`; `publish_evaluation(report: dict, output_dir: Path) -> dict`. Exclusive output directory contains aggregate `evaluation.json`, `model-card.md`; private row scores/errors remain under v2 data root.

- [x] Test known scores for per-track confusion/FPR/AP, both operating points, absent/positive-only tracks, tiny subgroups, constant bootstrap, source/format breakdown and v1 overlap pruning. Evaluation must never call fit/threshold choice; all compared models score identical IDs; changed frozen bytes fail before prediction:

```python
def test_missing_tracks_and_paired_component_metrics(self):
    self.assertEqual(report['tracks']['external']['status'], 'unavailable')
    self.assertIsNone(report['tracks']['external']['metrics'])
    self.assertEqual(report['bootstrap']['unit'], 'domain_connected_component')
    self.assertIn('constant_bootstrap_outcomes', constant_outcome_limitations)
    self.assertFalse(paired_components & v1_development_components)
    self.assertEqual(v1_paired_ids, v2_paired_ids)
```

- [x] Run `.venv-ml\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_evaluation.py -v`; expect missing metrics behavior to fail.
- [x] Validate artifact/protocol/catalog/config/assignment hashes; score each available primary/external track once for two frozen learned branches, fixed rules and format diagnostic. Use frozen raw thresholds; only selected model has supported calibrated probabilities. Report metrics/confusion/class/format/source/group coverage, Brier/ECE/reliability and conditional precision scenarios at prevalence `.001`, `.01`, `.05`, `.1`. Unavailable tracks have reasons/null metrics; temporal status qualifies primary results, not an invented independent test.
- [x] Bootstrap whole connected components containing entire domains, `1000` replicates/seed `42`; record valid counts and flag constant distributions. Display subgroup class/component support and null undefined metrics; below `100` rows/`30` components per class is exploratory, with no precise-accuracy claim. Aggregate error categories only. Measure cold load/first URL and `100` warm URLs in deterministic ID order, median/p95, measured fit peak RAM and independence/chronology limitations.
- [x] With both verified v1 artifact and dataset/splits, report full-track transfer with overlaps against **all** earlier v1 data. Paired comparisons score the same v2 test rows with both models, dropping every v2 component containing a v1 train/validation/calibration domain; inadequate final support means unavailable. Use identical bootstrap samples for paired metric differences. Historical different-population headline scores cannot estimate improvement. Check v1 artifact matches supplied dataset/splits.
- [x] Publish atomically/exclusively; repeated final evaluation refuses overwrite. Public output has no URL/token/local absolute path/row identifier. Run the same discover command with patterns `test_url_v2_evaluation.py` and `test_url_ml_metrics.py`; expect PASS with honest negative/incomplete results, never a required score increase.
- [x] Commit: `feat(url-v2): report frozen source and temporal robustness`.

### Task 10: Explicit CLI, reproduction and app compatibility

**Files:** Create `cli.py`, `docs/url-v2-workflow.md`, `tests/test_url_v2_cli.py`, `tests/test_url_v2_compatibility.py`; update README/next steps/source audit for actual evidence only.

**Interfaces:** `main(argv: list[str] | None = None) -> int`. Require `--root` except for `predict`; `--config` defaults to `configs/url-ml-v2.json`. Commands:

| Command | Required options/result |
| --- | --- |
| `catalog` | Pinned inventory/card in `sources/phreshphish/catalog/` |
| `project-pilot` | Private schema/range pilot, never complete corpus |
| `project` | Full metadata projection; `--resume` verifies cache only |
| `admit-iscx` | `--mapping PATH`; explicit audited local members |
| `audit` | `--psl PATH`; frozen PSL/observation merge |
| `freeze` | Immutable audited protocol/assignments |
| `pilot` | Development-only whole-component CPU pilot |
| `train` | `--artifact PATH --version NAME`; immutable candidate |
| `evaluate` | `--artifact PATH --out DIR`; optional `--v1-root PATH --v1-artifact PATH` together |
| `predict` | `--artifact PATH --url TEXT`; existing service, no acquisition |

Private layout: `sources/`, `cache/`, `audited/`, `protocol/`, `runs/`, `failed-runs/`. Success prints sanitized aggregate status/hashes. Failure returns `2` with an exclusive private diagnostic path; persistence failure returns sanitized diagnostic inline. Missing dependencies/external source/chronology are explicit; server startup never installs/acquires them.

- [x] Subprocess tests: help, spaces in paths, wrong runtime/dependency, failed projection/all-fits with context, immutable repeats, missing external report, old CLI. Test default `python -S` server without optional libraries and separately an explicitly configured locally generated v2 artifact. Assert original default keys/case ownership, research checks save no cases, default imports neither PyArrow nor ML.

```python
def test_default_stdlib_server_keeps_original_contract(self):
    self.assertEqual(child.returncode, 0, child.stderr)
    self.assertNotIn('pyarrow', imported_modules)
    self.assertNotIn('sklearn', imported_modules)
    self.assertEqual(default_keys, {'fraud', 'harmful_content', 'profile'})
    self.assertEqual(saved_cases, [])
```

- [x] Run `.venv-url-data\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_cli.py -v` and `.venv-ml\Scripts\python.exe -m unittest discover -s tests -p test_url_v2_compatibility.py -v`; expect missing commands to fail.
- [x] Lazy stage dispatch validates config/provenance first. Read explicitly supplied preserved PSL; never refetch. Document exact data/ML commands, runtime handoff, attribution, pending official ISCX mapping, cap/schema protocol amendment and prohibition on final-test tuning. Research prediction may use an explicitly chosen artifact without changing the default launcher or enabling learned user warnings.
- [x] Repeat those commands, run `.venv-ml\Scripts\python.exe -m unittest discover -s tests -p test_url_ml_integration.py -v` and `node --test tests/web_client.test.mjs` (use the bundled Node absolute executable if absent from PATH); expect PASS. Inspect sanitized output for private queries; research outputs/case DB stay separate.
- [x] Commit: `feat(url-v2): expose the reproducible research workflow`.

### Task 11: Execute frozen research and complete independent review

**Files:** Ignored v2 data/artifacts; inspected `output/research/url-ml-v2/` aggregates/delivery record; workflow/source audit/next steps with actual evidence. No invented data or external-pass placeholders.

**Interfaces:** Consume declared config/commands; deliver measured results or reproducible incomplete tracks/failure reports, verified regressions and every final code-review disposition.

- [x] Build fresh `.venv-url-v2-check` from the union of both locks; reject overlapping pin conflicts. Run `.venv-url-v2-check\Scripts\python.exe -m unittest discover -s tests -v`, Node web-client tests and stdlib-only server check. Require zero failures/no relevant Arrow/ML skips; record actual counts/versions/locks, not the prior suite's count.
- [x] Snapshot/hashes verify preserved primary v1 data/artifact/output and case/intake state. Run data-runtime `catalog`, `project-pilot` against pinned source; record actual footer layout, selected bytes, scalar schema, resources/date semantics. If bounds/layout cannot work, preserve diagnostics and amend protocol before acquisition/modelling. Never call the pilot a representative dataset or treat the earlier eight-byte probe as full feasibility proof.
- [x] If pilot passes, full `project --resume`; admit ISCX only when official files/verified mapping are available. Otherwise external stays unavailable while primary can proceed. Run `audit --psl` using preserved v1 PSL and `freeze`; inspect totals/conflicts/pruning/components/classes/formats/ownership/chronology before fitting. Use measured counts, not inconsistent card totals.
- [x] When gates pass, ML-runtime `pilot`, `train` once to a new `url-v2` version, `evaluate` once to exclusive private output. Supply verified old root/artifact for overlap/paired diagnostics. Stage failure delivers intact diagnostics/incomplete status; do not alter frozen protocol after scores. Further data/model revision requires a new version and independent final set.
- [x] Copy only inspected aggregates/card/protocol summaries into public research output. Check no raw URLs/tokens/absolute user paths/private IDs. List unavailable tracks; restrict accuracy claims to measured support. Verify new artifact/preserved v1 hashes and equal scores after reload without refitting. Learned application warnings remain disabled.
- [x] Request one independent final whole-branch review under preserved inline execution. Reviewer reads this plan/spec/source audit/code/tests/results and checks ranges/conflicts/provenance/isolation/v1 contracts/final-test boundaries. Apply receiving-code-review before fixes; record every finding, disposition and verification. No per-task fresh implementer/reviewer is requested.
- [ ] Rerun broad regressions only when review fixes/new changes justify it. Verify actual data paths/hashes before integration and preserve needed ignored data/environments before worktree cleanup. Use finishing workflow to integrate/push under existing repository authorization; verify remote HEAD/clean scoped status. Report completed software/evaluable tracks and remaining external/release work.
- [ ] Commit inspected aggregates/docs: `docs(url-v2): record measured robustness and review decisions`; never stage raw sources/caches/rows/cases/joblib.

Execution note (2026-10-09): development query gate failed (6/30). Conditional model-fit,
calibration, artifact export/reload and final-scoring steps are not applicable; their metrics
remain unavailable. All four independent-review findings were reproduced and fixed.
Integration/push and final task ledger verification follow; no gate or final data was changed.

## Spec coverage and self-review

| Requirement | Tasks |
| --- | --- |
| Separate runtimes/private paths/hardware limits | 1, 7, 10-11 |
| Pinned inventory/card/attribution/bounded transport | 2-3, 10-11 |
| HTML isolation/metadata/resume/partial checksums | 2-3 |
| Official local ISCX/missing or positive-only external | 4, 6, 9-11 |
| Original records/all provenance/conflicts/dates/parser | 5 |
| Whole components/ownership/cap/fractions/support/formats/freeze | 6 |
| Distinct digest semantics/legacy rejection/compatibility | 1, 5, 7-8 |
| Reused grids/calibration/format baseline/5% and 1% thresholds | 7 |
| Immutable trusted artifacts/no PyArrow serving/no activation | 8, 10 |
| Tracks/subgroups/chronology/uncertainty/resources/valid comparisons | 6, 9, 11 |
| Failure evidence/unavailable status/no synthetic or test tuning | 1-3, 7, 9-11 |
| Reproduction/preservation/final review/authorized push | 10-11 |

Self-review: names/types/schemas agree across task boundaries; each task ends with a testable deliverable and scoped commit; every Review Focus item has tests/owner. No guaranteed performance or assumed acquisition is promised. Source feasibility/date semantics/original external members are explicitly measured/admitted during execution with stop/unavailable outcomes, not treated as known facts.

## User review handoff

Please review the plan and confirm it captures the approved specification. Preserve the selected method: inline `superpowers:executing-plans`, then one independent final review. Written-plan approval is required before code, dependencies or acquisition; this planning turn is not implementation.
