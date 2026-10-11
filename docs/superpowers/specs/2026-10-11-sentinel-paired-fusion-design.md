# Sentinel: paired message–link evidence and fusion study

Date: 2026-10-11. Status: **proposed for user review**. This refines subproject B of the [approved year-long design](2026-10-05-sentinel-year-long-design.md). It does not report a trained phishing model or a completed paired experiment.

## Purpose and current evidence

The research question is whether a model using the wording of a message **and the destination actually linked by that same message** detects phishing requests better than models using either input alone. The binary study distinguishes `phishing_request` from `verified_legitimate_request`; ordinary spam and uncertain cases are outside that binary label. The result must be useful to the investigation application only if its coverage and error rates support that use. This subproject produces an auditable paired dataset, three fair comparisons, a model card, and a guarded inference adapter; the human collection campaign runs alongside the software work.

The existing local workflow has an empty intake, 100 unreviewed NC State phishing candidates, and 18 unreviewed potential legitimate SMS candidates. The current `sentinel.research` comparison is a Naive Bayes engineering baseline, not a phishing finding. Its SpamAssassin run uses old email **spam/ham** labels. The [source audit](../../real-dataset-source-audit.md) and [benchmark record](../../first-research-benchmark.md) explain why NC State alone, PhishNet Dataset 2, UCI/NUS, and the Mishra–Soni SMS set do not yield a credible paired phishing-versus-verified-legitimate test. In particular, the latter exposed only two ham messages with recognizable links. A URL-only labeled dataset cannot create paired messages by attaching unrelated text.

## Approaches and decision

| Approach | Advantage | Cost or failure mode |
| --- | --- | --- |
| Merge public phishing messages with unrelated ham or URL corpora | Fastest way to fill rows | Source, period, channel and labeling become shortcuts; cannot answer the question |
| **Evidence-gated collection plus an offline fusion pipeline** | Preserves authentic pairs, label meaning and a fair comparison; selected | Requires weeks of human collection and review; may produce a documented infeasibility result |
| Start with a large neural fusion model or live URL reputation | Impressive demonstration | Data and calibration are still missing; service availability and external-data leakage complicate claims |

Keep the existing explicit-click app and extension. Do not introduce a crawler or open submitted links on the server. Do not connect URL-v3 to live warnings: its supplemental false-positive rate and legitimate query errors still block that release.

## Data acquisition and review

Use the existing local, Git-ignored `data/curation` workflow. A candidate may enter intake only when the original message and exact linked destination are observed together, reuse is permitted or the sender supplies consent, private identifiers/tokens are removed or the case is excluded, and the source is traceable. Record the original observation date only when supplied by the source; `collected_on` remains the date the team obtained the case. Never infer a sending date from dataset publication. Public-source class labels and reputation lookups are provenance, not final Sentinel labels.

For the needed legitimate class, recruit consented examples of authentic linked notices or posts and retain an **independent verification record** that ties the actual message to its claimed sender or purpose: for example, verification through an already known official channel. An official page merely containing the same link, a familiar hostname, absence from a phishing feed, a `ham` tag, or a successful page load is insufficient. Recruit phishing examples through a comparable channel and collection period wherever possible, so source identity does not perfectly predict the label. Preserve uncertain, ordinary-spam and unverifiable cases as `?` or exclude them. No examples are invented to fill a target.

Add a private admission ledger keyed by `case_id` with an opaque evidence ID, evidence type, original-observation date if known, source hash/version, permission basis and redaction decision. Do not store screenshots, consent records, message text or URL tokens in public reports or Git. Provide each of two independent reviewers a case packet with the message, linked URL, and access to class-neutral verification material, but hide source-provided labels. The reviewer records a label and concrete reason; disagreements and `?` require adjudication. Preserve the existing finalization hashes, and refuse silent replacement of any prepared or finalized batch. Admission, review and finalization remain human decisions; feedback from the app never becomes training data automatically.

Before freezing, emit a **counts-only feasibility report**: reviewed cases per label, source, channel and available date range; independent domain/campaign/wording groups; excluded/uncertain cases; source–label and channel–label cross-tabs; repeated URL or campaign overlap; and whether a usable held-out split can be formed. If source identity or collection period perfectly predicts class, mark the primary study **not claim-ready**; any software check on those rows is exploratory only. The approved planning target is 2,000 reviewed pairs, at least 1,000 per class, with at least 100 per class and 30 distinct domain groups in the final test. These are gates for the planned primary study, not proof of representativeness. If the team cannot obtain verified legitimate pairs, the final scientific outcome is **paired study unavailable**, while separate module work continues.

## Split and model contract

The release pipeline consumes only finalized, hash-verified pairs. Build connected groups from destination registrable domains, any other URL in the original message, documented campaign IDs, and normalized URL-stripped message wording. A group cannot cross partitions. Choose and record one training/validation/calibration/test assignment before fitting models. The final test is sealed from feature selection, threshold choice, source selection, calibration and examples used in demos. If a domain/campaign group is too large to preserve both classes across partitions, fail with a reason; do not weaken the isolation silently. The existing two-way locked baseline remains separately reproducible and is not overwritten.

Fit three branches on identical eligible pairs and the same partitions:

1. **Message-only:** remove all URL spans before feature extraction. Use the existing Naive Bayes baseline and a TF-IDF linear classifier.
2. **URL-only:** use only the actual paired destination string with lexical features and a bounded CPU classifier. URL-v3 may be documented as an external exploratory comparator only after an overlap/external-data audit; it is not the primary URL branch and cannot see final-test domains through its training corpus.
3. **Combined:** compare early message/URL feature concatenation with learned late fusion. Generate branch scores for the fusion learner out of fold within training groups; never fit fusion on branch predictions made for their own training examples. Missing message or URL must yield explicit reduced coverage rather than an invented feature value or an unsupported phishing claim.

Select a decision-score threshold on validation under the approved 5% validation false-positive-rate budget. Fit a probability calibrator on the separate calibration set if there is enough data; it affects displayed probabilities, not the frozen decision threshold. Run final inference once on test. If calibration is too sparse, suppress numerical confidence and record it as unavailable. No test-driven change to features, thresholds or cohort assignment is allowed without a new version and a newly reserved final set. Cap training memory and worker count for the Ryzen 7 / 16 GiB machine; a compact encoder is optional only if a pilot fits these resources and has a fair CPU baseline.

## Evaluation and application boundary

Report confusion counts, precision, recall, F1, macro F1, PR-AUC, false-positive rate, coverage/abstention, calibration quality where applicable, response time and peak memory for all three branches. Primary comparison is held-out recall at the validation-selected false-positive-rate constraint. Use paired case-level differences and 95% intervals bootstrapped by connected group; mark intervals unstable when groups or positive cases are sparse. Show breakdowns by source, channel, date availability, URL pattern and unseen domain; include false-positive examples only after redaction and permission. A gain over a weak URL branch alone is insufficient: compare combined against both individual branches, and discuss any source or prevalence bias.

The offline artifact records dataset and split hashes, training code/dependency versions, feature sets, thresholds, calibration status, model sizes, latency and a model card. The shared analysis API gets a versioned optional adapter that reports category, observed warning signs, missing checks, uncertainty and recommended verification steps. It remains disabled by default until the paired study and independent review justify activation. The existing rules can still report observations without presenting them as a validated learned phishing verdict. The web app and extension consume the same API response; no new external service is required for the first study.

## Delivery sequence and acceptance

1. Improve the review packet and add the private evidence ledger plus counts-only data-readiness report, reusing existing curation contracts. Test that missing evidence, duplicate pairs, leaking groups and source-confounded collections are rejected or flagged.
2. Implement a synthetic-fixture-tested, hash-pinned four-way split and offline baseline/linear/lexical/fusion pipeline. The fixture proves software behavior only; no synthetic metric appears as a research result.
3. Admit and double-review real, permissioned pairs; run source-balance and leakage audits. Freeze a final set only after the readiness gate passes. If it does not, publish the audit and keep model evaluation and live adapter unavailable.
4. Run the three-way experiment on the sealed set once, write aggregate report and model card, then independently review methodology and application behavior. Add the guarded adapter only if evidence supports it.

Acceptance requires reproducible commands from a clean clone, no raw private cases in Git, passing tests for intake/review/split leakage and out-of-fold fusion, a clear unavailable outcome when data gates fail, and no live learned warning before release review. The team can deliver the software scaffold promptly; the scientific result depends on human collection and independent verification and has no promised completion date from code alone.
