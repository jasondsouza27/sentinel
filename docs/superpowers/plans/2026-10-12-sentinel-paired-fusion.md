# Sentinel Paired Message–Link Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, evidence-gated message/URL/fusion study that reports unavailable until genuinely paired, independently reviewed phishing and legitimate cases pass the primary-study gates.

**Architecture:** Add a separate `sentinel/paired/` research path around the existing curation and Naive Bayes baseline; do not change their historical outputs. Keep private evidence, splits and models local. An optional, versioned API adapter consumes only a reviewed release artifact; the current rule result remains the default.

**Tech Stack:** Windows CPython 3.11.17; stdlib CSV/JSON/hashlib/unittest plus the existing pinned NumPy 2.4.6, scikit-learn 1.9.1, joblib 1.6.0, psutil 7.2.2, threadpoolctl 3.7.0 and offline `UrlParser`/public-suffix snapshot. Existing web/extension JavaScript and Node tests. No new dependency or paid service.

**Spec:** [Approved paired-fusion design](../specs/2026-10-11-sentinel-paired-fusion-design.md), approved by the user's “continue” on 2026-10-12; [year-long design](../specs/2026-10-05-sentinel-year-long-design.md) supplies the research targets.

**Status:** Proposed for user review. Carry forward the user's previously selected native/inline execution with one independent final review after plan approval.

## Global Constraints

- Study labels: `1 = phishing_request`, `0 = verified_legitimate_request`; uncertain and ordinary spam are excluded, never relabelled to fill a class.
- Only original message–destination pairs with permission, redaction review and a traceable private verification record enter the study. No arbitrary destination, redirect, DNS or webpage request.
- Preserve the current `sentinel.curation` two-way lock, `sentinel.research` Naive Bayes benchmark, URL-v1/v2/v3 artifacts, and empty real intake. Synthetic fixtures test software only.
- Primary target: 2,000 reviewed pairs, at least 1,000 per class; the sealed test must have at least 100 per class and 30 distinct domain groups. These gates do not establish representativeness.
- Source identity and available collection period must not perfectly predict class for a claim-ready primary study; report channel and date-coverage limitations. The same connected domain/campaign/URL-stripped-wording group never crosses train, validation, calibration and test.
- One seed `42` and target partition fractions `70/10/10/10`; no retrying seeds or moving groups after viewing test data. Select decision thresholds on validation under a `0.05` FPR budget; calibrate on calibration only; test once.
- Use at most four native CPU threads, one fit at a time and an 8 GiB process-tree memory cap; do not change the existing 17-pin environment. Cap message TF-IDF at 30,000 sparse word features; never densify it.
- Pin the offline private-inclusive suffix snapshot at `resources/url-v2-suffix.dat`, SHA-256 `e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66`; reject a changed parser resource.
- Raw text, URLs, consent records, evidence references, splits and joblib artifacts remain in Git-ignored local `data/curation/` or `models/paired/`; public reports have aggregate counts and hashes only. Git ignore is not a privacy boundary, so do not place private source files in a synced folder without team approval.
- URL-v3 stays research-only and is not the primary URL branch. The paired learned result is disabled in the API unless a separately reviewed release artifact is explicitly supplied.

## Review Focus

1. A reviewer packet or evidence ledger changed after preparation must stop study finalization; missing independent legitimate verification must prevent claim-ready status (Tasks 1–2).
2. A second URL, repeated wording or cross-domain campaign must connect cases across all four partitions, including URLs other than the selected destination (Task 3).
3. Tiny, perfectly confounded or one-giant-component collections must return an unavailable reason without creating a final lock or model (Tasks 2–3, 7).
4. Tied scores, all-negative admissible thresholds, class-sparse out-of-fold partitions and failed calibration must suppress unsupported confidence, never leak test labels into selection (Tasks 5–6).
5. An altered artifact, missing modality, malformed URL or unavailable optional ML dependency must leave the default rule assessment usable and must not display a learned safety claim (Tasks 7–8).

---

## File map and shared contracts

All paths are relative to `C:\Users\Jason Dsouza\Desktop\major project`, the active repository; the chat's OneDrive folder is empty. At execution time, follow the worktree skill and reuse a suitable attached worktree if available. Plan preparation does not edit product code.

| Path | Responsibility |
| --- | --- |
| `sentinel/paired/__init__.py`, `contracts.py` | Lightweight study schemas, immutable settings and unavailable reasons |
| `sentinel/paired/admission.py` | Private evidence ledger, blinded packet and study review/finalization integrity |
| `sentinel/paired/readiness.py` | Counts-only source/channel/period audit and primary-study gates |
| `sentinel/paired/protocol.py` | Connected groups, four-way assignment and immutable split manifest |
| `sentinel/paired/features.py`, `models.py` | URL-stripped message features, paired URL features, branch and out-of-fold fusion fitting |
| `sentinel/paired/evaluation.py` | Validation selection, calibration, one-time grouped paired comparison |
| `sentinel/paired/artifacts.py`, `cli.py` | Checked local artifact, stage receipts and offline commands |
| `sentinel/paired/service.py` | Disabled-by-default optional inference boundary |
| `sentinel/analysis.py`, `sentinel/server.py`, `web/app.js`, `extension/popup.js` | Shared API and optional result presentation |
| `tests/paired_fixtures.py`, `tests/test_paired_*.py`, `tests/test_analysis.py`, `tests/test_server.py`, `tests/web_client.test.mjs`, `tests/extension_popup.test.mjs` | Synthetic software and compatibility tests |
| `docs/paired-study-workflow.md`, `docs/next-steps.md`, `README.md` | Team collection handoff and reproduction commands |

`EVIDENCE_FIELDS = (case_id,evidence_id,evidence_type,verification_ref,observed_on,source_sha256,source_version,permission_basis,redaction_decision)`. `evidence_id` and `verification_ref` are opaque pointers to private records, not source text or public URLs. `observed_on` may be empty; `source_sha256` and `source_version` are required for `licensed_public` cases. `evidence_type` is one of `official_confirmation`, `independent_threat_report`, `source_record`, `consent_record`; reviewers still make the label decision. `redaction_decision` is `redacted` or `none_needed`. A `source_record` or `consent_record` alone cannot independently verify a legitimate request.

Readiness `status` is `pending_review`, `unavailable`, or `eligible_for_freeze`; eligibility is provisional until four partitions meet their gates. `StudyCriteria` contains production targets above; tests may pass smaller explicit criteria to pure allocation/evaluation functions, but the production CLI never accepts overrides. All output stages refuse overwrite, hash their inputs, and publish only after complete validation. Existing two-way files under `locked/` are untouched; new four-way files live under `study-v1/`.

Use `& .\.venv-url-v2-check\Scripts\python.exe -m unittest discover -s tests -p '<test_file.py>' -v` for each scoped Python test and `& .\.venv-url-v2-check\Scripts\python.exe -m unittest discover -s tests -v` for the full suite. Run `node --test tests/web_client.test.mjs tests/extension_popup.test.mjs` for the client suites; Node 22 is installed. Verify exit codes and zero skips. Run commands from the execution checkout.

### Task 1: Private evidence and review packet

**Files:** Create `sentinel/paired/__init__.py`, `contracts.py`, `admission.py`, `tests/paired_fixtures.py`, `tests/test_paired_admission.py`; modify `.gitignore` for `models/paired/`.

**Interfaces:** `validate_ledger(root: Path, intake: list[dict[str,str]]) -> dict[str,dict[str,str]]`; `prepare_study_reviews(root: Path) -> dict`; `finalize_study_reviews(root: Path) -> dict`; `verify_finalized_study(root: Path) -> dict`. Reuse `curation._intake`, `prepare_reviews`, `finalize_reviews`, and `_verify_finalized`; do not alter their historical file schemas.

- [ ] Write failing tests: exact one-to-one ledger/intake IDs, permission equality, date/hash syntax, source fields for licensed data, and no plaintext verification material in `case_packet.csv`; `prepare_study_reviews` hides source-provided labels but includes opaque evidence pointers. After preparation, changing the ledger or packet makes `finalize_study_reviews` fail before `final_pairs.csv` appears.
- [ ] Run `test_paired_admission.py`; expect missing paired module/functions.
- [ ] Implement validated ledger, packet and `study_review_manifest.json` hashes. The wrapper runs existing two-reviewer operations in a temporary copy and publishes checked outputs together; `study_final_manifest.json` binds ledger/packet/intake/finalization hashes. Keep consent/screenshot evidence outside the repository.
- [ ] Run `test_paired_admission.py` and `test_curation.py`; expect all pass with no existing baseline schema change.
- [ ] Commit these paths: `feat: bind paired reviews to private evidence records`.

### Task 2: Counts-only feasibility and honest unavailable status

**Files:** Create `sentinel/paired/readiness.py`, `tests/test_paired_readiness.py`; modify `sentinel/paired/contracts.py`; extend `tests/paired_fixtures.py`.

**Interfaces:** Define `StudyCriteria` and `PRODUCTION_CRITERIA` in `contracts.py`. `readiness_report(root: Path, criteria: StudyCriteria = PRODUCTION_CRITERIA) -> dict` consumes Task 1 verification when finalized. It returns `status`, `reasons`, counts and cross-tabs, never row text/URLs/evidence refs. Empty intake returns `unavailable` with zero admitted cases; nonempty unfinalized intake returns `pending_review`; passing aggregate gates returns `eligible_for_freeze`.

- [ ] Write failing tests for empty intake, pending review, two-reviewer finalized data, fewer than 1,000 per class, one-source-per-label, channel and known-period confounding, unknown observation dates, and a legitimate label whose ledger has only `source_record`. Assert JSON contains no message, URL, case ID or verification reference; channel imbalance is reported, while source or known-period perfect prediction blocks eligibility.
- [ ] Run `test_paired_readiness.py`; expect missing report.
- [ ] Implement class/source/channel/month cross-tabs using opaque source IDs, independent group counts and explicit `claim_ready=False` reasons. A perfect source or known-period predictor blocks the primary claim; missing dates are reported as unknown rather than invented. Verification type is a completeness flag, not automatic proof of authenticity.
- [ ] Run `test_paired_readiness.py` and `test_paired_admission.py`; expect all pass.
- [ ] Commit: `feat: audit paired-study readiness without exposing cases`.

### Task 3: Sealed four-way, connected-group protocol

**Files:** Create `sentinel/paired/protocol.py`, `tests/test_paired_protocol.py`; extend `tests/paired_fixtures.py`.

**Interfaces:** `connected_groups(rows: list[dict], parser: UrlParser) -> dict[str,str]`; `allocate_partitions(rows: list[dict], parser: UrlParser, *, seed: int = 42, criteria: StudyCriteria = PRODUCTION_CRITERIA) -> dict[str,list[dict]]`; `freeze_study(root: Path, parser: UrlParser) -> dict`; `load_development(root: Path, parser: UrlParser) -> dict`; `load_final_test(root: Path, parser: UrlParser, receipt: dict) -> list[dict]`. Use `resources/url-v2-suffix.dat` with its checked SHA and `UrlParser` for registrable domains; normalize message wording after removing every URL span. Training cannot load the final test through `load_development`.

- [ ] Write failing tests that link cases through the selected domain, another URL in the message, shared `campaign_group` and URL-stripped wording. Assert zero component overlap in train/validation/calibration/test; classes and production test minima are enforced, huge connected groups fail, corrupt input/manifest hashes fail and pre-existing `study-v1/` is never overwritten.
- [ ] Run `test_paired_protocol.py`; expect missing allocator.
- [ ] Implement a deterministic whole-component assignment with one seed and `70/10/10/10` targets. Validate readiness and all gates before publishing private CSVs plus `study-v1/manifest.json`; fail instead of retrying seeds or splitting components.
- [ ] Run `test_paired_protocol.py` and `test_research.py`; expect all pass.
- [ ] Commit: `feat: freeze group-isolated paired-study partitions`.

### Task 4: Fair message and URL branch models

**Files:** Create `sentinel/paired/features.py`, `models.py`, `tests/test_paired_features.py`, `tests/test_paired_models.py`.

**Interfaces:** `strip_links(message: str) -> str`; `build_branch(kind: str, parser: UrlParser, config: dict) -> object` for `message`, `url`, `early`; `fit_branch_candidates(train: list[dict], parser: UrlParser, config: dict) -> dict[str,tuple[BranchCandidate,...]]`; `score_candidate(candidate: BranchCandidate, rows: list[dict]) -> list[float]`. Define `BranchCandidate(kind, config_id, model, fit_record)`; keys are `message`, `url`, `combined`, with early fusion under `combined`. Existing Naive Bayes runs through `sentinel.research` as a separately labeled baseline, never as the learned fusion score.

- [ ] Write failing tests proving message-only text cannot see host/path/query tokens, URL-only sees no message wording, early combination uses both, and all branches score the same ordered case IDs. Malformed or missing URL is unsupported rather than replaced by a benign URL.
- [ ] Run the two scoped tests; expect missing feature/model factories.
- [ ] Implement message word TF-IDF `(1,2)` with `max_features=30000` and logistic `C in {0.5,1.0}`; URL lexical transformer with offline parser and HGB `max_depth in {3,5}`, `max_iter=150`; early sparse TF-IDF plus lexical vector with logistic `C in {0.5,1.0}`. Fix `random_state=42`, restrict to four native threads, and fit candidates sequentially in a monitored worker capped at 8 GiB. Fit vectorizers only on their training partition.
- [ ] Run scoped tests and `test_url_ml_training.py`; expect all pass.
- [ ] Commit: `feat: train isolated message URL and early-fusion branches`.

### Task 5: Out-of-fold late fusion

**Files:** Extend `sentinel/paired/models.py`; create `tests/test_paired_fusion.py`.

**Interfaces:** `fit_late_fusion(train: list[dict], parser: UrlParser, config: dict, *, folds: int = 5) -> BranchCandidate`; its `model` holds the late logistic learner and final fitted message/URL branches; `score_candidate` from Task 4 handles it. Add this candidate to the `combined` list. The fit record contains fold IDs, group counts, class counts and hashes, never row text.

- [ ] Write failing tests that spy on every fold fit: no scored row or connected group is in its branch-training fold, no vocabulary fitted on out-of-fold text, every training row gets exactly one held-out branch score, and class-sparse folds yield `late_fusion_unavailable` rather than in-sample fallback.
- [ ] Run `test_paired_fusion.py`; expect missing interface.
- [ ] Implement five deterministic group-disjoint folds inside training only; train branch models afresh per fold, fit logistic fusion to their held-out message/URL scores, then fit final branch models on all training rows. Record the fold audit; do not read validation/calibration/test labels here.
- [ ] Run `test_paired_fusion.py` and `test_paired_models.py`; expect all pass.
- [ ] Commit: `feat: learn late fusion from group-held-out branch scores`.

### Task 6: Validation, calibration and paired final metrics

**Files:** Create `sentinel/paired/evaluation.py`, `tests/test_paired_evaluation.py`.

**Interfaces:** `select_candidates(candidates: dict[str,tuple[BranchCandidate,...]], validation: list[dict]) -> dict[str,Selection]`; `fit_calibrators(selections: dict[str,Selection], calibration: list[dict]) -> dict`; `evaluate_branches(selections: dict[str,Selection], test: list[dict], calibrators: dict, groups: dict[str,str]) -> dict`. Define `Selection(candidate, raw_threshold, validation_report)`; choose one `combined` candidate from early/late using validation only. Reuse `url_ml.metrics.choose_threshold`/`point_metrics` and `url_ml.calibration.fit_calibration` where contracts fit; paired intervals use connected groups and preserve branch-paired resamples.

- [ ] Write failing tests for threshold FPR `<=0.05` on validation, an admissible all-negative threshold, tied scores, calibration with too few cases, no numerical confidence when unavailable, identical test cases for every branch, connected-group bootstrap deltas, and test labels never passed to selection/calibration. The old Naive Bayes baseline must remain separately named with its fixed default decision, not presented as a 5%-budget candidate.
- [ ] Run `test_paired_evaluation.py`; expect missing evaluator.
- [ ] Implement validation selection among fixed candidate grids: maximize recall within the 5% FPR budget, then precision, then lower FPR, then `config_id`. Calibrate on calibration only. The final report includes confusion, precision, recall, F1/macro F1, PR-AUC, FPR, coverage, Brier/ECE when available, latency, peak memory, 1,000 group-bootstrap replicates (`seed=42`), and aggregate source/channel/date-coverage/URL-pattern breakdowns. Compare combined against **both** individual branches at their validation-selected thresholds; report the original Naive Bayes separately and mark sparse intervals unavailable. Keep individual error-case IDs in the private review workspace, never the public aggregate report.
- [ ] Run `test_paired_evaluation.py` and `test_url_ml_metrics.py`; expect all pass.
- [ ] Commit: `feat: measure frozen paired-model differences`.

### Task 7: Integrity-checked artifact and offline stage CLI

**Files:** Create `sentinel/paired/artifacts.py`, `cli.py`, `tests/test_paired_artifacts.py`, `tests/test_paired_cli.py`; extend `.gitignore` if needed.

**Interfaces:** `export_study_artifact(selections: dict[str,Selection], calibrators: dict, protocol: dict, output: Path) -> dict`; `load_study_artifact(path: Path) -> object`; CLI `python -m sentinel.paired.cli {prepare,finalize,audit,freeze,train,evaluate,predict} --root <directory>`. `train` consumes only a hash-verified `study-v1` train/validation/calibration lock. Exported artifacts have `release_status=research_only`. `evaluate` writes `final_access.json` **before** calling `load_final_test` for sealed rows.

- [ ] Write failing tests for changed private inputs/split hashes, incomplete or replaced artifact members, foreign/unsupported joblib metadata, repeated final evaluation, interrupted evaluation with same-version resume, and a zero-row CLI `audit` yielding `unavailable` while `freeze/train/evaluate` create no model or result.
- [ ] Run scoped artifact/CLI tests; expect missing commands.
- [ ] Implement transactional private stage outputs, SHA-256 manifests, environment/model metadata and a model card. Load only locally trusted artifacts after metadata/hashes are checked and only then deserialize joblib. Final-access receipt binds protocol, artifact and output identity; resume only the identical interrupted attempt. Public JSON contains aggregates/hashes, no row-level data.
- [ ] Run scoped tests and `test_curation.py`; expect all pass.
- [ ] Commit: `feat: add checked paired-study stages and unavailable outcome`.

### Task 8: Guarded shared API and optional presentation

**Files:** Create `sentinel/paired/service.py`, `tests/test_paired_service.py`, `tests/extension_popup.test.mjs`; modify `sentinel/analysis.py`, `sentinel/server.py`, `web/app.js`, `extension/popup.js`, `tests/test_analysis.py`, `tests/test_server.py`, `tests/web_client.test.mjs`.

**Interfaces:** `PairedService(path: Path).health() -> dict`; `.assess(message: str, url: str) -> dict`; extend `analyze(..., paired_model=None)` and `create_server(..., paired_model_path=None)`. Add `--paired-model` / `SENTINEL_PAIRED_MODEL_PATH` opt-in. The response has optional `paired_assessment` with `state`, `category`, `evidence`, `uncertainty`, `unavailable_checks`, `action`, `model_version`; it never overwrites `fraud` or `url_assessment`.

- [ ] Write failing tests: default API JSON unchanged; research-only/tampered/missing artifact reports unavailable; no message or URL returns explicit missing-modality state; malformed URL and absent ML package do not break rule analysis; a mocked approved artifact yields a separate category with no unsupported “safe” or numerical confidence. Web and extension use a renderer for `state`/`category` (the existing cards expect `level`), render only the optional result and place message-derived text with `textContent`.
- [ ] Run Python service/analysis/server tests and Node web/extension tests; expect missing optional integration.
- [ ] Implement lazy dependency loading and release-status guard; no live learned warning from this milestone's research artifact. `evidence` contains only transparent observations already supported by the submitted content, never invented model attribution. Keep existing evidence-rule explanations intact. Both clients use the same response field and no new extension permissions.
- [ ] Re-run scoped Python and both Node tests; expect all pass.
- [ ] Commit: `feat: expose guarded paired assessment through shared API`.

### Task 9: Reproduction workflow and end-to-end software check

**Files:** Create `docs/paired-study-workflow.md`, `tests/test_paired_workflow.py`; modify `README.md`, `docs/next-steps.md`.

**Interfaces:** Document all seven CLI stages, evidence-ledger columns, local private storage, four-person review roles, label meanings, source-confounding gate, and the exact `unavailable` outcome when no reviewed pairs exist. No fabricated research score or sample case is published as a finding.

- [ ] Write failing end-to-end test that runs empty CLI `audit` and a complete **synthetic software fixture** through internal prepare/finalize/freeze/train/evaluate functions with explicit reduced test criteria. Assert frozen hashes and no case text/URLs in aggregate outputs; CLI production still rejects the fixture below production gates.
- [ ] Run `test_paired_workflow.py`; expect missing workflow/stages.
- [ ] Add workflow and user handoff documentation; make the test pass without editing the real `data/curation/intake.csv` or protected URL-v3 files.
- [ ] Run full Python unittest suite, both Node suites, `git diff --check`, and a real empty-intake `audit`; record exact pass/skip counts, aggregate unavailable reason, and resource measurements. Do not run final phishing evaluation on the unreviewed candidate sheets.
- [ ] Commit: `docs: record paired-study workflow and readiness handoff`.

## Human-data gate after software delivery

The four-member team must obtain traceable, permissioned positive **and** independently verified legitimate pairs, complete two independent reviews/adjudication, then inspect the counts-only readiness report. The existing 100 NC State and 18 potential legitimate SMS candidates stay unreviewed until people admit them. If the report fails its source/period/size/group gates, preserve `unavailable`; do not relax criteria, graft unrelated URL labels onto messages, or activate the adapter. Once a real batch is `eligible_for_freeze`, lock it and execute the final study once if every partition gate passes. Review its false positives and model card before considering a separately approved release artifact. User-pilot measurement is a later application milestone.
