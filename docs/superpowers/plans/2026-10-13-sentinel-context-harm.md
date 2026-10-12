# Sentinel English Conversation and Harm Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible English directed-abuse study comparing a target message with its preceding conversation, and integrate ordered conversation checks and exact assessment saving into Sentinel.

**Architecture:** Add a separate `sentinel/context_harm/` package with verified CAD ingestion, protected cohorts, bounded model workers and immutable research artifacts. Share one text/context contract between research and the existing local API; preserve rule results when learned inference is unavailable. Keep the compact encoder in its own environment and maintain an initially empty human-review challenge workflow.

**Tech Stack:** Windows CPython 3.11.17, stdlib/unittest, the existing locked CPU NumPy/scikit-learn/SciPy/joblib/psutil/threadpoolctl environment, a separately pinned PyTorch/Transformers/Safetensors environment, existing JavaScript and Node 22 tests. No framework migration or paid service.

**Spec:** [Approved English conversation/harm design](../specs/2026-10-13-sentinel-context-harm-design.md), approved on 2026-10-13; [source investigation](../../context-harm-source-audit-2026-10-12.md) supplies measured feasibility figures.

**Status:** Proposed for plan review. Preserve the user's choice of implementation in this chat with one final independent whole-branch review. Plan preparation installed no dependencies, downloaded no package/model bodies and ran no training or final scoring.

## Global Constraints

- The learned task is binary English directed abuse, separate from toxicity, intent, repeated harassment, phishing and profile authenticity. Preserve the spec's explicit label mapping; invalid/unknown label sets fail before binary assignment.
- CAD archive SHA-256: `69f5ed2fd7b40de21fe54c620549f0be6c34eaf55b8de06ff481cabe3e9476d2`; selected `data/cad_v1_1.tsv` SHA-256: `7287d635e1d35ae1e64779ffe107df16f493c6ccc4084c4497bbf3f56ae0f349`. CC BY 4.0 attribution is required.
- Limit archive bodies to 12 MiB, the selected inflated TSV to 16 MiB and metadata to 1 MiB; enforce both a 120-second request deadline and a 32 MiB durable aggregate received/reserved-byte budget. Download failure is unavailable, not an empty dataset.
- Parse with `QUOTE_NONE`; metadata missing markers must not become shared identities. Gold labels/context tags/highlights, author/thread/source/split IDs and dates never enter features.
- Use at most four preceding ancestor turns, oldest to newest; root title/body each count as a turn. Never include siblings or later turns. Both primary branches use identical context-available cases and target preprocessing.
- Preserve published test-thread ownership. Purge whole development threads sharing known test authors, including contextual/excluded source rows; then purge protected duplicates. Unknown authors remain unknown.
- Use seed 42 once and development fractions 70/15/15. Training needs at least 200 cases per class; validation and calibration at least 30 per class and ten components each; primary test at least 100 per class and 30 retained threads. No development component may exceed 70% of the cohort. Failed gates publish no replacement split or fitted model.
- CPU grids: word TF-IDF `(1,2)`, 30,000 sparse features per space; `C = 0.5, 1.0, 2.0` crossed with `class_weight = None, balanced`; `liblinear`, `max_iter=1000`, seed 42. One fit at a time, four native threads, 8 GiB process-tree RSS, 15-minute CPU-fit deadline; never densify.
- DistilBERT revision `12040accade4e8a0f71eabdb258fecc2e7e948be`; pinned Safetensors/config/tokenizer/vocabulary/licence/card only, maximum 512 MiB model-source bodies, no remote code. Pilot: at most 32 training cases, 20 optimizer steps, sequence length 256, microbatch two, accumulation four, FP16 when supported, ten minutes, 3.2 GiB allocated/reserved GPU memory each, 8 GiB RSS. Full neural candidate deadline: 30 minutes.
- Neural candidates: learning rates `2e-5, 5e-5`, at most three epochs, AdamW, weight decay 0.01 and seed 42. Both neural branches abstain when the target exceeds 252 WordPiece tokens; the contextual pair reserves three special tokens and at least one context token.
- Selection maximizes validation recall under 5% FPR, then precision, lower FPR and config ID. Calibrate separately; three component-grouped calibration folds require held-out support of five per class and fit support of 20 per class. Unsupported/worsened calibration suppresses probabilities.
- Final scoring is reserved durably once, with implementation/settings/source/artifact/runtime/cohort bindings. Use 1,000 paired component-bootstrap replicates, seed 42. Intervals are unstable/unavailable if a class spans fewer than ten components or one component contains more than half the test cases.
- Structured input permits one to 50 turns, IDs matching `[A-Za-z0-9_-]{1,64}`, 20,000 total characters and 10,000 target characters. Reply references point only backwards. `language=en` is supported; omitted language is an assumption, other declarations are not assessed.
- Harm inference permits one worker, four threads, 60 seconds and 8 GiB RSS. Share the 8 GiB optional-inference reservation budget with other configured optional checks; busy/failure cannot break rule assessments. No job API, continuous monitoring, new extension permissions or payload logging.
- New private paths: `data/context-harm/`, `models/context-harm/`, `.venv-harm-neural/`. Preserve the existing 17 CPU dependency pins, URL/paired artifacts and empty real paired intake. Public reports contain aggregate counts and hashes, never source/challenge text or identities.
- Initial artifacts are `research_only`; live inference stays unavailable for them. Challenge labels require two independent humans and adjudication. Synthetic fixtures measure software behaviour only.

## Review Focus

1. Quoted `"NA"`, removed identities and multiple annotation rows must not join unrelated threads or change the literal quotation marks in text (Task 1).
2. Root title/body aliases, unsupported intermediate parents and a target before later messages must not introduce a sibling, invented connection or future text (Task 2).
3. After author/duplicate purging, class loss or an oversized connected component must yield an honest unavailable allocation rather than relaxed criteria or seed retries (Task 4).
4. A worker that exits while a descendant survives, oversized download or failed CUDA optimizer step must release resources and publish no successful partial candidate (Tasks 5, 7, 10).
5. Changed model settings, edited turns, expired save receipts and late browser replies must not replace or save an assessment the user did not review (Tasks 9–11).

## File map and interfaces

Paths are relative to the active repository, `C:\Users\Jason Dsouza\Desktop\major project`; the old OneDrive entry is empty. At execution, use the worktree skill, inspect attached worktrees and create/reuse suitable isolation from the approved default branch. Do not reuse the merged paired checkout as if it were this feature. Record baseline hashes of the old locks and URL/paired research artifacts before product changes.

| Files | Responsibility |
| --- | --- |
| `sentinel/context_harm/{__init__,contracts,integrity}.py`, `configs/context-harm-v1.json` | Lightweight types, production constants, canonical hashing and atomic private stage publication |
| `sentinel/context_harm/{transport,source}.py` | Official-source byte budgets, CAD verification/parser/coalescing and codebook audit |
| `sentinel/context_harm/{conversation,text}.py` | Source ancestry, submitted turn validation, shared masking and duplicate normalization |
| `sentinel/context_harm/challenge.py` | Empty intake, blinded review packets, adjudication and reserved challenge ownership |
| `sentinel/context_harm/protocol.py` | Whole-thread purges, connected components, readiness and sealed partition manifests |
| `sentinel/context_harm/{runtime,worker,cpu}.py` | Bounded native workers and sparse CPU fitting/scoring |
| `sentinel/context_harm/selection.py` | Validation choices and grouped out-of-fold sigmoid calibration |
| `sentinel/context_harm/{neural_sources,neural}.py` | Pinned runtime/base model, CUDA pilot, token coverage and compact encoder candidates |
| `sentinel/context_harm/{artifacts,access,evaluation,cli}.py` | Checked local bundles, durable final receipt, aggregate comparison and stage commands |
| `sentinel/context_harm/service.py`, `sentinel/optional_work.py`, `sentinel/assessment_receipts.py` | Disabled-by-default learned boundary, shared reservations and stateless save receipts |
| `sentinel/analysis.py`, `sentinel/server.py` | Compatible structured analysis, health/configuration, exact saving and static route |
| `web/conversation.js`, `web/{app.js,index.html,styles.css}`, `extension/popup.js` | Turn editor, context/result display, exact snapshot saving and explicit extension checks |
| `tests/context_harm_fixtures.py`, `tests/test_context_harm_*.py`, `tests/conversation_editor.test.mjs` | Invented source/conversation fixtures and substantive isolation/failure tests |
| Existing server/analysis/storage and web/extension tests | Compatibility, exact saved result and late-reply regressions |

Define these immutable contracts in Task 1; no ML import at package import time:

- `HarmError(reason: str)`; `HarmCriteria(train_per_class, validation_per_class, calibration_per_class, development_components, test_per_class, test_threads, max_component_fraction)` with production defaults above.
- `ModelText(target: str, context: tuple[str,...])`.
- `CadUtterance(case_id, thread_id, parent_id, root_id, author_id, order, text, split, labels, context_tags, eligible, text_supported, metadata)`: IDs/text/split are strings; nullable IDs remain `None`; `order` and label/tag sets are tuples of strings; metadata is private.
- `SourceRelease(records: tuple[CadUtterance,...], provenance: dict)`; `HarmCase(case_id: str, model_input: ModelText, context_ids: tuple[str,...], thread_id: str, label: int, metadata: dict)`.
- `CaseCohort(primary: tuple[HarmCase,...], diagnostics: tuple[HarmCase,...], source: SourceRelease, audit: dict)`; `FrozenStudy(path: Path, manifest: dict)`.
- `CandidateRef(kind: str, config_id: str, directory: Path, fit_record: dict)`; `ScoreBatch(case_ids: tuple[str,...], scores: tuple[float|None,...], coverage: tuple[bool,...], runtime: dict)`.
- `Selection(candidate: CandidateRef, raw_threshold: float|None, validation_report: dict)`; `CalibrationRecord(status: str, slope: float|None, intercept: float|None, report: dict)`.
- `WorkerLimits(deadline_seconds: int, rss_bytes: int, native_threads: int)`; `WorkerRecord(status: str, reason: str|None, measurements: dict, output: dict)`.

Tests may inject smaller criteria into pure allocation functions. Production CLI/freezing verifies the exact production settings and source receipts; synthetic protocols/artifacts are explicitly marked and cannot become real research or live releases.

Scoped Python verification command: `& .\.venv-url-v2-check\Scripts\python.exe -m unittest discover -s tests -p 'test_context_harm_<component>.py' -v`. A worktree may use the existing primary environment interpreter by absolute path with its working directory set to the worktree. Full command: the same interpreter with `-m unittest discover -s tests -v`; client command: `node --test tests/web_client.test.mjs tests/extension_popup.test.mjs tests/conversation_editor.test.mjs`. Expect successful exit and zero skips; conditional real CUDA outcomes are explicit reports, not skipped software tests.

### Task 1: Verified CAD release and label admission

**Files:** Create `sentinel/context_harm/__init__.py`, `contracts.py`, `integrity.py`, `transport.py`, `source.py`, `configs/context-harm-v1.json`, `tests/context_harm_fixtures.py`, `tests/test_context_harm_source.py`; modify `.gitignore` for all three new private paths.

**Interfaces:** `acquire_release(root: Path, settings: dict) -> dict`; `load_source(root: Path, settings: dict) -> SourceRelease`; `coalesce_rows(rows: list[dict[str,str]]) -> tuple[CadUtterance,...]`; `map_labels(labels: tuple[str,...]) -> int`; `publish_stage(stage: Path, output: Path, members: dict[str,str]) -> dict`. Integrity helpers `sha256(path: Path) -> str` and `canonical_sha256(value: object) -> str` reject nonfinite JSON.

- [ ] Write failing tests, including these assertions and release corruption/oversize, cumulative interrupted budget, wrong member and unsupported label cases:

```python
self.assertIsNone(records['missing'].author_id)
self.assertEqual(records['quoted'].text, 'Someone said "stop".')
self.assertEqual(map_labels(('Slur',)), 0)
self.assertEqual(map_labels(('CounterSpeech', 'PersonDirectedAbuse')), 1)
```

- [ ] Run `test_context_harm_source.py`; expect missing harm interfaces, not a network-dependent failure.
- [ ] Implement strict schema/metadata parsing, same-utterance conflict checks and fixed label precedence. Follow the existing acquisition journal's durable read/reservation pattern in the new transport without changing URL transport. Fetch only the official pinned archive/metadata, inspect safe archive members without extracting arbitrary paths, and hash the codebook read from that archive. Record a taxonomy/codebook consistency audit before any protocol freeze; a disagreement blocks admission. The source audit reports eligible/exclusion/mixed-label counts and no raw text.
- [ ] Run this scope plus existing URL transport/source tests; expect pass and unchanged existing acquisition outputs.
- [ ] Commit the listed paths as `feat: admit verified CAD directed-abuse records`.

### Task 2: Shared ancestry and submitted conversation contract

**Files:** Create `sentinel/context_harm/conversation.py`, `text.py`, `tests/test_context_harm_conversation.py`, `tests/test_context_harm_text.py`; extend fixtures.

**Interfaces:** `build_cases(source: SourceRelease, settings: dict) -> CaseCohort`; `parse_submission(payload: dict) -> ConversationInput`; define `ConversationInput(target_id: str|None, model_input: ModelText, turns: tuple[dict,...], coverage: dict, language: str, language_assumed: bool)`; `prepare_model_text(value: ModelText) -> ModelText`; `duplicate_keys(value: ModelText) -> dict`; `simhash_target(text: str) -> int`.

- [ ] Write failing tests for root aliases, missing/unsupported intermediate parents, cycles, ordering contradictions, cross-thread references, valid backward replies, partial structured fields, unknown turn fields, invalid IDs/relative times and dual-target disagreement:

```python
request = parse_submission(linear_request(target='t2', later_text='future threat'))
self.assertNotIn('future threat', request.model_input.context)
self.assertEqual(len(build_cases(source, settings).primary[0].model_input.context), 4)
self.assertEqual(prepare_model_text(a).target, prepare_model_text(b).target)
```

Here `a` and `b` differ only in URL/username spelling. Add exact 50/51-turn and 20,000/20,001-total-character boundaries, unsupported declared language, legacy-only conversation and literal quoted text.
- [ ] Run both scopes; expect missing conversation/text interfaces.
- [ ] Implement same-thread ancestor traversal; stop at unsupported/missing ancestors without jumping over them. Root title/body resolve only through confirmed root metadata. Decode the release's linebreak convention; retain raw provenance privately. Apply the 10,000 target and 20,000 combined character caps to the target and four-turn model window, while auditing the remaining ancestry. Apply URL and `@name`, `u/name`, `/u/name` masking with stable placeholders; duplicate normalization is NFC/casefold/whitespace with Unicode `\b\w+\b` word tokens. SimHash uses trigram occurrence weights, canonical JSON serialization, the first eight SHA-256 bytes and the spec's bit/bucket rules. Local speakers remain display/audit metadata.
- [ ] Run both scopes and existing `test_analysis.py`; expect pass without changing legacy analysis yet.
- [ ] Commit as `feat: reconstruct and validate target conversation context`.

### Task 3: Empty private challenge and independent review workflow

**Files:** Create `sentinel/context_harm/challenge.py`, `tests/test_context_harm_challenge.py`; extend fixtures.

**Interfaces:** `init_challenge(root: Path) -> dict`; `prepare_challenge_reviews(root: Path) -> dict`; `finalize_challenge_reviews(root: Path) -> dict`; `challenge_reservation(root: Path) -> dict`; `audit_challenge(root: Path) -> dict`.

- [ ] Write failing tests for empty initialization, missing permission/provenance, identical reviewer identities, modified packets, disagreement without adjudication, uncertain labels and an attempt to use predictions as gold:

```python
init_challenge(root)
self.assertEqual((root / 'challenge/intake.jsonl').read_text(), '')
self.assertEqual(audit_challenge(root)['status'], 'pending')
self.assertFalse(audit_challenge(root)['claim_ready'])
```

- [ ] Run `test_context_harm_challenge.py`; expect missing workflow.
- [ ] Implement private JSONL intake fields `case_id, conversation_kind, conversation_turns, target_turn_id, source_ref, permission_basis, verification_ref, collected_on, family`. Family is one of `quoted_abuse, reported_abuse, counter_speech, disagreement, direct_abuse, uncertain`; labels are separate human decisions `0,1,uncertain`. Produce blinded packet plus separate reviewer CSVs; require two distinct reviewers and recorded adjudication. Final reservation binds packet/intake/review hashes, known source ownership and masked duplicate keys. Reject overwrite; initialize no invented examples. Public audits expose counts only.
- [ ] Run this scope and the existing curation scopes; expect pass with real paired intake unchanged.
- [ ] Commit as `feat: prepare independent contextual-harm challenge reviews`.

### Task 4: Protected cohort and immutable development splits

**Files:** Create `sentinel/context_harm/protocol.py`, `tests/test_context_harm_protocol.py`; extend fixtures.

**Interfaces:** `audit_cohort(cohort: CaseCohort, challenge: dict, criteria: HarmCriteria) -> dict`; `connected_components(cases: tuple[HarmCase,...], source: SourceRelease) -> dict[str,str]`; `allocate_development(cases: tuple[HarmCase,...], components: dict[str,str], criteria: HarmCriteria, seed: int = 42) -> dict[str,tuple[HarmCase,...]]`; `freeze_study(root: Path, settings: dict) -> FrozenStudy`; `load_development(study: FrozenStudy) -> dict[str,tuple[HarmCase,...]]`.

- [ ] Write failing tests where a known test author occurs only in an excluded/context row; also test masked duplicates, near duplicates and a missing author marker across many unrelated threads:

```python
self.assertNotIn('author-linked-development-thread', retained_threads)
self.assertEqual(set(parts), {'train', 'validation', 'calibration'})
self.assertFalse(cross_partition_author_or_context_overlap(parts))
self.assertFalse((failed_root / 'v1/manifest.json').exists())
```

Pin tests for class loss, one oversized component, absent challenge reservation and changed raw/derived files.
- [ ] Run `test_context_harm_protocol.py`; expect missing purge/allocation functions.
- [ ] Implement whole-thread test-author purge, protected exact/meaningful/SimHash duplicate purge and author/duplicate connected grouping. Reserve development-derived challenge threads before fitting; challenge overlap with protected test ownership blocks that challenge admission. Allocate components once, largest first with seed-42 tie order, minimizing squared normalized row/class deviation from 70/15/15; validate every gate afterwards. A greedy allocation failure is reported as failure of this allocation, not mathematical proof that no allocation exists. Atomically publish private partitions and a manifest with source/config/implementation/member/cohort hashes, exclusions and coverage. `load_development` has no test-return path.
- [ ] Run this scope and source/conversation/challenge scopes; expect pass, no retries and immutable successful output.
- [ ] Commit as `feat: freeze author and duplicate isolated harm cohorts`.

### Task 5: Bounded sparse CPU candidates

**Files:** Create `sentinel/context_harm/runtime.py`, `worker.py`, `cpu.py`, `tests/test_context_harm_runtime.py`, `tests/test_context_harm_cpu.py`.

**Interfaces:** `run_worker(command: list[str], limits: WorkerLimits, *, cancel: threading.Event|None = None, input_payload: bytes|None = None) -> WorkerRecord`; `fit_cpu_candidates(study: FrozenStudy, output: Path, settings: dict) -> tuple[CandidateRef,...]`; `score_candidate(candidate: CandidateRef, rows: tuple[HarmCase,...], runtime: dict|None = None) -> ScoreBatch`. Training entry point: `python -m sentinel.context_harm.worker --request <private-json-path>`; requests identify operation, verified inputs and private output, never pass case text in command arguments. Inference uses `--request-stdin` and sends bounded input bytes only after the ownership handshake; it writes no unsaved payload to disk.

- [ ] Write failing feature-isolation and resource tests, including a child spawning a sleeping descendant before the parent exits:

```python
self.assertEqual(scores_before_metadata_change, scores_after_metadata_change)
self.assertTrue(sparse.issparse(context_matrix))
self.assertLessEqual(context_matrix.shape[1], 60000)
self.assertEqual(timed_out.status, 'unavailable')
self.assertFalse(descendant_is_running)
```

- [ ] Run both scopes; expect missing worker/CPU factory.
- [ ] Implement a Windows Job Object owned by the supervisor with kill-on-close, plus psutil RSS monitoring at 100 ms and deadline/cancel checks. Workers wait for an ownership handshake before reading private requests/importing ML. If ownership/monitoring cannot be established, fail before fitting. Set native-thread environment variables to four and bound stdout/stderr to 64 KiB with no payload text. CPU target features use one vectorizer; contextual features use separate target/context vectorizers and sparse concatenation. Fit six configurations per branch sequentially; nonconvergence/resource failure records a failed candidate and publishes no successful partial bundle.
- [ ] Run both scopes and existing ML training tests; expect pass, bounded workers and unchanged old training behaviour.
- [ ] Commit as `feat: fit bounded sparse directed-abuse candidates`.

### Task 6: Frozen validation choices and supported calibration

**Files:** Create `sentinel/context_harm/selection.py`, `tests/test_context_harm_selection.py`.

**Interfaces:** `select_candidates(candidates: tuple[CandidateRef,...], scores: dict[str,ScoreBatch], labels: dict[str,int]) -> dict[str,Selection]`; `fit_calibration(selection: Selection, scores: ScoreBatch, labels: dict[str,int], components: dict[str,str]) -> CalibrationRecord`; `apply_calibration(calibration: CalibrationRecord, scores: tuple[float,...]) -> tuple[float,...]|None`.

- [ ] Write failing tests for ties, all-negative admissible decisions, branch case-ID mismatch, class-sparse grouped folds, tied predictors, invalid/nonpositive slope and worsened out-of-fold calibration:

```python
self.assertLessEqual(chosen.validation_report['fpr'], 0.05)
self.assertEqual(unusable.validation_report['recall'], 0.0)
self.assertEqual(bad_calibration.status, 'unavailable')
self.assertIsNone(apply_calibration(bad_calibration, (0.2, 0.8)))
```

- [ ] Run `test_context_harm_selection.py`; expect missing selection/calibration.
- [ ] Implement spec tie-breaking explicitly; reuse existing `point_metrics` for non-calibration metrics, without modifying its historical implementation. Raw scores are probabilities; sigmoid fits use their clipped logits (`epsilon=1e-6`), fixed logistic `C=1e6`, `lbfgs`, 1,000 iterations, seed 42. Allocate three whole-component calibration folds once; measure out-of-fold Brier and five equal-frequency ECE bins with stable tied-score ordering. Reject unsupported/invalid/nonpositive-slope fits or worsened Brier, otherwise refit on all calibration data. Never use this diagnostic to change the raw decision threshold or candidate grid.
- [ ] Run this scope plus existing metric/calibration scopes; expect pass with unchanged existing calibration contracts.
- [ ] Commit as `feat: select and calibrate harm models without test leakage`.

### Task 7: Pinned encoder environment and bounded CUDA pilot

**Files:** Create `requirements-harm-neural.in`, `requirements-harm-neural-win-py311.lock.txt`, `sentinel/context_harm/neural_sources.py`, initial `neural.py`, `tests/test_context_harm_neural_sources.py`, `tests/test_context_harm_neural_pilot.py`; consume [planning package catalog](../../../output/research/context-harm-neural-package-catalog.json).

**Interfaces:** `prepare_neural_sources(root: Path, catalog: Path) -> dict`; `probe_neural_runtime(python: Path, output: Path) -> dict`; `token_compatible_cases(rows: tuple[HarmCase,...], tokenizer_dir: Path) -> tuple[tuple[HarmCase,...],dict]`; `run_neural_pilot(study: FrozenStudy, python: Path, sources: dict, output: Path) -> dict`.

- [ ] Write failing tests for changed wheel/model bytes, unpinned revision, download size/deadline/budget, a tokenizer requiring an unexpected special-token count and a CUDA forward/backward/optimizer failure:

```python
self.assertEqual(coverage_252['supported'], True)
self.assertEqual(coverage_253['supported'], False)
self.assertEqual(pilot_failure['status'], 'neural_unavailable')
self.assertFalse(pilot_failure['may_fit_full_candidate'])
```

- [ ] Run both scopes in the CPU environment with controlled worker outcomes; expect missing interfaces, never a skip because Torch is absent.
- [ ] Implement the 26-package exact lock from catalog SHA-256 `778a7d964e97d5a1aa895a8bd5607e6b462f26429a286369d1a126b109b58f0e`. Core pins are `torch==2.8.0+cu128`, `transformers==4.57.6`, `safetensors==0.6.2`, `tokenizers==0.22.2`, `huggingface-hub==0.36.0`; every runtime/transitive wheel filename/hash is specified in the catalog. Metadata confirms Python/dependency constraints, not installed compatibility. Torch's body size is unverified: enforce a 4 GiB cumulative received/reserved wheel-body budget, ten-minute body deadline and at least 12 GiB free disk before acquisition; record actual sizes. Provide offline installation with `--no-index --require-hashes` into `.venv-harm-neural/`, exact runtime-package inventory verification and `pip check` for Task 12's real preflight; record bootstrap pip separately as the installer. No latest aliases, extras, driver installation or changes to CPU locks. [Official PyTorch release installation](https://pytorch.org/get-started/previous-versions/), [Transformers release](https://pypi.org/project/transformers/4.57.6/).
- [ ] Implement the pinned seven-file DistilBERT allowlist `model.safetensors, config.json, tokenizer.json, tokenizer_config.json, vocab.txt, LICENSE, README.md`. Obtain expected revision/blob metadata through the official API, verify SHA-256/LFS or Git blob identity as applicable, and record acquired SHA-256 hashes before tokenization. Use only local files with remote code disabled. Run CUDA smoke, then a balanced seed-42 training-only 32-case/20-step pilot under Task 5 supervision. Include model load, backward and optimizer memory, finite-loss checks, throughput and a conservative three-epoch forecast. Any source/runtime/resource gate failure produces a durable `neural_unavailable` report while CPU work proceeds.
- [ ] Run both scopes; run the real preflight/pilot only after the cohort is frozen during Task 12. Expect passing software tests and no unsupported runtime-success claim.
- [ ] Commit as `feat: pin and gate compact encoder training on laptop resources`.

### Task 8: Comparable compact-encoder candidates

**Files:** Extend `sentinel/context_harm/neural.py`, `worker.py`; create `tests/test_context_harm_neural.py`.

**Interfaces:** `fit_neural_candidates(study: FrozenStudy, pilot: dict, python: Path, output: Path, settings: dict) -> tuple[CandidateRef,...]`; extend Task 5 `score_candidate` for neural references through the configured separate interpreter. Neural refs bind a common token-compatible cohort manifest, base/tokenizer/runtime hashes and measured fit record.

- [ ] Write failing tests for an unavailable pilot, unequal target/context cases, lost target tokens, context-token trimming, changed pilot/source binding and checkpoint selection using test data:

```python
self.assertEqual(target_ids, contextual_ids)
self.assertEqual(encoded_target_tokens, complete_target_tokens)
self.assertGreaterEqual(used_context_tokens, 1)
self.assertEqual(candidate.fit_record['selection_partition'], 'validation')
```

- [ ] Run `test_context_harm_neural.py`; expect missing fit path.
- [ ] Implement a direct PyTorch loop without Trainer/Accelerate: unweighted `torch.nn.CrossEntropyLoss` over two-class logits, AdamW default betas/epsilon, constant learning rate, clip norm 1.0, microbatch two and accumulation four. Reset Python/NumPy/Torch seeds before each model/head initialization; shuffle with seed 42. Fit two learning rates per branch, at most three epochs each, and compare each epoch checkpoint using Task 6's validation rule. Retain only the best checkpoint per configuration in private staging, not every epoch or optimizer snapshot. Use AMP/GradScaler when supported and discard nonfinite steps as candidate failure. Preserve the whole compatible target and most recent context token suffix; publish coverage/window omissions. Apply production class/component gates to the neural compatible subsets; their failure disables neural participation only. Fix candidate participation before final access. CPU configurations remain selected on full CPU validation, not retuned for the neural subset.
- [ ] Run this scope and CPU/selection scopes; expect pass with identical case IDs within each comparison and explicit no-GPU outcomes.
- [ ] Commit as `feat: compare bounded target and context encoder candidates`.

### Task 9: Checked artifacts, final access and reproduction CLI

**Files:** Create `sentinel/context_harm/artifacts.py`, `access.py`, `evaluation.py`, `cli.py`, `tests/test_context_harm_artifacts.py`, `tests/test_context_harm_access.py`, `tests/test_context_harm_evaluation.py`, `tests/test_context_harm_cli.py`.

**Interfaces:** `export_artifact(selections: dict[str,Selection], calibrators: dict[str,CalibrationRecord], study: FrozenStudy, output: Path) -> dict`; `inspect_artifact(path: Path, *, research: bool = False) -> dict`; `begin_final_access(study: FrozenStudy, identity: dict) -> dict`; `load_final_test(study: FrozenStudy, receipt: dict) -> tuple[HarmCase,...]`; `finish_final_access(study: FrozenStudy, receipt: dict, report_hash: str) -> None`; `evaluate_final(study: FrozenStudy, artifact: Path, output: Path) -> dict`.

- [ ] Write failing tests for altered code/lock/tokenizer/weights, unsupported bundle, deserialization before checks, interrupted identical resume, two different concurrent final callers, changed identity and completed rescore:

```python
self.assertTrue(receipt_was_durable_before_test_load)
self.assertEqual(report['bootstrap']['replicates'], 1000)
self.assertEqual(report['comparison_case_hashes']['target'], report['comparison_case_hashes']['context'])
self.assertEqual(dominant_component_report['interval_status'], 'unavailable')
```

- [ ] Run the four scopes; expect missing artifact/receipt/evaluator/CLI.
- [ ] Implement immutable schema-1 `research_only` bundles with checked CPU joblib members and neural Safetensors members. Fingerprint all harm research/scoring code, imported support implementation, production config, both relevant locks, source/protocol and optional base/tokenizer files before loading locally trusted artifacts. CLI live loading refuses schema-1 research artifacts; offline research inspection is explicit. Hashes do not authenticate a downloaded artifact.
- [ ] Implement exclusive durable final reservation with full identities from the spec. Include declared diagnostic cohorts and token-compatible coverage in the one scoring operation. Report the existing fixed `ABUSE_RE` baseline separately on target text and target plus the same context window, threshold 0.5 on its boolean scores; do not tune the phrase list. Produce full CPU target/context results, CPU/neural comparison on the identical compatible subset when available, paired deltas and aggregate subgroups. Use connected test thread/known-author/duplicate components and report dominant/sparse intervals honestly. Derive research subgroup counts and calibration diagnostics without modifying selections. Public JSON/card contain no case IDs, texts, usernames or prediction vectors.
- [ ] Implement CLI commands `source,audit,freeze,train-cpu,neural-pilot,train-neural,pack,evaluate,predict,challenge-init,challenge-prepare,challenge-finalize,challenge-audit`; standard options are `--root`, model stages `--models`, public evaluation `--output`, neural stages `--neural-python`, and offline prediction `--artifact --input-json --research`. Each stage validates preceding receipts, refuses output overwrite and creates a truthful unavailable record on failed gates; no criteria/seed/grid overrides in production. `train-*` runs fitting, validation selection and separate calibration; no final test access. `pack` locks neural participation before evaluation.
- [ ] Run the four scopes and old artifact/receipt/CLI scopes; expect pass and unchanged old study receipts.
- [ ] Commit as `feat: bind harm research artifacts and one-time final evaluation`.

### Task 10: Optional API and exact assessment saving

**Files:** Create `sentinel/context_harm/service.py`, `sentinel/optional_work.py`, `sentinel/assessment_receipts.py`, `tests/test_context_harm_service.py`, `tests/test_assessment_receipts.py`; modify `sentinel/analysis.py`, `server.py`, `tests/test_analysis.py`, `tests/test_server.py`, `tests/test_storage.py`.

**Interfaces:** `HarmService(artifact_path: Path|None, neural_python: Path|None = None)` exposes `health() -> dict` and `assess(request: ConversationInput) -> dict`; `OptionalModelBudget.run(kind: str, operation: Callable, unavailable: Callable) -> object` grants a nonblocking reservation; `SnapshotSigner(secret: bytes, ttl_seconds: int = 900, clock: Callable[[],float] = time.time)` exposes `issue(submitted: dict, result: dict) -> str` and `verify(receipt: str, submitted: dict, result: dict) -> None`. Extend `analyze(..., harm_model=None, optional_budget=None)` and `create_server(..., harm_model_path=None, harm_neural_python=None)` without removing old parameters. The optional `harm_assessment` fields are `schema_version=1`, `task_id=english_directed_abuse`, `state`, `category`, `branch`, `target_id`, `coverage`, `evidence`, `unavailable_checks`, `uncertainty`, `action`, `model_version`; optional `calibrated_probability` and explicitly labelled `model_contributions` appear only when supported. States/categories follow the approved spec.

- [ ] Write failing tests for structured-only analysis, malformed turns, declared non-English, missing/research/changed artifact, busy reservation, timeout cleanup, probability suppression, and later messages excluded from target harm observations. Test saving a valid result after the configured model has changed:

```python
self.assertEqual(saved['result'], originally_reviewed_result)
self.assertEqual(inference_calls_during_receipt_save, 0)
self.assertEqual(unavailable['category'], 'not_assessed')
self.assertNotIn('raw target text', captured_server_logs)
```

Also pin changed input/result, expiry, process restart and absent receipt rejection when a client supplies a result.
- [ ] Run these scopes and existing server/analysis/storage tests; expect failures at the new contract boundaries.
- [ ] Implement lightweight request parsing before deriving the selected message for existing fraud/rule checks. Structured harm observations use the target and verified preceding context; extra legacy flat context cannot become learned structure or introduce future turns. The server instantiates a lightweight harm service even without a configured artifact; absence yields a versioned unavailable result. Add `--harm-model`, `--harm-neural-python` and matching `SENTINEL_HARM_MODEL_PATH`, `SENTINEL_HARM_NEURAL_PYTHON` configuration. All configured optional model operations use the same budget; an exclusive 8 GiB reservation serializes them without queuing. Harm inference runs in a bounded fresh worker, clears private memory on exit and never persists unsaved content.
- [ ] Implement stateless HMAC-SHA256 receipts bound to canonical submitted input/result, issue time and a per-server random secret. Canonical JSON uses sorted keys, compact separators, UTF-8 and `allow_nan=False`; reject future issue times and use constant-time MAC comparison. `/api/analyze` attaches `assessment_receipt` beside the result fields; clients strip that field from the result and submit `{input,result,assessment_receipt}` to `/api/cases`. Verify before storing and never reanalyse this flow. Expired/restarted receipts return a clear recheck error; input-only legacy saves remain compatible and explicitly create a new assessment. Never accept an unsigned client result. Health reports only state/version/reasons, not paths or payloads.
- [ ] Run the listed scopes plus paired/URL integration and service tests; expect pass, no old artifact-identity changes and no rule failure from optional inference.
- [ ] Commit as `feat: assess ordered conversations and save reviewed snapshots`.

### Task 11: Turn editor, coverage and client snapshots

**Files:** Create `web/conversation.js`, `tests/conversation_editor.test.mjs`; modify `web/app.js`, `index.html`, `styles.css`, `extension/popup.js`, `sentinel/server.py` static mapping, `tests/web_client.test.mjs`, `tests/extension_popup.test.mjs`.

**Interfaces:** A plain browser script exposes `globalThis.SentinelConversation.createEditor(rootElement, onChange)` returning `{read(), populate(input), clear()}`. `read()` returns the structured request fields or `{}` for legacy mode. User edits call `onChange`; `populate`/`clear` batch their programmatic updates without generating user-edit callbacks. Load it before `app.js`; Node fixtures evaluate both real scripts in the same controlled DOM context. No new frontend package.

- [ ] Write failing client tests using the actual scripts: add/remove/reorder turns, choose target/reply, clear/reopen structured cases, selected message synchronization, missing context and unavailable model. Assert safe rendering and exact saved snapshots:

```javascript
assert.deepEqual(saved.input.conversation_turns, analyzedTurns);
assert.deepEqual(saved.result, reviewedResult);
assert.equal(saved.assessment_receipt, reviewedReceipt);
assert.equal(renderedExecutableMarkup, false);
```

Extend every existing late-analysis/save/clear/open race to structured snapshots and an expired receipt response. An older server response without a receipt remains readable, but the updated client disables saving and asks for a service restart instead of submitting an unsigned result.
- [ ] Run all three Node scopes; expect failures for absent editor/receipt handling, while retaining the previous 14 checks.
- [ ] Implement accessible add/remove and move-up/down controls, local speaker labels, linear/reply selection, target radio selection and explicit context coverage. Generate opaque IDs; mirror the chosen target into a readonly message field in structured mode and omit flat legacy conversation from that submission. Reject reorder/delete operations that would leave an invalid parent/target until the user repairs the relationship; preserve valid editor data instead of inventing a parent. Use text nodes/textContent for all submitted/evidence data. Label observed phrases, learned category, model contribution, missing checks and English assumption distinctly. Show no numerical probability when absent.
- [ ] Update web and extension state to retain the exact analyzed input, result and receipt together under the existing version/race protections. A user turn/target edit increments the analysis version, hides the old result and disables saving until checked again. Never combine a newer editor value with an older result or token. The extension continues target-only, explicit user checks and its existing permissions. Add the static script route and narrow-screen CSS without redesigning the entire dashboard.
- [ ] Run client scopes and server static-route tests; expect pass and no skipped race checks.
- [ ] Commit as `feat: review ordered conversation evidence in the Sentinel app`.

### Task 12: Real study, reproduction and final independent review

**Files:** Create `tests/test_context_harm_workflow.py`, `docs/context-harm-workflow.md`, `docs/context-harm-delivery-record.md`, `docs/context-harm-web-smoke-test.md`; modify `README.md`, `docs/next-steps.md`; produce aggregate `output/research/context-harm-v1/` records only when their stages actually run. Keep source, rows, predictions, challenge and models ignored locally.

**Interfaces:** Use the Task 9 CLI and Task 10 server configuration as documented; no new experimental API, thresholds or datasets are introduced in this task.

- [ ] Write a failing synthetic end-to-end test using explicit fixture provenance: admission/context reconstruction, challenge pending, group freeze, CPU fit/selection/calibration, artifact checks, final reservation, score, repeat denial and optional API unavailable. Assert identical comparison cohorts, no raw text in public outputs and old lock/artifact/intake hashes unchanged. A separate failure path exercises real production gates without lowering them.
- [ ] Run `test_context_harm_workflow.py`; expect a concrete integration failure before completing any missing wiring. Repair only the wiring required by the approved contracts, then rerun the scope to pass.
- [ ] Run real `challenge-init`, `source`, `audit` and `freeze`; review the codebook/provenance and retained cohort counts before proceeding. Failed gates stop model fitting and record unavailable reasons while software delivery continues. Successful gates permit `train-cpu`, real pinned neural preflight/pilot and conditional `train-neural`. Compare recorded fit/runtime/calibration/coverage outcomes and pack the immutable research bundle; the final test remains unscored at this point.
- [ ] Run the full Python and three Node suites once on the complete code, with zero skips. Verify in a browser against an isolated test database: keyboard target/reply editing, future-turn exclusion, safe text display, unavailable learned result, analyze/save/reopen with exact turns/result/version, export/deletion, offline recovery, late replies and narrow layout. Record actual download/deletion evidence; keep Chrome toolbar/context-menu checks deferred unless genuinely performed. Retest only when new changes/failures justify it.
- [ ] Request the user's already selected one independent whole-branch review of the complete implementation, protocol, development/pilot records and final-evaluation code. Reproduce/fix important findings and verify affected/full scopes as needed. Refresh unscored artifacts if their implementation binding changed; no final test has yet been consumed. This is one final review cycle, not per-task reviewer dispatch.
- [ ] After blocking findings are resolved, run `evaluate` once with the exact packed bundle. Write aggregate comparison/model card, calibration/resource/coverage limits and challenge/live-release pending status. If evaluation is interrupted, resume only the identical reserved identity; never change code/settings and rescore this test. Have the same final reviewer check these delivery records as the closing part of that review cycle. A discovered issue requiring a different scoring implementation needs a new held-out version or an explicit unavailable result, not silent reuse.
- [ ] Verify clean-clone reproduction by acquiring checksum-pinned sources and using the documented exact CPU/neural locks; reuse the frozen artifact for a hash-verified report check, never rescore the completed final test. Document CPU-required and neural-optional commands, expected honest failure outcomes and deferred human challenge work. Recheck protected hashes and Git staging so no private data enters the commit.
- [ ] Commit the delivery records and aggregate outputs as `docs: record contextual-harm evaluation and reproducible workflow`; use the finishing-branch skill with the user's standing preference for appropriate integration. Do not activate a learned live warning as part of merging this research milestone.

## Acceptance and handoff

Every source/feature/split/model/receipt/API/client requirement above maps to a task and a substantive check. Successful delivery means reproducible software, measured CPU research when its gates pass, a truthful conditional encoder outcome, preserved old studies, exact case snapshots and an empty or genuinely human-reviewed challenge cohort. It does not require inventing challenge cases, claiming a context gain or activating a research-only model.

After plan review, execute inline using `superpowers:executing-plans`, following the user's retained preference and one final independent reviewer. Dependencies, feature worktree creation, product changes, fitting and final scoring are execution work and have not been performed by preparing this plan.
