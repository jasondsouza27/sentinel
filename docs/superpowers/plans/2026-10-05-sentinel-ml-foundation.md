# Sentinel ML Foundation and URL Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an audited URL dataset, two evaluated CPU classifiers, calibrated immutable artifacts and an opt-in inference adapter for Sentinel.

**Architecture:** Keep offline acquisition/training separate from serving in a focused `sentinel/url_ml/` package. Share URL normalisation, features and artifact metadata between training and inference; import optional dependencies only inside enabled ML paths. Preserve the existing paired Naive Bayes pipeline and dependency-free application.

**Tech Stack:** CPython 3.11, NumPy/SciPy, scikit-learn, joblib, idna, tldextract, psutil, stdlib argparse/CSV/JSON and unittest. No PyTorch, dashboard rewrite or public deployment in this subsystem.

**Spec:** [Approved ML foundation design](../specs/2026-10-05-sentinel-ml-foundation-design.md), with constraints from the [approved year-long design](../specs/2026-10-05-sentinel-year-long-design.md). Approved by the user on 2026-10-05; **this implementation plan awaits review and execution-method selection**.

## Global Constraints

- "Use a dedicated Python 3.11 environment with locked compatible NumPy/scikit-learn/feature-parser dependencies."
- "Run one training job at a time." The standard CPU run targets "at most 8 GiB RAM".
- "URLs above the 2,048-character cap are excluded from this model's training/benchmark and reported unsupported at inference, with exclusion counts."
- "No arbitrary submitted website, redirect, DNS endpoint or page source is fetched." Training/inference are offline after acquisition.
- "Sentinel's label is `1 = phishing_url`, `0 = legitimate_url`." PhiUSIIL conversion is `0 -> 1`, `1 -> 0`.
- TF-IDF starts with "character n-grams of lengths 3–5 and at most 50,000 sparse features"; never densify that matrix.
- Split targets are "70/10/10/10 by domain-group components"; every partition contains both classes or the run stops.
- Search uses "at most six configurations per learned branch on validation data" under the parent's "5% validation false-positive-rate budget".
- Calibrate only on the calibration partition; test evaluation follows a frozen selection. No model or threshold selection on test.
- Raw data/large artifacts stay outside Git; published reports contain no raw URL tokens or absolute user paths.
- Phase 0 stays runnable without ML packages. No changes to paired labels, candidate admission, extension permissions or SQLite ownership.

## Review Focus

1. Malformed authorities, ports, controls, Unicode and IPv6: reject unsupported input consistently without fetching or crashing (Task 1).
2. Equivalent URLs with conflicting source labels: exclude the whole conflict, not whichever row arrives last (Task 2).
3. Huge domains or class-sparse splits: report infeasibility rather than relax domain isolation (Task 3).
4. Tied scores, all-negative operating points and reversed calibration: report the limitation; never manufacture confidence (Task 5).
5. Corrupt/incompatible artifacts or missing dependencies/suffix resources: validate before deserialisation and return unavailable while Phase 0 still runs (Tasks 6–7).

## File map and shared contracts

New files, each with one responsibility:

| File | Responsibility |
| --- | --- |
| `sentinel/url_ml/__init__.py`, `contracts.py` | Lightweight package and stdlib records/errors; no ML imports |
| `urls.py` | Strict URL normalisation and offline suffix/domain grouping |
| `source.py` | Fixed-source acquisition and auditable PhiUSIIL conversion |
| `splits.py` | Frozen group-disjoint partition creation/loading |
| `features.py`, `training.py` | Shared features/model factories and bounded candidate fitting |
| `metrics.py`, `calibration.py` | Threshold selection, grouped reports and sigmoid calibration |
| `artifacts.py`, `service.py` | Immutable trusted artifact export/loading and assessment adapter |
| `cli.py` | Acquisition, audit, split, pilot, train, evaluate and predict commands |
| `configs/url-ml-v1.json` | Frozen experiment settings, grid and source/resource references |
| `requirements-ml.in`, `requirements-ml-win-py311.lock.txt` | Direct pins and resolved Windows/Python 3.11 environment |
| `tests/url_ml_fixtures.py`, `tests/test_url_ml_*.py` | Synthetic boundary/leakage fixtures and meaningful subsystem tests |
| `docs/url-ml-workflow.md`, `docs/url-ml-source-audit.md` | Reproduction, attribution, measured counts and limitations |

Modify `.gitignore`, `sentinel/analysis.py`, `sentinel/server.py`, `README.md` and `docs/next-steps.md` only where tasks specify. Local directories: `data/url-ml/` and `models/url-ml/`; publish inspected aggregate deliverables under `output/research/url-ml-v1/`.

Define these stdlib dataclasses in `contracts.py`; immutable tuples hold row collections:

- `ParsedUrl(model_url: str, host: str, domain_group: str, flags: tuple[str, ...])`.
- `UrlRow(case_id: str, original_url: str, url: str, label: int, domain_group: str, source_ref: str, source_date: str | None = None)`.
- `DatasetBundle(rows: tuple[UrlRow, ...], manifest: dict)`; `SplitBundle(partitions: dict[str, tuple[UrlRow, ...]], manifest: dict)`.
- `Selection(model: object, branch: str, raw_threshold: float | None, config: dict, report: dict)`.
- `Calibration(status: str, slope: float | None, intercept: float | None, threshold: float | None, report: dict)`; `RunBundle(selection: Selection, calibration: Calibration, provenance: dict)`.
- `UrlAssessment(state: str, decision: str | None, model_version: str | None, evidence: tuple[str, ...], uncertainty: tuple[str, ...], unavailable_checks: tuple[str, ...], recommended_action: str, probability: float | None = None)`. Its `to_dict() -> dict` omits `probability` when absent; no raw internal score is returned.
- `UnsupportedUrl(reason: str)` and `DatasetError(reason: str)` contain reason codes, never the submitted URL. `None` threshold means flag no cases, avoiding JSON infinity.

All command paths below are relative to the verified repository root `C:\Users\Jason Dsouza\Desktop\major project`. Implement in an isolated worktree at execution time using the worktree skill; source paths remain relative to that checkout. Run each task's red/green cycle before its scoped commit; do not run acquisition/training while merely reviewing this plan.

Manifest schemas are `url-dataset-v1`, `url-splits-v1` and `url-artifact-v1`; feature schema is `url-lexical-v1`. Config keys include `seed=42`, `split_fractions={train:0.7,validation:0.1,calibration:0.1,test:0.1}`, `max_url_chars=2048`, `max_fpr=0.05`, `native_threads=4`, `memory_budget_gib=8`, and the branch grids below. Acquisition paths are `raw/phiusiil.zip`, `raw/PhiUSIIL_Phishing_URL_Dataset.csv` and `resources/public_suffix_list.dat` beneath the supplied root. Dataset/split manifests carry `schema_version`, `dataset_sha256`, `psl_sha256`, relative `files` and aggregate `counts`; splits additionally carry `seed` and partition row-ID assignments. Artifact metadata binds these hashes to the exact config/dependency lock and model version.

### Task 1: Offline URL contract and reproducible environment

**Files:** Create `contracts.py`, `urls.py`, package marker, both requirements files, `tests/url_ml_fixtures.py`, `tests/test_url_ml_urls.py`; modify `.gitignore`.

**Interfaces:** `UrlParser(psl_path: Path)` exposes `psl_sha256: str` and `normalize(value: str) -> ParsedUrl`. Later tasks reuse this parser instance. Fixture helper `fixture_psl(directory: Path) -> Path` writes an attributed minimal synthetic suffix list including `com`, `org`, `de`, `co.uk` and private `github.io`.

- [x] Obtain a dedicated Python 3.11 runtime if missing; create `.venv-ml` with `py -3.11 -m venv .venv-ml`. This machine currently has only Python 3.13 registered; do not silently retarget the approved environment. Pin candidate Windows-wheel versions: NumPy 2.4.6, SciPy 1.17.1, scikit-learn 1.9.1, joblib 1.6.0, idna 3.20, tldextract 5.4.0, psutil 7.2.2. Install into this venv only, smoke-check imports/version, then record all resolved transitive pins in the lock file. If resolution fails, document a compatible pin correction before proceeding. Ignore `.venv-ml/`, `data/url-ml/`, `models/url-ml/`.

The NumPy/SciPy candidates have Python 3.11 Windows wheels in official release metadata; installation is still unverified. [NumPy](https://pypi.org/project/numpy/2.4.6/), [SciPy](https://pypi.org/project/scipy/1.17.1/), [scikit-learn](https://pypi.org/project/scikit-learn/1.9.1/)
- [x] Write failing parser tests, including exact 2,048/2,049-character boundaries, preserving `/A?Token=X`, IDNA equivalence, invalid ports/brackets/controls and network-denied execution. Fixtures must supply the local PSL path:

```python
def test_private_suffix_and_ipv6_groups(self):
    self.assertEqual(self.parser.normalize("https://a.github.io/A").domain_group, "domain:a.github.io")
    self.assertEqual(self.parser.normalize("http://[2001:db8::1]/").domain_group, "ip:2001:db8::1")
def test_invalid_port_is_unsupported(self):
    with self.assertRaises(UnsupportedUrl): self.parser.normalize("https://example.org:99999/a")
```

- [x] Run `.venv-ml\Scripts\python.exe -m unittest discover -s tests -p test_url_ml_urls.py -v`; expect failure for missing parser/behaviour.
- [x] Implement `UrlParser` and the records. Use explicit local `psl_path.as_uri()`, `fallback_to_snapshot=False`, private suffixes enabled and an isolated cache; never use the module-level auto-fetch extractor. Normalise scheme/host case, IDNA, trailing host dot and default ports; preserve user-info/path/query/fragment spelling. Reject embedded whitespace/controls, bad percent escapes, missing host and unsupported schemes. Unknown suffixes conservatively group by full normalised host and record `unknown_suffix`; localhost/private targets are parsed without requesting them. [tldextract local/private-suffix configuration](https://github.com/john-kurkowski/tldextract#how-to-use-a-custom-suffix-list)
- [x] Rerun the parser suite, expect all passing without network. ML tests import optional modules inside test setup and skip clearly outside the ML environment; the ML environment must have zero dependency skips. Commit this deliverable and its environment files.

### Task 2: Audited PhiUSIIL import

**Files:** Create `source.py`, `cli.py`, `configs/url-ml-v1.json`, `tests/test_url_ml_source.py`; extend fixtures; create source-audit documentation.

**Interfaces:** `fetch_sources(root: Path) -> dict`; `import_phiusiil(csv_path: Path, parser: UrlParser, output_dir: Path) -> DatasetBundle`; `load_dataset(output_dir: Path, parser: UrlParser) -> DatasetBundle`; `cli.main(argv: list[str] | None = None) -> int`.

- [ ] Write tests with tiny ZIP/CSV fixtures (including UTF-8 BOM), original labels `0`/`1`, ignored webpage columns, duplicate and conflicting equivalent URLs, invalid labels, malformed/oversized URLs, and overwrite refusal:

```python
def test_label_inversion_and_conflict_exclusion(self):
    self.assertEqual([r.label for r in self.bundle.rows], [1, 0])
    self.assertEqual(self.bundle.manifest["excluded"]["conflicting_label"], 2)
    self.assertNotIn("Token=secret", json.dumps(self.bundle.manifest))
```

- [ ] Run the source suite with the Task 1 discovery command pattern changed to `test_url_ml_source.py`; expect missing importer/behaviour failure.
- [ ] Implement fixed-source acquisition: UCI `https://archive.ics.uci.edu/static/public/967/phiusiil+phishing+url+dataset.zip` and official PSL `https://publicsuffix.org/list/public_suffix_list.dat`. Stream to temporary files; require HTTPS/approved source hosts, finite timeouts, 64 MiB download and 128 MiB ZIP-member limits. Read only `PhiUSIIL_Phishing_URL_Dataset.csv`, never extract arbitrary archive paths. Refuse existing different outputs. Log retrieval time, SHA-256 and source terms; no arbitrary URL fetch argument.
- [ ] Implement conversion with required `URL`/`label` columns and explicit label inversion. Deduplicate canonical URL/label pairs and exclude all equivalent-URL conflicts. Keep original URL/private exclusion references locally. `case_id` uses source/member hash plus one-based CSV record ordinal; manifest records counts, original/canonical labels, hashes and relative paths without raw values. Loading verifies hashes and parser version before accepting rows.
- [ ] Add `fetch`/`audit` CLI commands; rerun tests, then acquire and audit the actual source into ignored storage. Record actual counts/exclusions/licences, including differences from the advertised size. Do not add rows to paired intake. Commit code, tests, config and counts-only documentation.

### Task 3: Frozen group-disjoint splits

**Files:** Create `splits.py`, `tests/test_url_ml_splits.py`; extend `cli.py` and config.

**Interfaces:** `freeze_splits(dataset: DatasetBundle, output_dir: Path, seed: int = 42) -> SplitBundle`; `load_splits(dataset: DatasetBundle, output_dir: Path) -> SplitBundle`.

- [ ] Write reproducibility, no-overlap, tampering and infeasible-group tests:

```python
def test_group_isolation_and_infeasibility(self):
    self.assertEqual(self.first.manifest, self.repeated.manifest)
    self.assertTrue(all(not (a & b) for a, b in self.partition_group_pairs))
    with self.assertRaises(DatasetError): freeze_splits(self.single_domain, self.empty_output)
```

- [ ] Run `test_url_ml_splits.py`; expect missing split functionality failure.
- [ ] Implement deterministic seeded group allocation targeting row/class proportions 70/10/10/10, keeping whole domain/equivalent-URL groups. Persist row-ID assignments, source/derived/PSL hashes, counts and largest groups; require both labels in every partition. Refuse overwrite; loading rejects altered IDs/hashes or overlaps. If allocation fails, emit a diagnostic instead of falling back to random rows.
- [ ] Add `split` CLI command and freeze the real audited source. Rerun tests; inspect group sizes/class counts before modelling. Commit the implementation and aggregate split summary, not row assignments.

### Task 4: Shared features and bounded CPU baselines

**Files:** Create `features.py`, `training.py`, `tests/test_url_ml_features.py`, `tests/test_url_ml_training.py`; extend config and CLI `pilot`.

**Interfaces:** `lexical_features(parsed: ParsedUrl) -> dict[str, float]`; `build_pipeline(branch: str, params: dict, parser: UrlParser) -> object`; `fit_pipeline(rows: tuple[UrlRow, ...], branch: str, params: dict, parser: UrlParser) -> object`; `raw_scores(model: object, urls: list[str]) -> np.ndarray`; `resource_pilot(splits: SplitBundle, config: dict, parser: UrlParser) -> dict`.

- [ ] Write sparse-shape, train-only vocabulary, shared-transform and prediction-orientation tests:

```python
def test_train_only_sparse_features(self):
    self.assertTrue(scipy.sparse.issparse(self.transformed))
    self.assertLessEqual(self.transformed.shape[1], 50_000)
    self.assertNotIn("zzzzz", self.model.named_steps["tfidf"].vocabulary_)
    self.assertIn("Token", self.model.named_steps["tfidf"].vocabulary_)
```

- [ ] Run both new suites; expect missing feature/model functionality failure.
- [ ] Implement branch `char_tfidf`: a float32 character TF-IDF/logistic pipeline (`liblinear`, `max_iter=1000`), named steps `tfidf`/`classifier`, with `lowercase=False`, 3–5-grams and a 50,000-feature cap. Grid: `C=[0.1,1,10]`, `class_weight=[None,"balanced"]` (six configurations). Implement ordered lexical features: URL/host/path/query lengths; host-label/dot counts; digit/letter/punctuation ratios; hyphen/user-info/encoding counts; IP, punycode, unknown-suffix and HTTPS flags. No original dataset features enter a pipeline.
- [ ] Implement branch `lexical_hgb`: lexical HistGradientBoosting, named steps `lexical`/`classifier` (`max_iter=200`, `max_depth=[3,5]`, `learning_rate=[0.05,0.1]`, `early_stopping=False`, `random_state=42`; four configurations). `raw_scores` explicitly chooses class `1` probability for both branches. Preserve parser/suffix state; fix feature ordering. Phase 0 rule baseline calls existing `analyze` with URL only and no feed/model, mapping any URL warning to flag `1` for benchmarking.
- [ ] Implement the training-only pilot: fixed seed, whole selected training groups, target at most 2,000 rows, both labels required. Run candidate fits sequentially in fresh child processes to measure independent peak RAM/time; return only the fitted model and measurement record. Read Windows peak working-set memory via psutil's supported peak field; limit native threads to four. Record pilot IDs/hash locally and counts/config publicly. Rerun tests and pilot; if peak exceeds 8 GiB, adjust the declared feature budget before final selection and document it. Commit the independently usable model factories and pilot command.

### Task 5: Selection, calibration and grouped evaluation

**Files:** Create `metrics.py`, `calibration.py`, `tests/test_url_ml_metrics.py`, `tests/test_url_ml_calibration.py`; extend `training.py` and config.

**Interfaces:** `choose_threshold(labels: np.ndarray, scores: np.ndarray, max_fpr: float = 0.05) -> float | None`; `select_model(splits: SplitBundle, config: dict, parser: UrlParser) -> Selection`; `fit_calibration(labels: np.ndarray, scores: np.ndarray, raw_threshold: float | None) -> Calibration`; `apply_calibration(calibration: Calibration, scores: np.ndarray) -> np.ndarray | None`; `evaluate_frozen(run: RunBundle, rows: tuple[UrlRow, ...], seed: int = 42) -> dict`.

- [ ] Write known-confusion-count, tied-score, grouped-bootstrap, calibration-separation and reverse-slope tests. Fit instrumentation must show candidate fitting sees train IDs, selection sees validation IDs, calibration sees only calibration IDs; poison test inputs must not be read during selection.

```python
def test_ties_and_reverse_calibration(self):
    self.assertIsNone(choose_threshold(np.array([0,0,1]), np.array([.9,.9,.9])))
    self.assertEqual(self.reversed_calibration.status, "unavailable")
    self.assertIsNone(apply_calibration(self.reversed_calibration, np.array([.4])))
```

- [ ] Run metric/calibration suites; expect missing functionality or incorrect partition/threshold behaviour failure.
- [ ] Implement threshold enumeration over unique validation scores, plus the `None` all-negative point; classify with `score >= threshold`. Select maximal recall subject to FPR <=0.05, then precision, then deterministic config order. Record every configuration, resource measurement, convergence failure and validation result. Evaluate Phase 0 rules descriptively without pretending they meet the budget. Never retrain the chosen model on validation/calibration.
- [ ] Fit sigmoid calibration using clipped score logits (`epsilon=1e-6`) and the calibration partition; store coefficients, sample counts and mapped threshold. Require at least 100 calibration rows and 20 per class, finite coefficients and strictly positive slope; these are validity guards, not proof of reliability. Otherwise retain raw-threshold decisions and suppress probabilities. Decisions continue using the frozen raw threshold to avoid rounding changes after calibration. Tests cover sparse calibration and use enough synthetic rows to exercise the reversed-slope guard independently.
- [ ] Implement confusion counts, positive/macro F1, precision/recall, PR-AUC, actual FPR, coverage, Brier and 10 equal-width reliability/ECE bins. Use 1,000 seed-42 whole-domain bootstrap resamples for 95% percentile intervals; mark insufficient class/group support and undefined metrics as JSON null, not zero/NaN. Include prevalence scenarios 0.1%, 1%, 5%, 10% and redacted error-category counts. Test bootstrap group sampling, not just output shape. Rerun all owning tests and commit; do not inspect real final-test results yet.

### Task 6: Immutable artifacts and inference adapter

**Files:** Create `artifacts.py`, `service.py`, `tests/test_url_ml_artifacts.py`, `tests/test_url_ml_service.py`; extend CLI with `train`, `evaluate`, `predict`.

**Interfaces:** `export_artifact(run: RunBundle, parser: UrlParser, output_dir: Path, version: str) -> dict`; `load_artifact(path: Path) -> RunBundle`; `UrlModelService(artifact_path: Path)` with `assess(url: str) -> UrlAssessment` and `health() -> dict`.

- [ ] Write export/reload equivalence after deleting the original dataset/PSL, nonexistent/wrong-version/tampered dependency/PSL/weights tests, no-deserialisation-before-verification, unavailable/unsupported states, and calibration omission:

```python
def test_corrupt_artifact_never_deserializes(self):
    self.assertEqual(self.corrupt_service.assess("https://example.org/").state, "unavailable")
    self.joblib_load.assert_not_called()
def test_uncalibrated_probability_is_absent(self):
    self.assertNotIn("probability", self.uncalibrated_assessment.to_dict())
```

- [ ] Run artifact/service suites; expect missing loader/adapter behaviour failure.
- [ ] Implement new-directory-only atomic export: trusted `pipeline.joblib`, parser PSL snapshot, calibration/config/manifest JSON, checksums and model card. Record schema/feature/label/dependency versions, source/split hashes, seed, Git commit, thresholds, resources and limitations. Loader validates required metadata, safe relative file paths and all hashes/compatibility before joblib, then rebinds every feature parser to the verified artifact PSL. Accept only locally produced trusted artifacts. No upload endpoint. Artifact files are immutable; final evaluation/report card lives separately and references their hash.
- [ ] Implement service lazy imports and explicit `complete`/`not_assessed`/`unavailable` states. Decisions are `phishing_flag`/`not_flagged`, never `safe`; optional probabilities describe source-benchmark calibration. Evidence uses actual structural observations, with verification action and missing reputation/history checks; no invented site behaviour or raw score. Missing dependencies/resources cannot stop the standard app.
- [ ] Complete CLI persistence: `train` consumes train/validation/calibration only and exports a frozen research-candidate artifact; `evaluate` verifies manifests and evaluates all baselines on the same test, refuses accidental report overwrite; `predict` emits the assessment. Rerun owning tests, confirm model decisions survive export/reload and commit. Real final evaluation remains Task 8.

### Task 7: Opt-in Phase 0 API integration

**Files:** Modify `sentinel/analysis.py`, `sentinel/server.py`; create `tests/test_url_ml_integration.py`; extend existing analysis/server tests where necessary.

**Interfaces:** Append `url_model=None` to `analyze(payload, known_phishing=None, model=None, url_model=None)`; append `url_model_path=None` to `create_server(...)`; add `--url-model`/`SENTINEL_URL_MODEL_PATH` configuration. When configured, add top-level `url_assessment` and health `url_model` status; preserve all existing fields and legacy `--model` semantics.

- [ ] Write integration tests proving the dependency-free subprocess starts, disabled responses retain existing shape, configured missing artifact returns unavailable, learned assessment does not alter harm/profile/rule levels, and analysis remains unsaved:

```python
def test_optional_model_is_separate_and_unsaved(self):
    self.assertIn("url_assessment", self.response)
    self.assertEqual(self.response["fraud"], self.baseline["fraud"])
    self.assertEqual(self.saved_cases, [])
```

- [ ] Run `test_url_ml_integration.py`; expect signature/configuration failure.
- [ ] Implement one service per configured server with a nonblocking one-slot inference semaphore; a busy model returns unavailable/retry guidance rather than building an unbounded thread backlog. In this compatibility API assess only the explicitly submitted `url`; message-extracted links retain legacy rule behaviour and receive a limitation if no explicit URL was supplied. This avoids silently selecting a message link for the new single-URL model. Catch optional-module failures as unavailable; do not reinterpret NB JSON as the new artifact.
- [ ] Rerun integration plus existing analysis/server/storage and web-client checks. Verify a temporary-case save/export/delete retains the configured model version; use a temporary DB, never the user's live case file. Document that current UI rendering is Phase 0 and the standalone/API result is this milestone's model interface. Commit the integration.

### Task 8: Real-data benchmark and reproducible delivery

**Files:** Create `docs/url-ml-workflow.md`; finalise source audit; update README/next steps; publish inspected aggregate reports/model card under `output/research/url-ml-v1/`. No additional product feature in this task.

**Interfaces:** The CLI below implements the previous tasks' contracts; this task verifies them end to end on acquired, audited data.

- [ ] Write the reproduction guide with exact source attribution, hashes, prerequisite/runtime setup, lock installation, capabilities/label mapping and limitations. Preserve the actual acquisition snapshot for reproduction; never substitute a fresh PSL silently. Paths containing spaces are exercised by the CLI integration test. Document that this URL-string benchmark does not reproduce the source paper's full webpage-feature experiment or establish message–URL fusion benefit.
- [ ] From a clean Python 3.11 venv, install the committed lock and run the complete Python suite and `node --test tests/web_client.test.mjs`. Expected: all applicable tests pass, no ML dependency skips. Demonstrate the original launcher without ML installed separately.
- [ ] Run the real pipeline, one command at a time, from the active implementation checkout:

```powershell
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli fetch --root data/url-ml
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli audit --root data/url-ml --config configs/url-ml-v1.json
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli split --root data/url-ml --config configs/url-ml-v1.json
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli pilot --root data/url-ml --config configs/url-ml-v1.json
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli train --root data/url-ml --config configs/url-ml-v1.json --artifact models/url-ml/url-v1 --version url-v1
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli evaluate --root data/url-ml --artifact models/url-ml/url-v1 --out data/url-ml/final-evaluation.json
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli predict --artifact models/url-ml/url-v1 --url https://example.org/
```

`fetch` may reuse byte-verified existing acquisition; `audit`/`split` must refuse overwrite, so for already completed tasks verify/load their frozen outputs rather than rerun into the same directories. Training records peak RAM/time for every candidate. Final evaluation measures cold/warm single-URL latency and whole-domain intervals; no test-driven tuning or promised score.

- [ ] Inspect counts, split isolation, failures, calibration reliability, resource targets and error categories. Publish an accurate final model card and aggregate report only after checking for raw tokens/paths; keep source rows, manifests and binary artifacts ignored. Reproduce assignments and predictions within `1e-6` score tolerance from the same supplied inputs/config. If full training or calibration fails, report that milestone incomplete and preserve diagnostics; a synthetic run is not a substitute.
- [ ] Run scoped final checks and `git diff --check`, commit deliverables, request the selected method's whole-branch review, then push after fixes and fresh relevant verification. Before archiving an implementation worktree, preserve needed ignored source/model artifacts in the active project with verified paths and no silent overwrite. Report measured results and remaining data/application tasks; do not claim the year-long project is complete.

## Self-review and handoff

Coverage: source/labels (Task 2), normalisation/PSL (1), grouped protocol (3), models/resources (4), selection/calibration/statistics (5), artifacts/uncertainty (6), backwards compatibility (7), actual evaluation/reproduction (8). Review Focus cases are assigned explicitly. Parent subprojects B–F remain outside this execution plan.

Recommended execution: **Native**. These tasks share parser, split and artifact contracts; implementing them in one session reduces repeated context setup, followed by an independent whole-branch review. Subagent-driven execution is also available: a fresh implementer and reviewer per task, plus final review, with higher coordination cost.

The human partner must review this written plan and choose the execution method before implementation begins.
