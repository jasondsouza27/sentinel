# Sentinel context-harm v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved, reproducible CAD-based v2 study using supported whole-component allocation and frozen calibration folds, with one protected-test history across study versions.

**Architecture:** Reuse the existing context-harm source, conversation, model and application primitives. Add bounded count allocation, immutable v2 protocol records and a shared holdout registry behind explicit version dispatch. Keep training and final scoring separate, with one independent whole-branch review before official real-study admission/freezing and a closing check of its research records.

**Tech Stack:** Windows CPython 3.11.17; existing 17 CPU/data pins including NumPy 2.4.6 and SciPy 1.17.1/bundled HiGHS; unittest; existing native Windows worker supervision; optional unchanged 26-wheel encoder environment; existing Node client tests.

**Spec:** [Approved context-harm v2 design](../specs/2026-10-18-sentinel-context-harm-v2-design.md). Read it together with this plan; its source/label/context/model/evaluation requirements are inherited.

Date: 2026-10-18. Status: **specification approved; implementation plan awaiting user review**. Execution choice already supplied: implement here using `superpowers:executing-plans`, with one independent final review. This is a plan, not evidence that the allocator, trained model or v2 final evaluation exists.

## Global Constraints

- Protocol ID `cad-context-v2-constrained`; study/bundle schema 2; base source/model settings remain schema 1 and unchanged. Missing protocol flags retain v1 CLI defaults; explicit v2 never falls back to v1.
- Preserve CAD v1.1 parser/labels, four-ancestor context window, 10,000 target / 20,000 combined character caps, known-author/context/duplicate ownership, protected test and empty challenge reservation.
- Training: at least 200 per class. Validation/calibration: at least 30 per class and ten components each. Each calibration held-out fold: at least five per class; its fitting portion: at least twenty. Test: at least 100 per class and thirty retained threads. No development component over 70%.
- Five bins in order: train, validation, calibration_fold_0, calibration_fold_1, calibration_fold_2. Component order: largest first with one `random.Random(42)` shuffle of sorted IDs for ties. Balancing uses the specification's exact rational `B_outer`, `B_fold`, then bin index; target fractions are 70/15/15, not guaranteed proportions.
- Allocation limits: 10,000 cases, 512 components, 256 KiB count-only input, 64 KiB worker output, `1 + 5*component_count` calls, 90-second shared internal deadline; each solve at most 20 seconds / 10,000 nodes, `mip_rel_gap=0`. Owned parent deadline 120 seconds, 2 GiB process-tree RSS, one native thread; `threads=1`, `parallel=False`, `random_seed=42`, presolve on.
- Keep the shared TrainingAdmission mutex. Lock order: training admission, registry, study. No alternate seed, weakened gate, incumbent fallback, automatic retry after completed failure, changed model grid or final-test tuning.
- CPU: twelve target/context candidates, `C=0.5,1.0,2.0` crossed with unweighted/balanced classes, sparse TF-IDF/logistic regression; four native threads, 8 GiB RSS, fifteen minutes per fit. Validation recall under 5% FPR; then precision, lower FPR, config ID.
- Calibration: three frozen component folds; preserve sigmoid/positive-slope/convergence/variation and non-worsening out-of-fold Brier gates plus five-bin ECE. Coverage loss never causes a reallocation.
- Optional encoder: retain the exact 26-wheel lock/catalog and DistilBERT revision `12040accade4e8a0f71eabdb258fecc2e7e948be`. Pilot: at most 32 training examples, twenty optimizer steps, sequence 256, target at most 252 tokens, microbatch two, accumulation four, 3.2 GiB GPU allocated/reserved, 8 GiB RSS, ten minutes; thirty minutes per full candidate. Preserve source budgets and actual-worker attestation.
- Private primary paths outside OneDrive: `data/context-harm-v2/`, `models/context-harm-v2/`, `data/context-harm-holdouts/`; successful study child `v2/`. Existing v1 data/models/reports, nineteen baseline Git contents, CPU locks, neural lock/catalog and empty paired intake are protected.
- Public v2 aggregates only under `output/research/context-harm-v2/`. No source text, case/author IDs, memberships, predictions or weights in Git. V2 artifacts remain `research_only`; default learned warnings stay unavailable.

| Production admission identity | Exact expected value |
| --- | --- |
| Base config canonical SHA | `d7ff7bdefc6736c930ed0d2226f417c49ea451dc1995747e7eedc499489ffece` |
| Archive SHA | `69f5ed2fd7b40de21fe54c620549f0be6c34eaf55b8de06ff481cabe3e9476d2` |
| TSV SHA | `7287d635e1d35ae1e64779ffe107df16f493c6ccc4084c4497bbf3f56ae0f349` |
| Codebook SHA | `3d9489fc77b25b92c48f91192c0a52d561413cf260774935aa6a7959131612d4` |
| Development cases SHA | `c1f4885298d619ae63e9f28a93cb6a11be94977c0fa3eb0c88051e28ea196b87` |
| Primary test cases SHA | `395a0c5059a974b96d0b9f2d9ef58bffe476c6a6365aa2e20bddce245f23332d` |
| Test diagnostics SHA | `56d5b117ad28c2ddf5fae3cb53d949f82e739dbc3009fc94b522ed39193a3752` |
| Component count vectors SHA | `60f4121621cc7758181ae7f2d35e4586ddc837b8eb1da98c56662e876818e935` |
| Published-test ownership SHA | `8a23d2f612c85b4d8972d6b9deee5c3de2e7ef5593290609bb5c7fb88aa2e43a` |

The fixed pool has 1,624 primary development cases (1,356 label-0 / 268 positive), 248 threads, 66 unknown target authors and 135 components; largest component 571 cases. Preserve 342 published test threads, 3,315 primary test cases and 1,949 diagnostics. Case/vector/ownership hashing uses exactly the serializer and key conventions in the specification.

## Review Focus

1. Boolean, negative, nonfinite or inconsistent count values and hidden payload fields must be rejected before native solving (Tasks 3–4).
2. Windows path case/junction aliases, a registry copied to a new directory, or an alias resolving inside OneDrive must not create different protected ownership (Task 2).
3. Budget exhaustion after rejected bins must abort even if a later bin has a feasible witness; it must not turn a timeout into an allocation preference (Tasks 3–4).
4. Neural coverage may leave at least thirty cases per class overall while removing one fold's positives; retain the fold map and report unavailable calibration (Task 7).
5. A crash after global reservation or report publication, followed by a copied-root resume, must repair only the identical operation and never score again (Task 9).

## Execution context and file map

Create/reuse isolation with `superpowers:using-git-worktrees` only after plan approval. Inspect app attachments and Git worktrees first; start from current `codex/sentinel`, using branch `codex/context-harm-v2` if a new branch is needed. Do not move the Windows desktop or use the stale OneDrive checkout.

All file paths below are checkout-relative. Run tests from the chosen checkout, while using the existing primary interpreter:

```powershell
$SentinelPrimary = 'C:\Users\Jason Dsouza\Desktop\major project'
$SentinelPython = Join-Path $SentinelPrimary '.venv-url-v2-check\Scripts\python.exe'
$SentinelData = Join-Path $SentinelPrimary 'data\context-harm-v2'
$SentinelModels = Join-Path $SentinelPrimary 'models\context-harm-v2'
$SentinelRegistry = Join-Path $SentinelPrimary 'data\context-harm-holdouts'
```

Keep real data, models, the registry and the optional `.venv-harm-neural` in the primary project, even when code runs from a worktree. Capture an initial protected-file byte/Git-content manifest in a task-private temporary directory before creating new study records; retain it through delivery.

| New file(s) | Responsibility |
| --- | --- |
| `v2_contracts.py`, `v2_config.py` | Immutable count/policy/registry contracts; strict protocol/config identity |
| `holdouts.py` | Canonical ownership, adoption, active-study claim and monotonic shared history |
| `allocation.py`, `allocation_solver.py` | Exact balancing/order/witness checks; binary feasibility oracle |
| `allocation_runtime.py` | Owned count worker, shared admission and bounded result validation |
| `v2_source.py`, `protocol_v2.py` | Verified v2 admission/audit; immutable publication/version-specific verification |
| `folds.py` | Persisted fold membership, restriction and integrity checks |
| `final_v2.py` | One owned final session and registry/receipt/report recovery |
| `cli_v2.py` | Explicit v2 stage orchestration and safe public summaries |

These new Python files live in `sentinel/context_harm/`. Modify existing `protocol.py`, `worker.py`, `selection.py`, `cpu.py`, `neural.py`, `neural_sources.py`, `artifacts.py`, `access.py`, `evaluation.py`, `cli.py` and `service.py` only at their version/admission/provenance boundaries; retain v1 algorithms. Add `configs/context-harm-v2.json`, matching v2 tests/fixtures and the three private ignore patterns. No web/extension feature files need modification.

## Shared interface conventions

- Existing `HarmCriteria`, `HarmCase`, `SourceRelease`, `FrozenStudy`, `WorkerRecord`, `ScoreBatch`, `Selection` and `CalibrationRecord` remain the shared research types.
- Define frozen `CountVector(component_id: str, rows: int, label_0: int, label_1: int)`, `AllocationPolicy(criteria: HarmCriteria, fold_held_per_class: int, fold_fit_per_class: int, seed: int, internal_seconds: int, solve_seconds: int, node_limit: int, max_cases: int, max_components: int)` and `HoldoutRef(root: Path, ownership_id: str, registry_uuid: str, descriptor_sha256: str)` in `v2_contracts.py`.
- Count vectors are lexicographically ordered by component ID at the boundary. `bins` align with that order; `rejected_masks` align with processing order. Each mask marks only bins proven infeasible before the chosen bin. Oracle results use `status` in `feasible/infeasible/limit/invalid` and a bin-major, length `5*G` binary `witness` for feasible results.
- Allocation records use schema 2, protocol ID, status `ready/unavailable`, nullable reason, input hash, compact bins/masks, call/status summaries and solver/runtime identities. Unavailable records contain no successful partial assignment. Full decision scores are reconstructed privately from vectors and masks. Serialize each reduced rational as `[numerator, denominator]` with positive denominator; trace rows use `component_id`, `candidates`, `chosen_bin` and `rejected_mask`.
- Record identities: `assignment_sha256` hashes the canonical component-to-bin-index dictionary; `allocation_sha256` hashes the complete immutable allocation receipt; `fold_map_sha256` hashes the full canonical fold record. A covered calibration map has a separate `covered_fold_map_sha256`; it never replaces the full identity. Replay compares assignment and reconstructed fold identities using the original allocation receipt hash, not volatile elapsed-time receipts. Member manifests continue to hash actual file bytes.
- Frozen study bindings retain legacy `settings` and `config_sha256` for the unchanged base config; add `v2_config_sha256`, `protocol_id`, `assignment_sha256`, `allocation_sha256`, `fold_map_sha256` and serialized `holdout_ref`. This preserves existing model-setting readers.
- V2 config keys are `schema_version`, `protocol_id`, `base_config_sha256`, `expected`, `allocation`. `expected` uses `archive_sha256`, `member_sha256`, `codebook_sha256`, `case_hashes` (keys `development/test/diagnostics`), `count_vectors_sha256`, `ownership_sha256`, and `counts` (the named pool/test aggregates above). `allocation` uses `criteria` (the existing HarmCriteria field names), `fold_held_per_class`, `fold_fit_per_class`, `seed`, `internal_seconds`, `solve_seconds`, `node_limit`, `max_cases`, `max_components`, `request_bytes`, `result_bytes`, `worker_seconds`, `worker_rss_bytes`, `native_threads` and `solver_options`, with the exact global values. Loader checks one literal canonical production config hash; no CLI support-limit overrides.
- Synthetic policies and provenance exist only in internal test fixtures. Production CLI/config/source admission rejects them, and a real CAD archive/ownership hash can never be marked synthetic to bypass checks.

---

### Task 1: Version contracts, immutable config and private-path defaults

**Files:** Create `sentinel/context_harm/v2_contracts.py`, `v2_config.py`, `configs/context-harm-v2.json`, `tests/test_context_harm_v2_config.py`, `tests/context_harm_v2_fixtures.py`; modify `.gitignore`.

**Interfaces:** Produce `load_v2_config(path: Path | None = None) -> dict`, `production_policy() -> AllocationPolicy`, `protocol_id(binding: dict) -> str`, plus the three types above. Fixtures initially expose `small_policy() -> AllocationPolicy` and `feasible_counts() -> tuple[CountVector,...]`.

- [ ] **Write failing tests** `test_production_values_and_mutated_config_refusal`, `test_unknown_mixed_protocol_refusal`, `test_private_defaults_are_ignored`. Pin these assertions:
```python
self.assertEqual(production_policy().criteria.train_per_class, 200)
self.assertEqual(production_policy().fold_held_per_class, 5)
self.assertEqual(production_policy().internal_seconds, 90)
self.assertEqual(protocol_id({'schema_version': 2, 'protocol_id': 'cad-context-v2-constrained'}), 'cad-context-v2-constrained')
```
- [ ] **Run RED:** `& $SentinelPython -B -m unittest discover -s tests -p 'test_context_harm_v2_config.py' -v`; expect missing v2 contracts/config.
- [ ] **Implement** the interfaces and literal config/hash with the exact global values, strict key/type checks and explicit v1/v2 dispatch. Add only the three approved ignore roots. `small_policy()` uses `HarmCriteria(2,1,3,1,1,1,.7)`, held minimum 1, fit minimum 2; `feasible_counts()` returns six distinct components `c0` through `c5`, each `rows=2,label_0=1,label_1=1`. It is explicitly invented and is not accepted by production loading.
- [ ] **Run GREEN:** the same command passes; verify existing CPU/neural locks and base config bytes are unchanged. Confirm private paths with `git check-ignore` without creating real source/model directories.
- [ ] **Commit** only these paths: `feat: define versioned contextual harm study contract`.

### Task 2: Shared holdout adoption and monotonic ownership

**Files:** Create `sentinel/context_harm/holdouts.py`, `tests/test_context_harm_holdouts.py`; extend v2 fixtures with `synthetic_holdout(root: Path) -> HoldoutRef`.

**Interfaces:** Consume `HoldoutRef`. Produce `ownership_identity(source: SourceRelease) -> dict`, `adopt_holdout(registry: Path, ownership: dict, predecessor: Path, *, synthetic: bool = False) -> HoldoutRef`, `validate_ref(ref: HoldoutRef) -> dict`, `ref_record(ref: HoldoutRef) -> dict`, `ref_from_record(record: dict) -> HoldoutRef`, `locked_holdout(ref: HoldoutRef) -> ContextManager[HoldoutLease]`, `assert_permitted(ref: HoldoutRef, operation: str, study_sha256: str | None = None) -> None`. `HoldoutLease` exposes a detached `record` property and `claim_study(study_sha256: str, study_path: Path) -> dict`, `reserve_final(identity: dict) -> dict`, `complete_final(identity_sha256: str, report_sha256: str) -> None`; methods require an active lease.

- [ ] **Write failing tests** for adoption with an existing predecessor final receipt, swapped UUID/hash, conflicting active study, missing registry, Windows case/junction aliases and alias-to-OneDrive. Test only isolated temporary paths and synthetic ownership:
```python
with locked_holdout(ref) as lease:
    lease.claim_study('a'*64, study_path)
with self.assertRaisesRegex(HarmError, 'holdout_study_conflict'):
    with locked_holdout(ref) as lease:
        lease.claim_study('b'*64, other_study)
```
- [ ] **Run RED:** `& $SentinelPython -B -m unittest discover -s tests -p 'test_context_harm_holdouts.py' -v`; expect missing registry implementation.
- [ ] **Implement** immutable `ownership.json` plus monotonic `state.json` beneath the canonical registry/ownership directory. Resolve actual Windows targets and normalized case before/after creation; bind the resolved location, UUID, descriptor hash and predecessor proof. State transitions are unscored -> reserved -> complete; active-study claims and final identities cannot be replaced. Use exclusive/atomic writes and nonblocking registry locks. The caller owns TrainingAdmission before mutable fit/final operations; this module never recursively acquires it. `validate_ref` reads immutable ownership without re-entering a mutable-state lock.
- [ ] **Run GREEN:** the same scope passes, including real Windows alias/concurrency tests; creating an alternate registry path cannot satisfy an existing bound reference.
- [ ] **Commit:** `feat: preserve shared contextual harm holdout ownership`.

### Task 3: Exact balancing and a feasibility-preserving count allocator

**Files:** Create `sentinel/context_harm/allocation.py`, `allocation_solver.py`, `tests/test_context_harm_allocation.py`; extend fixtures with `enumerating_oracle(vectors, policy) -> Callable[[dict[str,int],float],dict]`, an independent exhaustive oracle for the six-component problem.

**Interfaces:** Consume count/policy types. Produce `validate_counts(vectors: tuple[CountVector,...], policy: AllocationPolicy) -> None`, `count_vectors_record(vectors) -> dict`, `processing_order(vectors, policy) -> tuple[str,...]`, `score_bins(vectors, policy, prefix: dict[str,int], component_id: str) -> dict[int,tuple[Fraction,Fraction]]`, `rank_bins(vectors, policy, prefix: dict[str,int], component_id: str) -> tuple[int,...]`, `validate_witness(vectors, policy, prefix, witness: list[float]) -> tuple[int,...]`, `allocate_counts(vectors, policy, oracle: Callable[[dict[str,int],float],dict], *, clock: Callable[[],float] = time.monotonic) -> dict`. `allocation_solver.solve_prefix(vectors, policy, prefix, remaining_seconds: float) -> dict` is imported only inside the owned worker.

- [ ] **Write failing tests** for legacy-heuristic failure on a feasible toy pool, integer/rational ties, two different valid completion witnesses, NaN/fractional witnesses, booleans/negative/inconsistent counts, oversized components, true infeasibility and a limit after rejected candidates. Keep limits distinct from proofs:
```python
self.assertEqual(result_a['bins'], result_b['bins'])
self.assertEqual(limited['reason'], 'allocation_limit_reached')
self.assertNotIn('bins', limited)
self.assertEqual(count_vectors_record(feasible_counts())['c0'], [2, 1, 1])
```
- [ ] **Run RED:** `& $SentinelPython -B -m unittest discover -s tests -p 'test_context_harm_allocation.py' -v`; expect missing allocation interfaces.
- [ ] **Implement** the spec's exact `Fraction` ranking, fixed seed/order and complete-prefix validation. The test oracle independently enumerates the small fixture; it does not mirror production MILP code. Build five binary variables per component, constant-zero objective and every class/component/fold constraint; accept only successful verified witnesses and advance only on proven infeasibility. Stop on budget/unknown/numeric failure without a partial bin map. Recompute all final counts using integer arithmetic. The source/text/gold-case fields are not accepted by this boundary.
- [ ] **Run GREEN:** pure allocation scope passes. The actual SciPy/native-option path is exercised under ownership in Task 4, not by an unsupervised product solve here.
- [ ] **Commit:** `feat: allocate supported harm components with feasibility checks`.

### Task 4: Owned solver execution and bounded audit results

**Files:** Create `sentinel/context_harm/allocation_runtime.py`, `tests/test_context_harm_allocation_runtime.py`, `tests/context_harm_v2_workers.py`; modify `sentinel/context_harm/worker.py`.

**Interfaces:** Consume Tasks 1–3. Produce `request_allocation(vectors, policy, *, holdout: HoldoutRef, replay: bool = False, study_sha256: str | None = None) -> dict`, `worker_allocate(request: dict) -> dict`, `verify_allocation_result(vectors, policy, record: dict) -> dict`. Add worker operation `allocate_v2`; existing `await_ownership()` remains before input/ML imports.

- [ ] **Write failing tests** for real owned solver execution, hidden/unknown payload fields, ignored native options, cumulative monotonic limits, timeout cleanup of descendants, output overflow, a feasible incumbent with limited status, busy training admission and crashed-owner recovery. Validate actual backend options and production payload isolation:
```python
self.assertEqual(record['status'], 'ready')
self.assertEqual(record['runtime']['native_threads'], 1)
self.assertLessEqual(record['calls'], 1 + 5*len(vectors))
self.assertTrue(record['runtime']['cleanup_complete'])
```
- [ ] **Run RED:** `& $SentinelPython -B -m unittest discover -s tests -p 'test_context_harm_allocation_runtime.py' -v`; expect missing owned allocator.
- [ ] **Implement** a fresh native worker with 120-second / 2,147,483,648-byte / one-thread limits. Under TrainingAdmission, check registry permission, send only the strict <=256 KiB count payload and enforce the common <=64 KiB output limit. Inside the worker lazily import SciPy, verify the pinned wrapper/backend option path and allow only the exact declared forwarding warning. Record solver/interpreter/package/binary identities. Rebuild rational trace and validate bins/masks/input identity in the supervisor; no verbose per-call or source text output. Replay has read-only registry permission and publishes nothing.
- [ ] **Run GREEN:** this scope plus `test_context_harm_review_safety.py` and `test_context_harm_runtime.py` pass; helpers leave no descendant process or permanent admission lease.
- [ ] **Commit:** `feat: supervise constrained harm allocation workers`.

### Task 5: Verified v2 source admission and bound allocation proposal

**Files:** Create `sentinel/context_harm/v2_source.py`, `tests/test_context_harm_v2_source.py`; extend v2 fixtures with `synthetic_source() -> SourceRelease` and `prepared_fixture(root: Path) -> dict`.

**Interfaces:** Produce `prepare_v2_source(root: Path, *, predecessor: Path, registry: Path) -> dict`, `load_prepared_v2(root: Path) -> dict`, `audit_v2(root: Path) -> dict`. Prepared records expose `source`, `cohort`, `development`, `primary_test`, `diagnostics`, `components`, `holdout` and `binding`; use existing `load_source`, `build_cases`, `_protected_pool`, `connected_components` and `serialize_case` unchanged.

- [ ] **Write failing tests** for every golden identity/aggregate, changed source/codebook/review, nonempty challenge, fake synthetic CAD, cache reuse vs acquisition, predecessor reservation and proposal drift/overwrite. Assert guards run before solving:
```python
with self.assertRaisesRegex(HarmError, 'cohort_identity_changed'):
    load_prepared_v2(changed_root)
allocator.assert_not_called()
self.assertEqual(proposal['protocol_id'], 'cad-context-v2-constrained')
self.assertFalse((root/'v2').exists())
```
- [ ] **Run RED:** `& $SentinelPython -B -m unittest discover -s tests -p 'test_context_harm_v2_source.py' -v`; expect missing v2 admission/audit.
- [ ] **Implement** staged import of only verified source bytes, codebook review and empty challenge files into the new root. If cache is absent, reuse the existing bounded acquirer. Check all case/vector/ownership hashes before registry adoption or solving; preserve predecessor bytes. Bind immutable `admission.json` to configs, source/review/challenge and canonical HoldoutRef. Audit invokes Task 4, writes one checked `allocation-proposal.json` and `runs/audit.json`, reuses identical success, and preserves completed failures. Public summaries whitelist aggregates; no new source labels or challenge contributions are created.
- [ ] **Run GREEN:** admission/source tests pass, including mocked no-network cache reuse and real failure/partial-stage cleanup; no primary study is admitted during these fixture checks.
- [ ] **Commit:** `feat: admit and audit the preserved CAD-v2 cohort`.

### Task 6: Immutable v2 study, fold records and version dispatch

**Files:** Create `sentinel/context_harm/protocol_v2.py`, `folds.py`, `tests/test_context_harm_protocol_v2.py`, `tests/test_context_harm_folds.py`; modify `sentinel/context_harm/protocol.py` and `access.py` execution support-file list.

**Interfaces:** Produce `freeze_v2(root: Path) -> FrozenStudy`, `verify_v2(study: FrozenStudy) -> dict`, `verify_frozen_allocation(study: FrozenStudy) -> dict`; `make_fold_record(calibration, components, bin_by_component, allocation_sha256: str) -> dict`, `validate_fold_record(record, calibration, components, *, allocation_sha256: str) -> dict[str,int]`, `restrict_folds(case_ids: tuple[str,...], full_map: dict[str,int]) -> dict[str,int]`. Existing `verify_study`, `load_development` dispatch strictly; introduce no default v2 promotion.

- [ ] **Write failing tests** for freeze consuming exactly the audited proposal without solving again, altered policy/masks, missing/duplicate/split-component folds, atomic active-study claim/publication recovery, wrong member sets and schema confusion:
```python
solver.assert_not_called()
self.assertEqual(verify_study(study)['schema_version'], 2)
self.assertEqual(set(fold_map), {row.case_id for row in calibration})
self.assertEqual(replayed['assignment_sha256'], binding['assignment_sha256'])
```
- [ ] **Run RED:** run `test_context_harm_protocol_v2.py` and `test_context_harm_folds.py` separately with unittest discovery; expect missing v2 publication/folds.
- [ ] **Implement** the schema-2 member set from the spec, including sorted partition JSONL, allocation receipt and fold map. Recheck admission/proposal/integer constraints, stage every member, then take training -> registry -> study locks to claim the expected manifest and publish atomically. Identical interrupted publication may finish; another expected manifest/root cannot replace it. `verify_study` lazily dispatches to v2, preserving v1's actual allocator/fold semantics and archived-commit reproduction. Bind new code/config/fold identities before consumers deserialize anything. Verification reads only the immutable registry descriptor; it must not re-enter mutable registry locks held by a final session. `verify_frozen_allocation` replays count policy only, compares fixed assignment/fold hashes and never writes a new proposal/claim.
- [ ] **Run GREEN:** both scopes plus existing `test_context_harm_protocol.py`, conversation/text tests pass. Internal synthetic freeze checks explicit invented provenance; public production freeze offers no custom-criteria/synthetic flag.
- [ ] **Commit:** `feat: freeze versioned harm studies with reserved calibration folds`.

### Task 7: Training guards and calibration on frozen folds

**Files:** Modify `sentinel/context_harm/protocol.py`, `selection.py`, `cpu.py`, `neural.py`, `neural_sources.py`, `cli.py`; create `tests/test_context_harm_v2_training.py`, `tests/test_context_harm_v2_calibration.py`.

**Interfaces:** Extend `fit_calibration(selection, scores, labels, components, *, fold_map: dict[str,int] | None = None, fold_record_sha256: str | None = None, protocol: str = 'cad-context-v1-greedy') -> CalibrationRecord`. Extend `prepare_neural_sources(root, catalog, *, study: FrozenStudy | None = None) -> dict` so the original default retains v1 behavior while v2 callers supply a checked ready study. Keep `fit_cpu_candidates`, `score_candidate`, neural candidate APIs and candidate grid signatures unchanged; add protocol/allocation/fold identities to their bound records.

- [ ] **Write failing tests** for a final reservation racing fit admission, schema-2 records using v1 calibrators, fold mutation, insufficient score variation/nonpositive slope/worsened Brier, and compatible coverage that removes all positives in one fold despite >=30 per class overall:
```python
self.assertEqual(calibration.status, 'unavailable')
self.assertEqual(calibration.report['reason'], 'insufficient_grouped_fold_support')
shuffle.assert_not_called()
self.assertEqual(record['fold_map_sha256'], binding['fold_map_sha256'])
```
- [ ] **Run RED:** run the two new scopes; expect absent registry/fold integration. Use a 60-positive/60-negative calibration fixture; remove twenty positives from one declared fold so the aggregate minimum still passes.
- [ ] **Implement** registry checks after acquiring the existing training lease and before each worker/publication, never reacquiring that lease recursively in children. Legacy real CAD operations without shared adoption are refused; synthetic legacy tests keep isolated behavior. V2 callers validate the full map, restrict it to covered cases and pass its original canonical `fold_record_sha256`; record both full and covered-map identities. Never silently shuffle/fallback. Emit schema-2 CPU/neural fit and selection records for v2 studies, with version-aware candidate checking; mark calibration reports with the same protocol/schema even when unavailable. Propagate full/covered fold hashes through every record; schema-1 records cannot be promoted by editing only their study hash. Permit neural acquisition only for the supplied ready, fittable v2 study, preserving exact locks, byte/deadline limits, compatible-case gates and actual-runtime attestation.
- [ ] **Run GREEN:** the new scopes plus existing CPU, selection, neural sources/pilot/neural and shared-admission regressions pass. No real packages/model bodies or real fits are invoked by these fixture tests.
- [ ] **Commit:** `feat: bind harm training and calibration to frozen v2 ownership`.

### Task 8: Research-only schema-2 bundles and provenance

**Files:** Modify `sentinel/context_harm/artifacts.py`, `access.py`, `service.py`; create `tests/test_context_harm_artifacts_v2.py`; extend existing artifact/service tests where necessary.

**Interfaces:** Keep `export_artifact`, `inspect_artifact`, `load_research_artifact`, `predict_research` and `HarmService` signatures. Schema-2 bundle base members add `allocation.json` and `calibration-folds.json`; metadata/selection records expose protocol ID, allocation/fold/v2-config/registry hashes and the checked study identity. Existing schema-1 bundle member rules remain distinct.

- [ ] **Write failing tests** for mixed schema/model/fold records, changed active registry, code/lock/runtime drift, added/missing members, synthetic-for-real candidates and research-only live refusal:
```python
self.assertEqual(metadata['schema_version'], 2)
self.assertEqual(metadata['release_status'], 'research_only')
self.assertNotIn('test.jsonl', manifest['members'])
self.assertEqual(HarmService(bundle).health()['reason'], 'research_only_artifact')
```
- [ ] **Run RED:** `& $SentinelPython -B -m unittest discover -s tests -p 'test_context_harm_artifacts_v2.py' -v`; expect schema-2 refusal until implemented.
- [ ] **Implement** per-version member/metadata validation and transitive proposal/study/fold/model/runtime binding before deserialization. Include new config/code files in execution identity. Preserve local-hash integrity limits, exact training cohort checks, offline `--research` and live-warning refusal. Package no final rows/source text; artifact copy does not change its registry reference.
- [ ] **Run GREEN:** new and existing artifact/service/workflow scopes pass, including valid schema-1 fixtures and explicit unsupported-version rejection.
- [ ] **Commit:** `feat: package checked research-only contextual harm v2 artifacts`.

### Task 9: One final session across registry, local receipt and report

**Files:** Create `sentinel/context_harm/final_v2.py`, `tests/test_context_harm_final_v2.py`; modify `sentinel/context_harm/access.py`, `evaluation.py`; extend concurrency workers/fixtures.

**Interfaces:** Produce `final_session(study: FrozenStudy, identity: dict) -> ContextManager[FinalSession]`, `evaluate_final_v2(study: FrozenStudy, artifact: Path, output: Path) -> dict`, `recover_v2_publication(study: FrozenStudy, identity: dict, output: Path) -> dict | None`, `build_v2_final_identity(study: FrozenStudy, bundle: dict, artifact: Path, output: Path) -> dict`. `FinalSession` exposes detached `receipt`, `load_rows(*, diagnostics: bool = False) -> tuple[HarmCase,...]`, `complete(report_sha256: str) -> None`. `evaluate_final` dispatches to v2; direct v1 access helpers refuse a schema-2 study rather than bypassing the session.

- [ ] **Write failing tests** for fit/final contention, alternate/copied roots/protocols/outputs, runtime drift before reservation, missing/swapped registry, interrupted claim/global reservation/local mirror and report publication. Pin no-rescore recovery:
```python
self.assertEqual(resumed['final_identity_sha256'], first_identity)
score.assert_not_called()  # matching report was already published
with self.assertRaisesRegex(HarmError, 'final_evaluation_already_complete'):
    evaluate_final(study, artifact, output)
```
- [ ] **Run RED:** `& $SentinelPython -B -m unittest discover -s tests -p 'test_context_harm_final_v2.py' -v`; expect missing cross-version final session.
- [ ] **Implement** strict v2 final identity extending existing provenance with protocol/config/allocation/fold/registry bindings. Attest actual candidate runtime before reservation. Hold TrainingAdmission -> registry -> study locks in that order for the final session; nested loaders use the existing session and never reacquire these locks. Persist authoritative reservation before the matching local mirror; require both before predictive row loading. Bind resume to one identical absolute output/study/model/runtime identity. Publish aggregates atomically, complete the registry with report hash, then repair/complete the local receipt. Matching publication recovery verifies bytes without scoring. If the registry is complete but the local mirror is missing/reserved, `recover_v2_publication` repairs only that matching mirror under the same lock order and returns the verified archive; an already complete registry/mirror pair still refuses a new evaluation. Do not change metric/bootstrap/subgroup semantics.
- [ ] **Run GREEN:** new scope plus existing access/evaluation/review-safety tests pass; interrupted cases never load protected scoring rows before matching receipts and never rescore completed publication.
- [ ] **Commit:** `feat: enforce one contextual harm final evaluation across versions`.

### Task 10: Explicit CLI and synthetic end-to-end delivery

**Files:** Create `sentinel/context_harm/cli_v2.py`, `tests/test_context_harm_cli_v2.py`, `tests/test_context_harm_workflow_v2.py`; modify `sentinel/context_harm/cli.py`; extend v2 fixtures with an internal synthetic frozen-study factory.

**Interfaces:** Produce `execute_v2(args: argparse.Namespace) -> dict`, `load_v2_study(root: Path) -> FrozenStudy`, `public_v2_summary(stage: str, record: dict) -> dict`. Add `--protocol` to stage parsers, default v1; v2 source alone accepts `--predecessor-root` and `--holdout-registry`. Add the read-only `verify-allocation` command. Use checked v2 study loading in existing selection/packing helpers; do not duplicate source/model algorithms in the CLI.

- [ ] **Write failing tests**, including `test_stdlib_server_starts_without_ml_imports` using a fresh `python -S` subprocess and disposable database, for missing/unknown/mismatched protocol, mutable registry flags on later stages, existing output, fake synthetic production input, sanitized failures and read-only verification after completion. Exercise the full internal synthetic path through the actual allocator, freeze, twelve CPU candidates, folds, pack, single-use evaluation and unavailable live service:
```python
self.assertEqual(report['comparison_case_hashes']['target'], report['comparison_case_hashes']['context'])
self.assertEqual(cli_result.returncode, 2)  # mismatched protocol
self.assertNotIn('toy-target-', json.dumps(public_summary))
self.assertEqual(before_registry_bytes, after_readonly_registry_bytes)
```
- [ ] **Run RED:** run both new scopes with unittest discovery; expect missing v2 routing/integration.
- [ ] **Implement** explicit v2 stage routing, ready-study gates and one-way failure summaries. `_failure` must not write anything for `verify-allocation`; no training/pilot/setup is triggered by verification or server health. `neural-pilot` consumes only an already prepared, checked separate interpreter; guarded environment setup remains an explicit research-run operation in Task 11 using existing helpers. Public JSON contains aggregates/hashes only. Internal synthetic factories reject real CAD source/ownership hashes; no synthetic CLI bypass flag.
- [ ] **Run GREEN:** the new CLI/workflow scopes including the actual stdlib-only loopback rule-analysis check, then `& $SentinelPython -B -m unittest discover -s tests -v` and `node --test tests/web_client.test.mjs tests/extension_popup.test.mjs tests/conversation_editor.test.mjs`; require zero unexpected skips/failures. Record actual counts, not the old 477/61 as new evidence.
- [ ] **Commit:** `feat: expose the versioned contextual harm v2 workflow`.

### Task 11: Reviewed software, real admission and development-only study

**Files:** Create `docs/context-harm-v2-workflow.md`, `docs/context-harm-v2-delivery-record.md`, aggregate `source-audit.json`, `cohort-audit.json`, `research-status.json`, `neural-pilot.json` under `output/research/context-harm-v2/`. All actual study/model/registry records stay in the three ignored primary roots.

**Interfaces:** Consume the explicit CLI plus existing `prepare_neural_sources(root, catalog, study=study)`, `verify_sources(record)`, `installation_commands(bootstrap_python, environment, wheelhouse, lock)`, runtime-probe/pilot APIs and the checked artifact. Produce a frozen development artifact and final-ready identity, or an honest aggregate unavailable status.

- [ ] **Confirm production guard coverage:** the existing Task 5/10 RED/GREEN tests pin drifted golden hashes, unavailable allocation, missing neural runtime/source and synthetic promotion refusal. Use their recorded full-suite result; add/regress a test only for a new uncovered failure. Never write a real-test-driven fit/scoring assertion.
- [ ] **Request the one independent whole-branch review before creating official v2 source/proposal/registry/study records.** Supply the approved spec/plan, complete code diff, synthetic workflow, full-suite evidence and existing real-source feasibility identities. Reproduce/fix findings with regressions, then freeze the reviewed implementation/config/runtime identity. This ordering permits corrections before an immutable active-study claim exists. Preserve this same review for the closing research-record check; do not start a second whole-branch code-review cycle.
- [ ] **Admit, audit and freeze using the locked interpreter:**
```powershell
& $SentinelPython -B -m sentinel.context_harm.cli source --protocol cad-context-v2-constrained --root $SentinelData --predecessor-root (Join-Path $SentinelPrimary 'data\context-harm') --holdout-registry $SentinelRegistry
& $SentinelPython -B -m sentinel.context_harm.cli audit --protocol cad-context-v2-constrained --root $SentinelData
& $SentinelPython -B -m sentinel.context_harm.cli freeze --protocol cad-context-v2-constrained --root $SentinelData
```
Check each result before the next command. If admission/solver/freeze is unavailable, stop real fitting/scoring, preserve the attempt and continue documentation of that outcome. Never run the commands as a blind batch. A late defect invalidating a frozen study requires withholding its result and a separately reviewed version/migration; do not overwrite its active-study claim or bound hashes.
- [ ] **Reproduce counts in a clean clone before fitting:** create an isolated pinned CPU environment, verify package inventory, reuse checksum-verified source records and the same authoritative registry. Run `verify-allocation --protocol cad-context-v2-constrained --root $SentinelData` from that clone; require identical case/vector/assignment/fold identities and no new claim/receipt. Do not freeze a second official study or describe cached bytes as a second fresh download.
- [ ] **Run the real development-only study when ready:**
```powershell
& $SentinelPython -B -m sentinel.context_harm.cli train-cpu --protocol cad-context-v2-constrained --root $SentinelData --models $SentinelModels
```
Then explicitly attempt conditional encoder setup: call `prepare_neural_sources` with `load_v2_study($SentinelData)` and the unchanged catalog; only a ready result permits executing the existing `installation_commands` argument lists into the primary `.venv-harm-neural`. Verify admitted wheel hashes, exact separate inventory, `pip check` and actual CUDA runtime before the training-only pilot. Retain the existing 4 GiB wheel-body / 512 MiB model-body budgets, disk requirement and acquisition deadlines. Preserve an unrecognized/partial existing environment and record unavailable instead of overwriting it. Only a passing pilot permits `train-neural`; otherwise lock neural_unavailable. Reuse the fixed candidate grid and coverage rules; do not consult test predictions.
- [ ] **Pack and verify:** run `pack --protocol cad-context-v2-constrained --root $SentinelData --models $SentinelModels` only after CPU selection/calibration and neural participation are locked. Confirm registry remains unscored, no final rows were predicted, research-only status and source/coverage/resource/calibration limits. Run all tests again only if code/failures require it; the full preflight from Task 10 remains valid otherwise.
- [ ] **Commit development aggregates/docs** and retain their identities for the same reviewer's closing delivery check in Task 12. No product/config/model/protocol changes based on final outcomes are permitted. Use `research: record supported contextual harm v2 development study`, or an explicit unavailable title matching the actual outcome.

### Task 12: One final result, truthful release records and integration

**Files:** Produce `output/research/context-harm-v2/final/evaluation.json`, `model_card.md`, `manifest.json` only if eligible. Complete root `model-card.md`, `verification.json`, `manifest.json`, the v2 workflow/delivery docs; update `README.md`, `docs/next-steps.md` and this plan's checked status.

**Interfaces:** Consume the reviewed frozen artifact and Task 9 final session. Root public manifest covers aggregate members and optional final members; missing/unavailable stages are represented as such, not invented artifacts.

- [ ] **Verify the review corrections and final-readiness guards** with their focused regressions. Require the recorded full Python/client checks, unchanged protected baseline, matching current code/runtime/artifact/study identities, completed independent code review and locked neural status before any final reservation. Synthetic final tests from Tasks 9–10 are the RED/GREEN evidence for this operation; do not add real-test-driven development assertions.
- [ ] **Run exactly one eligible final operation**, checking its returned identity/state; if the study/artifact is unavailable, skip scoring with an explicit unavailable report:
```powershell
& $SentinelPython -B -m sentinel.context_harm.cli evaluate --protocol cad-context-v2-constrained --root $SentinelData --artifact (Join-Path $SentinelModels 'artifact') --output output/research/context-harm-v2/final
```
Do not change code/config/model/data/thresholds based on these results. Interrupted identical publication may resume under the same bound identity; a completed result is verified as an archive, not rerun.
- [ ] **Complete aggregate records** with actual confusion/coverage/subgroup/calibration/resource metrics, bootstrap interval limitations, source/seed/versions/hashes, the pending human challenge and no live release. If a verified scoring bug invalidates the completed result, preserve/withdraw that claim and require new held-out ownership for corrected scoring; do not repair it by rescoring this test.
- [ ] **Run final verification:** compare protected bytes/Git contents/empty paired intake with the initial manifest, validate every public member hash and relative link, confirm registry completion (or truthful unavailable state), no raw data/weights staged, ignored private roots and default live-warning refusal. Perform a loopback HTTP smoke of rule analysis/signed save/reopen/delete using a disposable database; no unconfirmed Chrome toolbar/context-menu or new usability claim.
- [ ] **Obtain the same reviewer's closing record check**, covering actual final/unavailable state and aggregate integrity, without a new whole-branch code-review cycle. Commit as `research: deliver contextual harm v2 evaluation and limits` with wording matching the measured outcome.
- [ ] **Integrate the reviewed branch into `codex/sentinel` and push under existing authorization.** Verify the same LF-normalized execution identity and bound registry/model paths in the primary checkout; keep all private data outside the worktree. Use the appropriate Superpowers finishing workflow and native worktree cleanup. Do not alter another worktree or delete ignored research data. Report the new metrics only if actually measured, and keep default learned warnings disabled.
## Coverage and handoff

Tasks 1–2 cover version/config/ownership; Tasks 3–4 cover deterministic feasible allocation and native resource controls; Tasks 5–6 cover exact cohorts, immutable proposals/studies and fixed folds; Tasks 7–8 cover training/calibration/encoder/bundle compatibility; Tasks 9–10 cover cross-version final history, CLI and end-to-end verification; Tasks 11–12 cover real outcomes, reproducibility, one independent review, final evaluation and delivery.

Self-review covers spec coverage, type/signature/key consistency, every step's testable result, the five Review Focus tests and proportion to the design. This review corrected full-vs-covered fold identities, stable assignment-vs-runtime receipt comparison, final-mirror recovery and review-before-freeze ordering. No task's passing synthetic results count as a real research finding.

The user has already selected implementation here with one independent final review. After the user reviews and approves this written plan, use `superpowers:executing-plans`; do not ask them to choose an execution method again. Until then, do not create a product worktree, product files/config, a registry, installed environment, new study, fit or final receipt.
