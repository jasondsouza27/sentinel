# Contextual harm v2: development-support feasibility

Date: 2026-10-18. Status: **investigation complete; direction approved; written specification awaiting review**. This is evidence for a new specification, not an implemented or approved v2 study. No model was fitted, replacement split published, protected test scored or live warning activated.

## Purpose and recommendation

Continue Sentinel's balanced year-long ML/application programme by making a real English directed-abuse comparison possible on the existing laptop. The conversation application and v1 research software are already implemented. The immediate research obstacle is support after protected ownership and context exclusions, not missing application screens.

Recommend a **versioned, constraint-aware CAD development allocation**, with supported calibration folds reserved before modelling. Retain the same label mapping, source, preceding-context rules, known-author/duplicate components and unscored protected test ownership. Keep the current v1 unavailable result unchanged.

The read-only investigation found an integer allocation meeting all current class/component support minimums, including the held-out/fitting class minimums for three grouped calibration folds. It does not establish detector quality, calibrated probabilities, a final allocation or deployment readiness.

## What the current evidence establishes

The [v1 cohort audit](../output/research/context-harm-v1/cohort-audit.json) has 1,624 primary development cases: 1,356 label-0 and 268 directed-abuse cases, across 248 threads. The implemented largest-first allocation gives training only 175 positive cases and validation/calibration only five/eight components. That algorithm followed the approved v1 method; its failure is not proof that every whole-component allocation is infeasible.

The v1 class minimums require at least 200 training, 30 validation and 30 calibration positives: 260 in total, leaving only eight positives above those minima. This is tight support and must remain visible in any later study.

## Read-only feasibility audit

The [aggregate record](../output/research/context-harm-v2-feasibility/feasibility.json) and [exact probe](../output/research/context-harm-v2-feasibility/probe.md) record the investigation.

1. Verify the already acquired CAD source with the current production loader and settings. Read the existing challenge reservation without modifying it.
2. Reuse the current protected-pool procedure. Confirm development counts and purge history match the archived v1 audit. That procedure consults protected ownership/text for the existing author and duplicate exclusions; no protected predictions or performance enter this investigation.
3. Form the unchanged known-author/duplicate components on primary development cases. There are 135 components; the largest has 571 cases, below the existing 70% component-size gate.
4. Send only component case/class counts to one bounded integer feasibility solve. Each component belongs wholly to training, validation or one of three calibration folds. The solver has 675 binary variables and 155 linear constraints, a constant-zero objective, a 20-second time limit and a 10,000-node limit.
5. Enforce the existing class minimums (200/30/30 per class), ten components each for validation and calibration, at least five held-out cases per class in every calibration fold and at least twenty per class in each corresponding fitting portion. Round and independently validate the integer witness against every encoded constraint.
6. Compare SHA-256 fingerprints before and after: all 84 files checked in the private harm tree, existing public research outputs and three config/dependency files remained unchanged. The probe published no study or model files.

Windows CPython 3.11.17, NumPy 2.4.6 and SciPy 1.17.1 were used from the existing pinned CPU environment. The count solver returned success in 0.109 seconds; this is a feasibility-solver measurement, not a training-time or application-latency measurement.

An illustrative witness was:

| Partition | Cases | Label 0 | Directed abuse | Components |
| --- | ---: | ---: | ---: | ---: |
| Training | 989 | 784 | 205 | 21 |
| Validation | 241 | 211 | 30 | 41 |
| Calibration, all folds | 394 | 361 | 33 | 73 |
| Calibration fold 0 | 143 | 130 | 13 | 19 |
| Calibration fold 1 | 128 | 118 | 10 | 20 |
| Calibration fold 2 | 123 | 113 | 10 | 34 |

Fold 0's fitting portion has 20 positives; folds 1 and 2 each have 23. All fitting portions exceed twenty label-0 cases. The fold rows are subdivisions of calibration, not additional cases.

**This witness is not a selected split.** The probe deliberately did not optimise the existing 70/15/15 fraction targets. Its joint calibration-fold assignment also differs from v1's seeded equal-component fold shuffle. Both allocation and fold assignment therefore need an explicitly approved v2 method; this is not permission to substitute these assignments into v1.

The component-count identity is `60f4121621cc7758181ae7f2d35e4586ddc837b8eb1da98c56662e876818e935`; the illustrative assignment digest is in the aggregate record. No component membership, source text, usernames, gold annotations or predictions are published here.

## Alternatives considered

| Approach | Benefit | Limit / decision |
| --- | --- | --- |
| **Constrain allocation on the existing CAD development pool** | A counts-only witness exists without weakening isolation or support requirements; reuses the implemented task and verified source | Recommended. A new version must define balancing, deterministic selection, bounded failure and persisted calibration folds before training. Sparse support still limits conclusions. |
| Expand CAD-compatible permissioned data | Can improve support and later challenge coverage | Requires provenance, consent and genuinely independent human annotation. No additional cases have been admitted. Continue alongside the study, not as automatically labelled data. |
| Start a different contextual-harm benchmark | Supplies additional contextual research settings | Useful later as a separate task. Different labels/domains cannot be pooled with CAD's directed-abuse label without a new justified mapping and study. |

Two primary author releases were checked for the last approach:

- [ToxiChat](https://github.com/abaheti95/ToxiChat) describes 2,000 Reddit threads plus chatbot responses, annotated for offensive language and stance, with released thread splits. Its [licence file](https://github.com/abaheti95/ToxiChat/blob/c1ffebd76596481b26aab35074816641b076f992/LICENSE-CC-BY-SA.txt) declares CC BY-SA 4.0. The displayed example schema provides ordered turns and offense targets but does not establish stable cross-thread author identities. No source body or cross-corpus overlap audit was acquired for Sentinel.
- [ConvAbuse](https://github.com/amandacurry/convabuse) documents conversation IDs, previous agent/user turns, target user turns, individual annotations, ambiguous/graded abuse labels and abuse-target categories. The repository declares CC BY 4.0 and says the release includes CarbonBot and E.L.I.Z.A data, while Alana examples are withheld. This human–agent setting and label scheme differ from CAD's Reddit directed-abuse task. No source body, aggregation rule or usable post-isolation support was verified for Sentinel.

These are source-documentation findings, not claims that either dataset is admitted or interchangeable with CAD.

## Proposed v2 design direction

- Use a new private study/model namespace and new public v2 reports. Preserve v1 source bytes, reservation, unavailable reports and all existing URL/paired-study records.
- Carry forward the current CAD label/context contract, protected test ownership, component construction and numerical support gates. Unknown authors remain an independence limitation.
- Make class/component/fold support hard allocation constraints; keep 70/15/15 row/class proportions as balancing targets. Define one bounded, reproducible selection and tie policy in the written specification. Use counts only, with no model accuracy, test scores, seed retries or hand-picked assignments.
- Freeze the outer allocation and supported calibration-fold membership together before fitting. Bind their identities into training, calibration, artifact checking and final-evaluation receipts. Keep unavailable outcomes distinct from proven infeasibility and resource timeout.
- Reuse the fair target-only/context CPU comparisons and existing laptop limits. Retain the conditional neural pilot; count feasibility does not establish neural coverage, GPU fit or any full-model result.
- Preserve separate calibration-quality gates: adequate fold counts do not establish a positive sigmoid slope, non-worsening out-of-fold Brier score or valid displayed confidence.
- Keep the protected test unscored until all new study/model/final-access bindings are frozen. Do not activate learned live warnings as a consequence of passing these support checks.
- Keep permissioned human challenge collection and genuine paired-message review as parallel team tasks. Do not turn the assistant into either of the required independent human reviewers.

## Review boundary

The user approved this direction on 2026-10-18. The focused [v2 specification](superpowers/specs/2026-10-18-sentinel-context-harm-v2-design.md) is written and awaiting review before an implementation plan. The user's existing preference for inline implementation with one independent final review carries forward. Product changes, new frozen splits, fitting and final evaluation remain pending those reviews.

## Documentation evidence

SciPy's [official 1.17.0 `milp` reference](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.optimize.milp.html) documents integer variables, bounded linear constraints, time/node limits and distinct solver termination states. The installed patch version 1.17.1 executed the probe successfully; the corresponding 1.17.1 documentation URL returned 404, so no exact-patch documentation match is claimed. This probe uses the already installed dependency and changes no package pin.

The [approved year-long design](superpowers/specs/2026-10-05-sentinel-year-long-design.md), [implemented harm design](superpowers/specs/2026-10-13-sentinel-context-harm-design.md) and [v1 delivery record](context-harm-delivery-record.md) establish the existing intent, support rules and protected-study limits.
