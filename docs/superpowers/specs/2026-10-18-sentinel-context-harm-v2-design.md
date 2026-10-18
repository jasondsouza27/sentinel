# Sentinel: context-harm v2 with constrained CAD allocation

Date: 2026-10-18. Status: **direction approved; written specification awaiting user review**. The user approved the [feasibility investigation](../../context-harm-v2-feasibility-2026-10-18.md) and requested this specification. This document proposes a new study method; it does not report an implemented v2 allocator, a frozen v2 split, trained models or final-test results. The existing choice of inline implementation with one independent final review carries forward.

## Purpose and scope

Complete a real English directed-abuse experiment for Sentinel's year-long engineering project: **does preceding conversation context improve detection compared with the target message alone, on held-out conversations and known authors?** Retain the useful investigation application, task-aligned labels and laptop limits from the [implemented harm design](2026-10-13-sentinel-context-harm-design.md). Here v2 names Sentinel's study version; the dataset stays CAD v1.1. This revision addresses development allocation and supported calibration folds; it does not redesign the application or redefine directed abuse as general toxicity, intent or repeated harassment.

The current CAD-v1 allocation fails its declared support gates. After the established exclusions, the primary development pool contains 1,624 cases, including 268 positives, in 135 connected components. A [counts-only feasibility check](../../../output/research/context-harm-v2-feasibility/feasibility.json) found a whole-component witness with 205 training, 30 validation and 33 calibration positives, and supported calibration folds. That witness neither optimises the fraction targets nor replaces the v1 fold method. It establishes a reason to specify v2, not detector quality or a final split.

Three approaches were considered: expand compatible permissioned data, start a differently labelled contextual benchmark, or constrain the existing CAD development allocation. The user selected the last approach. Preserve the earlier negative/unavailable research outcome and disclose the tight support: the 200/30/30 positive-class minimums consume 260 of the 268 available positives.

## Preserved data, labels and ownership

Use exactly the existing CAD v1.1 release, parser, label mapping, root/parent reconstruction, four-ancestor window, application character caps, URL/username masking, missing-author handling and declared exact/SimHash duplicate rules. Coalesce annotations before assigning labels. Any directed-abuse category maps to one; neutral-only and nonempty counter-speech/non-hateful-slur-only sets map to zero. Reject contradictory/unknown labels. Gold context tags, authors, source IDs, split fields and annotation rationales remain audit information, never features.

Keep all published test-thread ownership, including authors/context from excluded rows. Apply the same whole-thread test-author, protected-duplicate and challenge exclusions to pooled original train/dev data. Preserve the same primary case eligibility and separate missing-context diagnostics. No case or component moves from the test to development. Unknown authors remain a disclosed independence limit.

| Preserved item | Identity / expected aggregate |
| --- | --- |
| CAD archive | 9,941,773 bytes; SHA-256 `69f5ed2fd7b40de21fe54c620549f0be6c34eaf55b8de06ff481cabe3e9476d2` |
| Selected TSV | SHA-256 `7287d635e1d35ae1e64779ffe107df16f493c6ccc4084c4497bbf3f56ae0f349` |
| Codebook | SHA-256 `3d9489fc77b25b92c48f91192c0a52d561413cf260774935aa6a7959131612d4`; retain the existing consistency review and limitations |
| Base source/model settings | Canonical SHA-256 `d7ff7bdefc6736c930ed0d2226f417c49ea451dc1995747e7eedc499489ffece` |
| Development | 1,624 primary cases; 1,356 label-0 / 268 positive; 248 threads; 66 unknown target authors; 135 components; largest 571 cases |
| Component count vectors | Canonical SHA-256 `60f4121621cc7758181ae7f2d35e4586ddc837b8eb1da98c56662e876818e935`, using the feasibility probe's sorted component-to-count representation |
| Protected ownership | All 342 published test threads; retained primary test 3,315 cases, with 2,767 label-0 / 548 positive, and 1,949 diagnostic cases; remain unscored until final access |
| Primary development case identity | `c1f4885298d619ae63e9f28a93cb6a11be94977c0fa3eb0c88051e28ea196b87` |
| Primary test case identity | `395a0c5059a974b96d0b9f2d9ef58bffe476c6a6365aa2e20bddce245f23332d` |
| Test diagnostic case identity | `56d5b117ad28c2ddf5fae3cb53d949f82e739dbc3009fc94b522ed39193a3752` |
| Published-test ownership identity | `8a23d2f612c85b4d8972d6b9deee5c3de2e7ef5593290609bb5c7fb88aa2e43a` |
| Existing v1 cohort audit | Byte SHA-256 `b490a4f49422b282ae24f11ea7c49bd0949147bd822be9bdba0d545e1cb64882`; preserve its unavailable result |

Case identities above use `canonical_sha256([serialize_case(case), ...])` with cases sorted by case ID and the existing v1 serializer. The ownership digest uses the exact dictionary fields `source_id`, `archive_sha256`, `member_sha256`, `published_test_thread_ids`, with source ID `cad-v1.1` and sorted test-thread IDs. Only digests were emitted when measuring these identities; no predictions or test scores were produced.

Recompute these admission aggregates, case/ownership hashes and component-count identity before allocation. A mismatch is `cohort_identity_changed`; do not select another cohort or quietly update the expected identity. The current challenge reservation is empty. V2 carries forward that empty reservation and keeps challenge evaluation pending. New human contributions require their own permissioned reservation; they cannot be added to this fixed pool or used to alter its allocation after fitting.

## Versioned boundaries and storage

Introduce protocol ID `cad-context-v2-constrained`, study/bundle schema 2 and a separate `configs/context-harm-v2.json`. The new configuration binds the unchanged base settings and the allocation, fold, solver and holdout policies below. Keep `configs/context-harm-v1.json`, the 17 CPU/data package pins, the 26-wheel encoder lock/catalog and all existing research artifacts unchanged.

Use Git-ignored private roots outside OneDrive: `data/context-harm-v2/`, `models/context-harm-v2/` and the shared `data/context-harm-holdouts/`. Store a successful frozen study at `data/context-harm-v2/v2/` and new public aggregates at `output/research/context-harm-v2/`. Never write new records into `data/context-harm/`, `models/context-harm/` or the archived public v1/URL/paired-study report directories. Preserve existing file bytes; retain the two pre-existing CRLF legacy reports.

Admit source bytes into the new root from the verified local cache, or use the existing bounded source acquirer if that cache is unavailable. Keep the original source-admission settings intact, and bind both their hash and the new protocol-config hash. Verify copied source, codebook and review bytes rather than treating a copy as a fresh human review. Record cache reuse honestly; do not claim another fresh download unless one succeeds. Keep source-transfer budgets, absolute deadlines and native worker ownership from v1.

Keep one context-harm package. Add a focused count-allocation unit and a version-dispatched protocol boundary; reuse the verified conversation/source/component and CPU/neural primitives. Protocol-aware study loading, fitting guards, calibration, artifact inspection and final access must dispatch on explicit schema/protocol fields, not on a directory name. Unknown/mixed versions fail closed. V1 keeps its declared greedy and fold-shuffle behaviour; it is not upgraded in place. Archived v1 reproduction remains tied to its recorded commit.

Offline v2 commands use the existing CLI with an explicit `--protocol cad-context-v2-constrained` and the v2 root/model paths. V1 commands keep their current defaults. Loading a different protocol than the command requests is an error, never a fallback. Add a read-only `verify-allocation` command to reconstruct the unchanged count problem under the bound method and compare its assignment/fold identities with the frozen records. It publishes no proposal, study, registry claim, model or final-access receipt; count verification remains permitted after final scoring. Source/admission establishes the shared holdout-registry location; later stages consume its bound location and cannot substitute a new registry through a flag.

| Unit | Responsibility and boundary |
| --- | --- |
| Source/cohort admission | Verify immutable inputs; produce the same eligible cases, components and protected ownership |
| Allocation worker | Consume only ordered component identifiers and row/class counts; return one deterministic assignment or a structured unavailable outcome |
| Protocol publisher | Validate the audited assignment and fold map, then atomically publish immutable study files |
| Calibration adapter | Consume frozen fold membership; retain the existing calibration-quality checks |
| Holdout registry/final access | Coordinate one official study and final reservation across version roots |
| Training/artifact/report adapters | Bind the declared protocol, allocation, folds, runtime and selected models; keep public outputs aggregate-only |

## Hard allocation constraints

Let each development component be assigned wholly to exactly one of five ordered bins: `train`, `validation`, `calibration_fold_0`, `calibration_fold_1`, `calibration_fold_2`. Calibration is the union of the last three bins. Its folds are disjoint subdivisions, not additional data. No dropping, splitting, duplicating, resampling or hand-picking components is allowed.

| Check | Required support |
| --- | --- |
| Training | At least 200 cases of each class |
| Validation | At least 30 cases of each class and ten components |
| Calibration union | At least 30 cases of each class and ten components |
| Every calibration held-out fold | At least five cases of each class |
| Every calibration fitting portion, the other two folds | At least twenty cases of each class |
| Development component size | No component over 70% of the full primary development pool |
| Protected primary test | Existing minimums of 100 per class and thirty retained threads, checked at admission without predictions |
| Isolation | Unchanged whole-thread, known-author, context-record and declared duplicate ownership checks across development partitions and protected sets |

These are readiness gates, not hyperparameters. Failure produces unavailable evidence without a frozen replacement study or fitted model. Calibration support does not prove calibration quality.

## One reproducible allocation policy

Use a deterministic feasibility-preserving allocation, with a declared balancing preference. It is a heuristic for partition balance, not a claim of a globally optimal split. Whole-component feasibility is a hard condition on every choice.

Sort component IDs lexicographically, shuffle that ordered list once with `random.Random(42)`, and use its ranks to break descending component-size ties, preserving v1's initial component order. Never retry that seed or inspect model performance to choose an ordering. Candidate bin indices are fixed as `train=0`, `validation=1`, `calibration_fold_0=2`, `calibration_fold_1=3`, `calibration_fold_2=4`.

For each component, rank candidate bins using counts in the already assigned prefix plus the tentative placement. Unassigned components contribute zero to this balancing score, but remain in the full feasibility problem. Global totals `N_m` for metrics `rows`, `label_0`, `label_1` are fixed development totals. For outer partitions `p` in train/validation/calibration, use `a_p=14,3,3` respectively; calibration counts are the sum of its three folds:

- First score: `B_outer = sum(p,m) ((20*c[p,m] - a_p*N_m) / (a_p*N_m))**2`. This carries forward v1's normalized row/class deviation preference toward 70/15/15.
- Second score: `B_fold = sum(f,m) ((3*c[f,m] - c[calibration,m]) / N_m)**2`. This prefers evenly filled calibration folds without overriding the outer balancing preference.
- Rank by `(B_outer, B_fold, bin_index)`, computing both scores as exact rational numbers with Python `Fraction`; no floating tolerance is used for ties.

Use one fixed binary feasibility problem with five assignment variables per component and exactly the hard constraints above. Its objective is constant zero. First solve it without a fixed prefix to establish global feasibility. For each component, try candidate bins in the ranked order, fixing that bin and the previously accepted prefix. Choose the first solve with successful status and an independently verified complete integer witness. Advance to the next bin only when the solver proves the tentative problem infeasible. The witness's assignments for unprocessed components are not adopted; they only establish that the prefix can be completed.

After the last choice, validate the final assignment and all class/component/fold counts independently. Every accepted prefix must have a feasible completion; exhausting all bins after one exists is `allocation_oracle_inconsistent`, not permission to restart. A time limit, unknown status, unexpected solver warning or invalid witness aborts the attempt rather than trying a different bin. This determines one assignment regardless of which feasible completion the solver returns.

Use the existing Windows CPython 3.11.17 CPU environment, NumPy 2.4.6 and SciPy 1.17.1 `milp`/bundled HiGHS. Freeze interpreter/package inventory, solver version/binary identity, coefficient ordering, solver settings and allocation implementation hash. Configure one native thread, HiGHS `threads=1`, fixed `random_seed=42`, no parallel solving and presolve enabled. The pinned SciPy wrapper takes `parallel=False` and converts it to the native off setting. Allow only the expected warning that these declared backend options are forwarded; any ignored/invalid option or numerical warning makes the attempt unavailable.

Each solve uses `mip_rel_gap=0`, at most 10,000 nodes and `time_limit=min(20 seconds, remaining internal budget)`. Share one 90-second monotonic internal budget across the attempt, with at most `1 + 5*component_count` solver calls. The parent supervises the entire fresh worker with a 120-second absolute deadline, a 2 GiB process-tree RSS cap and native Job Object ownership before any ML import. Acquire the existing nonblocking cross-process harm TrainingAdmission lease, using the same lease as CPU/neural training and the optimizer pilot. A busy lease returns unavailable.

Bound production inputs to 10,000 cases and 512 components, positive class totals and a 256 KiB feature-free count payload; otherwise return `allocation_input_unsupported`. Each count vector has strictly integral, nonnegative class counts and positive rows equal to their sum; component IDs are unique, and unknown payload fields are refused. Verify agreement with the supervisor's admitted component membership. Only component identifiers and counts enter the allocator. Return a compact bin vector, rejected-bin masks and aggregate call statuses within the existing 64 KiB worker-output cap; the supervisor reconstructs the exact rational decision trace privately instead of emitting verbose per-call logs. All binary values must be finite and within `1e-6` of zero or one; round and recheck exactly-one membership, every integer constraint and the requested prefix using integer arithmetic. Require successful solver status for a witness; reject even a valid incumbent returned with a time/node-limit status. A proven-infeasible initial problem yields `allocation_infeasible`; subsequent inconsistent proofs yield an explicit integrity failure.

The 70/15/15 targets and fold balance remain soft preferences. Report their actual deviations; do not claim a global optimum. These time/memory caps are proposed engineering limits, not measured throughput of the revised algorithm. No fallback to the old unconstrained greedy allocation, changed ordering/limits, seed retries or manual assignments is allowed.

## Audit, freezing and compatibility

The audit writes one private proposal/attempt record binding source/review/reservation hashes, exact cohort/component counts, both configs, implementation/runtime, all solver limits, termination/call summaries, exact balancing scores/choice order and the deterministic component/bin map. Distinguish `allocation_infeasible`, `allocation_limit_reached`, `allocation_worker_failed`, `allocation_numeric_invalid`, `allocation_oracle_inconsistent`, `cohort_identity_changed` and admission/isolation failures. A proven-infeasible result refers to the encoded constraints; a timeout does not prove impossibility.

An identical successful audit reuses its checked proposal. Completed failure records are not silently overwritten or automatically retried. Freeze consumes the exact proposal, recomputes admission/ownership and every integer constraint, and refuses drift. It does not solve again or choose another assignment. Interrupted publication may resume only the same bound input/proposal and expected output hashes.

Publish schema-2 `study.json`, `components.json`, train/validation/calibration/test/diagnostic JSONL files, `allocation.json`, `calibration-folds.json` and an explicit member manifest atomically. Keep individual cases sorted by case ID. The fold file binds every calibration case to exactly one declared fold and its component; reject unknown, missing or duplicated cases, split components, wrong counts and overlapping memberships. It also binds the calibration partition and allocation hashes.

Frozen metadata includes protocol ID, source/base/v2-config hashes, parser/preprocessor/grouping/allocator identities, full cohort/partition identities, allocation policy/receipt, fold-map identity, challenge reservation and the holdout-registry identity below. Include new protocol files/configs in execution fingerprints. Fit, selection, calibration, bundle and final receipts all bind this same identity transitively and explicitly expose protocol/fold hashes where they are consumed. No schema-1 model, proposal or receipt can be attached to a schema-2 study.

Schema-2 bundles include checked allocation/fold receipts and their hashes, plus the existing model/runtime/preprocessing provenance. They contain no test rows or raw CAD source. Inspect version, member sets, bindings and runtime before deserialization. Tampering with a fold, allocation decision/score, implementation, registry binding or selection record must refuse fitting/packing/evaluation. Hashes provide local integrity, not authentication of an untrusted distributor.

## Training, calibration and reporting

Carry forward the v1 candidate grid, paired case comparison, preprocessing, thresholds, resource supervisors and conditional encoder rules. Fit twelve CPU candidates: target/context branches each cross `C=0.5,1.0,2.0` with unweighted/balanced classes, sparse TF-IDF and liblinear logistic regression. Training-only vocabularies and identical primary case IDs remain mandatory. Keep at most four native threads, an 8 GiB process-tree cap and a fifteen-minute deadline per CPU fit. Select on validation recall under the declared 5% validation FPR budget, then precision, lower FPR and config ID. Preserve unusable/all-negative outcomes.

Calibration uses the preassigned three folds; do not re-shuffle or reallocate them for a branch. Preserve sigmoid fitting, held-out/fitting support checks, positive/finite slope, score-variation/convergence checks, out-of-fold Brier comparison and five-bin equal-frequency ECE. Refit once on all calibration rows only when supported. Calibration never changes the frozen raw threshold. Invalid or worsened calibration suppresses probability without silently selecting another model/calibrator or re-solving the split.

The compact encoder remains conditional. Keep the existing exact 26-wheel lock/catalog and pinned DistilBERT revision `12040accade4e8a0f71eabdb258fecc2e7e948be`, isolated `.venv-harm-neural`, source budgets and actual-worker runtime attestation. Only a ready study permits guarded source/environment setup and the training-only pilot: at most 32 examples, twenty optimizer steps, sequence length 256, microbatch two, accumulation four, 3.2 GiB GPU allocated/reserved peaks, 8 GiB RSS and ten minutes. Full candidates require passing support, CUDA/runtime, memory and throughput gates and stay within thirty minutes each. Missing/unavailable pinned sources or runtime produce `neural_unavailable`; do not update pins or drivers to make them pass.

Both neural branches use the same token-compatible subset and preserve the full target; over-252-token targets abstain. Recheck all existing compatible-cohort class/component/size gates without altering the primary allocation. Restrict the frozen calibration fold map to covered cases for neural diagnostics; if any support check fails, its calibration is unavailable. Do not redistribute remaining cases or folds. Compare CPU/neural branches on declared common coverage separately from the full CPU comparison.

Before final access, freeze every selected configuration, raw threshold, calibration record, neural participation/unavailability, actual runtime and coverage policy in one immutable research artifact. Keep `research_only` status, the offline `--research` prediction requirement and live-warning refusal. The default application continues its current rules and unavailable learned card. No UI migration, new extension permissions, team authentication or release bypass is part of this revision.

Report the existing phrase baseline, branch point metrics, class/coverage counts, calibration diagnostics where supported, subgroup errors, latency and peak resource measurements. Use the original 1,000 paired component-bootstrap replicates with seed 42 on identical scored cases. Preserve the sparse/dominant-component interval refusal rules. Do not claim established context improvement from unsupported intervals, Reddit labels as contemporary cross-platform performance, or a single-message label as evidence of harassment intent. Human challenge evaluation remains pending until a separately reserved, independently reviewed cohort exists.

## One protected-test history across versions

Creating a new study directory must not create another opportunity to score the same protected test. Establish an authoritative local registry at the explicitly configured, outside-OneDrive `data/context-harm-holdouts/`. Its immutable ownership key is the canonical hash of CAD source ID, archive/member hashes and the sorted set of **all published test-thread IDs**, including context/excluded records. Primary and diagnostic test rows share this key; changing eligibility or a directory name cannot reset it.

At v2 admission, verify the predecessor v1 root/reservation and absence of any v1 final-access reservation/completion. If a predecessor receipt exists, refuse a new v2 adoption; it is not a fresh test. The registry records its UUID, ownership identity, predecessor provenance and one active frozen-study identity. Bind its resolved canonical location and immutable identity into the v2 proposal/study; commands cannot switch to a new empty registry. A copied study keeps that authoritative location. Missing, changed, divergent or inaccessible registry records fail closed. The common fitting/final boundary also refuses a legacy production CAD study without matching shared ownership adoption; choosing the v1 command cannot bypass a reserved/completed v2 history. Historical report verification remains read-only and the existing v1 unavailable audit method remains unchanged.

Use registry states `unscored`, `reserved`, `complete`. Freeze claims the active study using its already staged expected manifest hash; another study cannot replace it. Recover a crash between claim and publication only for the identical staged identity. Keep locks and atomic/exclusive publication local; this file-based registry is a workflow control, not protection against an operator deliberately deleting/forging the local research history.

Use a consistent nonblocking lock order: shared TrainingAdmission lease, holdout-registry lock, then per-study lock. Allocation/fitting/pilot admission checks the authoritative state while holding this order and retains its existing training lease while a worker is active. Final reservation takes the same lease, so it cannot race an active fit, verifies frozen artifact/current runtime, then durably records the complete final identity in the registry before any final scoring load. Once reserved or complete, all new allocation publication/refits/pilots for that ownership are refused. A read-only source/count/manifest verification is still permitted.

The authoritative final identity includes study/protocol/allocation/fold/config/source identities, artifact and selection/calibration hashes, actual CPU/neural runtime attestation, coverage and preprocessing, bootstrap settings and absolute output identity. Preserve a matching per-study receipt for existing helpers. Reserve the registry first; an interrupted local mirror write may only repair that same identity, not create a new reservation. No final rows are loaded for prediction until both receipts agree.

Only an identical reserved operation may resume. Another root, protocol, model, runtime or output identity is refused. Atomically publish final aggregates before marking the registry complete with their hashes; recover a matching already-published report by verification without re-scoring it. Completed final access cannot be reset. Any later method/source/error-driven revision requires independently reserved held-out ownership; this study's final examples cannot be reused for tuning.

## Delivery and acceptance

Deliver the versioned CLI/config, bounded count allocator and private proposal, immutable study/fold manifests, shared holdout registry, compatible model/calibration/artifact/evaluation adapters, measured CPU study, conditional neural outcome, aggregate reports/model card and reproduction guide. A supported software path with an honestly unavailable solver/model/calibration/neural outcome remains valid; do not manufacture a successful research score.

Required verification covers:

- Constraint-feasible grouped fixtures that fail the legacy heuristic; true infeasibility; missing/zero classes; oversized components; different feasible solver witnesses with identical deterministic allocation; exact rational balancing/tie arithmetic; prefix consistency; drift and invalid solver values; time/node limits and a feasible incumbent that must be refused.
- Exact production cohort/vector identity; known-author/duplicate/context isolation; unchanged v1 allocation semantics; no gold/source identifiers entering feature payloads; complete, disjoint frozen folds and refusals for missing/changed membership.
- The real worker's native ownership, single-thread solver option path, absolute deadline, process-tree cleanup, cross-process admission and busy/crashed-owner recovery. Include allocation-policy/fold mutation and unsupported-version tests through the actual CLI/worker/bundle paths.
- Calibration-quality failures despite count support; neural coverage shrinking a frozen fold; mixed protocol/artifact refusals; resource failure without partial successful artifacts; actual encoder-runtime drift.
- Registry adoption, conflicting study roots, concurrent fitting/final reservation, interrupted claim/mirror/report publication, identical resume, missing/swapped registry, cross-version final refusal and completed no-rescore behaviour.
- One synthetic end-to-end v2 pipeline exercising production adapters with explicit synthetic provenance and isolated synthetic ownership. It tests software only; synthetic data can never pass as CAD production admission.

After implementation, run the complete pinned Python suite and the existing Node conversation/web/extension suites, with meaningful v2 regressions and no undocumented skips. Run a count/source reproduction from a clean clone and verify the same canonical allocation/fold identities before official fitting; after final access, reproduction verifies archived artifacts/reports without another fit or scoring pass. Do not overstate a cache reproduction as a fresh download.

Before and after the real run, verify the existing private v1/source/reservation data, public v1 harm/feasibility evidence, nineteen protected baseline Git contents, both CPU locks, neural lock/catalog and empty paired intake remain unchanged. Record Git revision, hashes, interpreter/packages, solver outcomes and actual memory/time measurements. Keep raw source, memberships, predictions and weights private; publish aggregate methods, counts, hashes, limitations and CC BY 4.0 attribution only. Retain the existing deferred Chrome toolbar/context-menu record; no new browser-validation claim is required for an unchanged UI.

One independent final review covers the whole implemented change and methodology records. Fix verified findings, then deliver the runnable project with default learned warnings still disabled. This revision does not authorize a live model release.

## Documentation and next review

The existing [CAD-v1 design](2026-10-13-sentinel-context-harm-design.md), [delivery record](../../context-harm-delivery-record.md) and [approved year-long design](2026-10-05-sentinel-year-long-design.md) supply inherited requirements. [SciPy's official 1.17.0 milp documentation](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.optimize.milp.html) documents integrality, constraints and solver statuses/limits. The installed 1.17.1 wrapper was inspected for option forwarding; an exact-patch documentation page was unavailable. [HiGHS option definitions](https://ergo-code.github.io/HiGHS/dev/options/definitions/) describe native thread/parallel/seed controls; effective compatibility must be verified with the pinned bundled solver, not assumed from development documentation.

Review this written specification before the detailed implementation plan. Only specification approval permits preparing that plan; product changes, setup, new study freezing, fitting and protected final scoring remain pending plan approval. The selected execution method remains implementation here with one independent final review.
