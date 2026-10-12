# Sentinel: English conversation and directed-abuse design

Date: 2026-10-13. Status: **approved written specification; implementation plan awaiting review**. The user approved the CAD-based direction and bounded compact-encoder pilot after the source investigation, then approved this written specification on 2026-10-13. Specification approval permits preparing the plan; product implementation and live model activation have not occurred. Preserve the user's execution preference: implementation in this chat with one final independent review, after plan review.

## Purpose and experiment

A student or community reviewer should be able to select a message, supply the preceding conversation, inspect a cautious assessment of that target, and save the exact assessment with its context. Build a trained English directed-abuse module and a fair experiment asking: **Does preceding conversation context improve directed-abuse detection compared with the target message alone, on held-out threads and known authors?** Inspect false positives on counter-speech and separately reviewed quoted/reported abuse and ordinary disagreement.

This is subproject C of the [approved year-long design](2026-10-05-sentinel-year-long-design.md). The [source investigation](../../context-harm-source-audit-2026-10-12.md) and [aggregate audit](../../../output/research/context-harm-source-audit.json) establish a feasible candidate cohort, not readiness after every exclusion or an accuracy finding. Toxicity, directed abuse, intent and repeated harassment are different claims; this study's learned label is directed abuse. Preserve separate fraud/URL, harm and profile results.

## Source and label contract

Use CAD v1.1 from [the author release](https://zenodo.org/records/4881008), with CC BY 4.0 attribution. Retrieve only its 9,941,773-byte data archive and needed metadata. Verify SHA-256 `69f5ed2fd7b40de21fe54c620549f0be6c34eaf55b8de06ff481cabe3e9476d2`, then the `data/cad_v1_1.tsv` member hash `7287d635e1d35ae1e64779ffe107df16f493c6ccc4084c4497bbf3f56ae0f349`. Limit archive bodies to 12 MiB, the selected inflated TSV to 16 MiB and metadata to 1 MiB; enforce both a 120-second request deadline and a 32 MiB durable aggregate received/reserved-byte budget. Download failure is unavailable, not an empty dataset. Do not download released CAD models or predictions or fetch destinations appearing in comments.

Parse the author's TSV with `QUOTE_NONE`; normalize documented metadata quote wrappers and missing markers without removing quotation marks from comment text. Coalesce annotation rows by `info_id`, retaining the label set and provenance. Conflicting text, thread, parent, author or eligible split values for the same utterance must stop admission. Respect source bot, empty, image and language exclusions for target eligibility; contextual records do not become labelled training targets merely because their text is available.

The [author paper's taxonomy](https://aclanthology.org/2021.naacl-main.182.pdf) distinguishes three directed-abuse categories from neutral content, counter-speech and non-hateful slur use. Review the supplied codebook before freezing, and implement this explicit mapping. Apply integrity failures before assigning a binary label:

| Source label set | Study label |
| --- | --- |
| Any of `IdentityDirectedAbuse`, `AffiliationDirectedAbuse`, `PersonDirectedAbuse` | `1: directed_abuse`, including co-occurring counter-speech or slur annotations |
| Only `Neutral`, or a nonempty subset of `CounterSpeech` and `Slur` | `0: not_annotated_directed_abuse` |
| `Neutral` combined with another primary category, unknown categories or contradictory records | Integrity/admission failure; never silently relabel |

Retain non-hateful-slur and counter-speech subgroup tags. Mapping these to the study's negative class does not rename them neutral or prove that the text is harmless in every setting. Do not expose source subtypes as trained predictions; the first head is binary. Gold context tags, highlights, rationales, identities, source/split fields and dates are audit metadata, never model features.

Store raw sources, derived cases, challenge records, splits and models in new Git-ignored `data/context-harm/` and `models/context-harm/` paths outside OneDrive. Keep the existing 17 dependency pins, URL artifacts, paired-study artifacts and intake untouched. Public reports contain aggregate counts, methods and hashes; no raw comments, usernames or annotation-worker identifiers.

## Context reconstruction and fair cohort

Reconstruct reply ancestry from supplied parent IDs within the same thread. A root link may resolve to the matching `-title` and `-post` entries only when root-link and same-thread metadata confirm that relationship; order title before body. Decode source linebreak markers. Reject cycles, cross-thread parents and contradictory ordering. Missing, image-dependent, unavailable or source-flagged non-English context remains unavailable. Do not substitute an arbitrary earlier row, sibling reply, later reply or external scraped text.

Model input uses the target and at most four preceding ancestor turns, ordered oldest to newest within that window; each resolved root title/body entry counts as one turn. Retain full supplied/available provenance and report the number of turns used and omitted. Preserve quoted/reported text. Replace URLs and usernames consistently in both branches, preserving surrounding words and quotation punctuation. The first model families consume text with fixed target/context separators. Local speaker relationships support the turn display and audit only; raw author names/IDs, local speaker IDs and global speaker identity must not enter features.

The primary context comparison includes only targets with at least one usable predecessor and within the application character caps. Train, select, calibrate and score both primary branches on identical case IDs and contextual gold labels. Targets with missing predecessors are a separate coverage/target-only diagnostic; they cannot be counted as successful context assessments. The preliminary audit found 2,395 context-available development targets (382 directed-abuse labels) and 4,801 published-test targets (819 directed-abuse labels); final exclusions may reduce these counts.

Retain target-only inference capability through the selected primary target-only model. Record that its training population had available context even when inference does not. Whole-thread labelling may involve more context than the four-turn window; report this limitation and errors by available/used ancestry length.

## Protected test and development protocol

Preserve the published test-thread ownership. First reserve every known author appearing anywhere in those test threads, including contextual/excluded records. Remove whole original train/dev threads sharing any reserved known author. Pool the remaining original train/dev threads for Sentinel development; this intentionally differs from the paper's train/dev benchmark and must be reported. Missing/deleted author markers remain unknown, never one shared person.

Audit duplicate inputs after username/URL masking, Unicode NFC normalization, case folding and whitespace normalization. Exact complete target-plus-used-context matches connect cases. Exact meaningful targets with at least eight word tokens and 40 normalized characters also connect cases irrespective of context. For these meaningful targets, group near duplicates using deterministic 64-bit SimHash over word trigrams (the first eight SHA-256 bytes, most-significant bit first; zero weighted sums map to zero), Hamming distance at most three, with four disjoint 16-bit candidate buckets. The manifest binds the exact word tokenizer and trigram serialization. This defines a documented near-duplicate heuristic, not semantic equivalence. Generic shorter replies are compared with their context rather than treating every occurrence of a common word as one conversation.

Purge whole development threads connected to protected test inputs by these duplicate rules; never move a test case into development. Connect remaining development threads by known authors and duplicate ownership. Source author overlap and duplicate keys include text/context actually supplied to models. Measure retained-source/class composition and unknown-author coverage before and after every purge.

Use seed 42 once. Allocate whole development components to train/validation/calibration with target proportions 70/15/15. Never retry seeds, cut a component or move cases after final scoring. Readiness requires:

- Training: at least 200 cases per class.
- Validation and calibration: at least 30 per class and ten connected components in each partition.
- Primary test: at least 100 per class across at least 30 retained threads.
- No known author, protected utterance/context record or declared duplicate component across partitions.
- No development component greater than 70% of the development cohort; all required partitions must be feasible.

The preliminary pool has 2,982 eligible targets in 405 threads and 241 author components; its largest component has 711 targets. These are feasibility figures before final context/duplicate/cap filtering. Failure returns explicit unavailable reasons and writes no replacement split or fitted model. A frozen manifest binds archive/member hashes, parser/normalizer/grouping implementation, exclusions, label mapping, case and partition hashes, candidate settings and source metadata. No harm result may be inferred from the separate phishing benchmarks.

## Models and resources

Establish the phrase-rule baseline and two primary CPU branches:

| Branch | Inputs and fixed candidate family |
| --- | --- |
| Target only | Word TF-IDF unigrams/bigrams, maximum 30,000 sparse features; logistic regression |
| Context | Separate target and preceding-context TF-IDF spaces, at most 30,000 each, sparse concatenation; logistic regression |

For each learned CPU branch, compare `C = 0.5, 1.0, 2.0` crossed with `class_weight = None, balanced`, solver `liblinear`, maximum 1,000 iterations and seed 42. Fit vocabulary only on training. Do not densify the sparse matrices or use gold contextual-need labels as features. Standalone and contextual preprocessing are identical for their shared target text.

Use Windows CPython 3.11.17 and the existing locked CPU environment. Run one fit at a time, at most four native threads, with an 8 GiB training process-tree RSS cap and a 15-minute CPU-fit deadline. Measure worker/descendant memory and terminate descendants on timeout/failure. Resource failure is recorded; it cannot publish a partial successful candidate.

### Bounded compact-encoder pilot

The approved hardware design records an RTX 3050 Laptop GPU with 4 GiB VRAM; recheck driver/device/runtime availability. PyTorch, Transformers and Safetensors are currently absent. Use a separate `.venv-harm-neural/` environment and a dedicated exact Windows/Python-3.11 dependency lock. Select supported stable binary packages through official metadata and verify a CUDA forward/backward/optimizer smoke before corpus fitting. The implementation plan must resolve and record exact versions and wheel identities; do not alter the working CPU locks, system Python or drivers. [PyTorch installation/verification](https://pytorch.org/get-started/locally/)

Use the generic English [DistilBERT base](https://huggingface.co/distilbert/distilbert-base-uncased), revision `12040accade4e8a0f71eabdb258fecc2e7e948be`; its card declares Apache-2.0 and generic language pretraining. Download only the pinned Safetensors weights, config, tokenizer/vocabulary and licence/card, with a 512 MiB aggregate model-source bound. Record file hashes; disable remote code and unpinned revisions. The generic pretraining corpus is an external-data limitation, not proof of zero historical overlap.

Pilot only on at most 32 training examples for 20 optimizer steps, sequence length 256, microbatch two, gradient accumulation four and FP16 when supported. Require peak allocated and reserved GPU memory each at most 3.2 GiB, process-tree RSS at most 8 GiB and pilot completion within ten minutes. If runtime, memory or measured throughput cannot support a full candidate within a 30-minute fit deadline, record `neural_unavailable` and complete the CPU study. Do not continue a runaway fit or repeatedly loosen limits.

If the pilot passes, compare target-only and contextual DistilBERT with the same revision and identical token-compatible cases. Candidate learning rates are `2e-5, 5e-5`, at most three epochs, AdamW, weight decay 0.01 and seed 42; select checkpoint/configuration on validation. Record determinism limitations. The paired input reserves three special tokens and at least one context token, leaving at most 252 WordPiece target tokens. A longer target abstains from both neural comparison branches; verify the pinned tokenizer's special-token count instead of truncating the target. Preserve the entire compatible target and retain the most recent context tokens within the remaining 256-token budget. Report context truncation and neural coverage. Compare CPU and neural results on the same declared compatible subset separately from the full CPU cohort. Conditional neural participation and settings are locked before final evaluation.

## Selection, calibration and one-time evaluation

Select each branch's raw threshold/configuration on validation for greatest recall under a 5% validation FPR budget; tie-break by precision, lower FPR and config ID. This is a harm-study experiment setting, not a deployment guarantee. All-negative admissible thresholds or zero supported recall must be reported, not presented as a useful detector.

Fit a fixed sigmoid calibrator only on the separate calibration partition, with at least 30 cases of each class. Evaluate calibration diagnostics with three component-grouped out-of-fold partitions, seed 42, then refit once on the complete calibration partition. Each held-out fold needs at least five cases per class and its fitting portion at least 20 per class. Report out-of-fold Brier and five-bin equal-frequency ECE alongside the uncalibrated probabilities; numeric confidence is unsupported if grouping/class gates fail, the fit is invalid or Brier worsens. Do not select models, thresholds or calibrator variants from these diagnostics. Calibration affects displayed probabilities, never the frozen raw decision threshold. Suppress numeric confidence for unsupported calibration or input outside declared coverage. Final-test calibration diagnostics are reporting only and cannot change the frozen artifact.

Reserve final access durably before loading test rows for scoring. Bind source/protocol, artifacts, code and dependency locks, tokenizer/base-model hashes, selected settings, preprocessing/truncation, cohort/coverage identities, bootstrap configuration and output identity. Identical interrupted evaluations may resume; completed final outputs cannot be overwritten or rescored for tuning. Later revisions need a newly reserved final dataset, not another pass over this test.

Report confusion counts, precision, recall, positive and macro F1, PR-AUC, FPR, abstention/coverage, Brier/ECE when supported, latency and peak RAM/VRAM. Compare context-minus-target differences on identical cases using 1,000 paired bootstrap replicates, seed 42, with connected test thread/known-author/duplicate components as the resampling unit. Mark intervals unstable/unavailable if either class spans fewer than ten components or one component holds more than half the test cases. Point metrics may still be reported with this limitation; do not claim statistically established gains from unsupported intervals.

Report counter-speech-only and non-hateful-slur-only false positives, source/community shifts, source gold contextual-need tags, unknown authors, window/token coverage and exclusion effects. Gold subgroup tags are used only for reporting. Never tune using final subgroup errors. These historical Reddit labels do not establish contemporary, multilingual or cross-platform accuracy.

## Application contract and failure behaviour

Add a versioned optional `harm_assessment` to the existing shared API. Keep the existing `harmful_content` phrase observations and other optional modules compatible. Do not migrate the complete app to FastAPI/React, implement team access control or add the future job API in this subproject.

Structured requests add `conversation_kind` (`linear` or `reply_thread`), `conversation_turns` and `target_turn_id`; supplying any of these requires all three. Each turn has `turn_id`, nullable `speaker_id`, `text`, optional `relative_time_seconds` and, for reply threads, `reply_to`. Require one to 50 turns, unique opaque turn IDs, nonempty text, at most 20,000 total conversation characters and at most 10,000 target characters. IDs match `[A-Za-z0-9_-]{1,64}` and the selected target must exist. Optional relative timestamps must be finite nonnegative seconds and preserve supplied order. In a reply thread, each turn explicitly supplies a nullable `reply_to`, references only an earlier supplied turn and stays in the same case. In a linear conversation, the immediately preceding turn supplies the predecessor and `reply_to` is rejected. Reject unknown turn fields instead of silently ignoring structure. A target can precede later supplied turns, but later turns never become model context.

When structured turns and legacy `message` coexist, the message must equal the selected target text after outer whitespace trimming; reject ambiguous dual targets. Legacy `conversation` text is preserved for compatibility but cannot silently supply learned speaker/reply structure. Plain extension-selected messages can use the target-only branch with explicit missing-context coverage. Conversation-only legacy text without a selected target produces `not_assessed` in the learned module.

Results include schema/task/model version, state (`complete`, `degraded`, `not_assessed`, `unavailable`), category (`review`, `not_flagged`, `not_assessed`), branch, target ID, context/window/token coverage, observed evidence, unavailable checks, uncertainty and suggested human review. Keep observed phrase/quotation/context facts distinct from learned predictions. Any sparse-model token contribution is labelled a model contribution, not proof of meaning or intent; do not describe encoder attention as a causal explanation. Optional calibrated probability is conditional on the evaluated distribution. Do not invent intent, identify real speakers, average harm into fraud or infer harassment merely from multiple flagged messages.

The web app gets a turn editor, ordering, local speakers, reply/target selection and context coverage. Preserve pending-result, clearing, saving, reopening and feedback race protections. Save the exact submitted turns/target, result and model version; do not reanalyse a saved case silently. Export/deletion cover the saved snapshot. The extension retains explicit initiation and existing permissions; it submits target-only checks and renders the optional result safely as text.

Use one bounded harm inference worker at a time, four native threads, a 60-second deadline and an 8 GiB process-tree cap; reject concurrent harm work as unavailable/busy rather than queueing unbounded payloads. Coordinate memory admission with other optional model workers so simultaneously reserved process-tree budgets cannot exceed the 8 GiB optional-inference budget. A neural worker uses the separately configured local runtime; absence/failure must not break rule results. Discard temporary worker input/result memory on completion or observed cancellation/disconnection, and always by the deadline; never log payload text. The synchronous API adds no job-cancellation endpoint: clearing the browser rejects late results, and server cleanup may rely on its deadline when a disconnect is not yet observable. An optional top-level `language` string declares the language: trim/lowercase `en` is supported, other declarations produce `not_assessed`. A missing declaration records English as an assumption, not a verified language detector.

## Challenge review and release boundary

Provide an initially empty, private challenge workflow for quoted abuse, reported abuse, counter-speech, ordinary disagreement, direct abuse and uncertain cases. Accept traceable, permissioned real material with conversation/target provenance; two independent reviewers record the task label and family, with adjudication for disagreement. Do not auto-label from phrases or model predictions. Keep this challenge cohort disjoint from modelling and primary test ownership; development-derived challenge material must be reserved before fitting.

Until an adjudicated challenge cohort exists, mark its evaluation pending. Synthetic cases test software only. Initial trained artifacts remain `research_only`; the optional live adapter reports unavailable for them. An independent methodology/error review and a separately approved release step are needed to activate a learned warning. This milestone can deliver measured CAD research with an honest pending challenge/release outcome.

## Delivery and acceptance

Deliver the verified source adapter/audit, immutable cohort/split manifests, CPU models and bounded neural-pilot record, final aggregate comparison/model card, CLI reproduction, optional API/turn-editor integration and empty challenge workflow. Fingerprint implementation, dependencies, preprocessing, weights and tokenizer before loading locally trusted artifacts; hashes are not authenticated distribution.

Tests must exercise quoted metadata missing markers, duplicate annotation coalescing, mixed non-hateful-slur/counter-speech labels, known-author/duplicate purging, parent/root aliases, missing/cyclic/cross-thread references, future-turn exclusion, group allocation failure, label/feature separation, calibration suppression, durable same-version final access, resource cleanup and malformed/missing optional artifacts. Client tests cover escaped text and the existing stale/pending/save protections with structured turns. Verify the web workflow in a browser; preserve the existing record of deferred actual Chrome toolbar/context-menu checks.

Success requires a reproducible clean-clone workflow; no raw source/challenge cases in Git; protected existing studies unchanged; passing whole-project and client checks; truthful source/coverage/calibration/resource limits; and one final independent whole-branch review. CPU study availability depends on its gates. A neural candidate, challenge result or live release must not be claimed when its corresponding gate fails.

The next stage after written-spec approval is a focused implementation plan. Installation, product-code changes, fitting and final scoring begin only after that plan is reviewed.
