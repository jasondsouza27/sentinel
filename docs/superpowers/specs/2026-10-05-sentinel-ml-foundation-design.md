# Sentinel subproject A: ML foundation and URL detector

Date: 2026-10-05. Status: **draft for written review**. Parent: [year-long design](2026-10-05-sentinel-year-long-design.md). This specification defines the first buildable subsystem; it is not an implementation plan or a claim that a model has been trained.

## Outcome and boundary

Deliver a reproducible, evaluated URL classifier and a stable inference adapter that later message/fusion and application work can consume. Start on CPU so the first milestone does not depend on neural GPU setup or completion of the paired-message collection.

Inputs are HTTP(S) URL strings. Outputs are the model assessment, observed URL properties, uncertainty/limitations and artifact provenance. No arbitrary submitted website, redirect, DNS endpoint or page source is fetched. An HTTPS scheme, unusual character or low model score alone never proves safety or fraud.

This milestone does not train the message, harm or profile modules, redesign the dashboard, deploy publicly, or answer the message-plus-URL hypothesis. Human paired-case admission can continue independently using the current [collection workflow](../../collection-workflow.md).

## Source and label contract

First candidate: [UCI PhiUSIIL Phishing URL (Website)](https://archive.ics.uci.edu/dataset/967/phiusiil%2Bphishing%2Burl%2Bdataset). UCI lists 235,795 records, mixed URL/webpage features, and CC BY 4.0 terms. Download only the original archive from the documented repository, record retrieval time and archive/member hashes, and audit the actual file before accepting these as local counts.

Sentinel's label is `1 = phishing_url`, `0 = legitimate_url`. PhiUSIIL uses the opposite encoding; conversion must explicitly map source `0 -> 1` and `1 -> 0`, with mapping counts in the audit. Labels remain source-provided labels, not newly verified live-site truth. Do not infer dates or assign labels to unresolved rows. No sensitive URL tokens or raw training rows enter Git.

The canonical record has: stable source-row reference, original URL in controlled storage, model-input URL, canonical label, source name/hash, grouping key, optional authentic source date and exclusion status/reason. Case/source IDs support traceability only and cannot become features. Record exact duplicate pairs, conflicting labels, invalid or oversized URLs, accepted counts and class/domain-group balance. Exclude unresolved conflicts rather than keep whichever row arrives first.

Keep the raw source immutable. An adapter produces an audited derived file and manifest; it refuses accidental overwrite of a different dataset version. Repository documentation contains attribution and aggregate counts; redistribution of raw content is a separate decision. The manifest points to local files without exposing user-specific absolute paths in published metadata.

## URL normalisation, grouping and features

Preserve path/query spelling for modelling; canonicalise only scheme/host case and audited equivalent representations. Keep display text separate from parsing output. Apply IDNA handling explicitly and retain flags for Unicode/punycode. Reject unsupported schemes and invalid hosts without contacting the destination. URLs above the 2,048-character cap are excluded from this model's training/benchmark and reported unsupported at inference, with exclusion counts.

Use a versioned, offline Public Suffix List resolver with private suffix boundaries for registrable-domain grouping. Record the snapshot hash and reuse terms. For IP hosts, group by normalised address. Group equivalent URLs and all retained rows of the same registrable domain together. Report largest components and both-label distribution; do not split a large domain group just to obtain prettier proportions. Any unsupported parsing/domain case is audited and either conservatively grouped or excluded under a declared rule. [Public Suffix List](https://publicsuffix.org/list/)

Baseline branches:

1. Fixed Phase 0 URL rules as a non-ML reference on supported inputs, with reputation and message inputs disabled. For this benchmark only, map any structural URL warning to `flag = 1` and no warning to `flag = 0`; publish this mapping rather than interpret it as confirmed phishing/legitimacy.
2. URL character TF-IDF with logistic regression, using training-only vocabulary and a declared feature cap; start with character n-grams of lengths 3–5 and at most 50,000 sparse features, subject to the memory pilot.
3. Derived lexical features with a depth-limited `HistGradientBoostingClassifier`: lengths, host-label counts, digit/punctuation ratios, IP-host and user-info flags, encoding counts, scheme and path/query structure. Disable the estimator's automatic random validation split; choose bounded iteration/depth settings using the declared validation groups. Feature semantics and missing values are versioned. [scikit-learn estimator documentation](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html)

Do not use supplied webpage columns, `FILENAME`, labels, similarity-to-legitimate-reference features, population-level TLD legitimacy scores or any feature whose training-only computation and inference availability cannot be demonstrated. Derive structural features from the input URL so the same code executes in training and serving. A feature such as HTTP or punycode is an observation, not a stand-alone phishing verdict.

Predeclare a small bounded search budget: at most six configurations per learned branch on validation data. Preserve config/seed records, failed runs and resource measurements. Choose the model using recall under the validation false-positive-rate budget in the parent design, with precision/F1 and runtime as reported trade-offs. If no useful threshold meets the budget, report that limit; do not disguise near-total abstention as high accuracy.

## Splits, calibration and reporting

Create frozen train/validation/calibration/test manifests, targeting 70/10/10/10 by domain-group components. Use the same eligible rows and split for both learned branches. Approximate proportions are acceptable when grouping prevents exact stratification; each partition must contain both labels or the run stops with a clear diagnostic. A small deterministic group-selected pilot is for resource checks only and is excluded from final claims.

All learnt preprocessing uses training data only. Hyperparameters and an uncalibrated decision threshold are selected on validation data. Fit a simple sigmoid calibration on the separate calibration partition. Translate the selected raw-score threshold through that monotonic increasing calibration mapping; do not reselect a threshold by inspecting calibration or test labels. Report calibration sample sizes and reliability limits. If calibration cannot be fitted meaningfully, including an inconsistent score orientation, omit numeric confidence and keep the uncalibrated score/selected threshold internal.

Freeze the chosen pipeline, threshold, label map and calibration before final test evaluation. The report includes source and exclusions; partition/group counts; confusion matrices; precision, recall, F1 (positive-class and macro), PR-AUC and false-positive rate; Brier score/reliability where applicable; 95% group-bootstrap intervals; cold/warm latency; peak memory; and representative redacted error categories. Bootstrap whole domain groups rather than pretending correlated URLs are independent observations; flag insufficient class/group support.

Distinguish historical source evaluation from contemporary deployment. A second independently audited source or authentic time-held-out set is desirable later; do not claim generalisation to new years, languages or platforms from one source. Report positive predictive value under stated prevalence scenarios separately from balanced-benchmark precision.

## Artifact and inference contract

Store one artifact directory per immutable version. Include pipeline weights, preprocessing, label/schema/normalisation versions, decision threshold, calibration status, model card, source/split/config hashes, dependency versions, seed and Git commit. Derived reports and audit metadata must avoid raw URL tokens. Raw data and large binary artifacts remain outside source control; use local artifact paths with an explicitly configured active version.

Use only trusted locally produced model files. Hash verification catches corruption and wrong versions; it does not make arbitrary pickle/joblib content safe to load. Do not provide an upload endpoint for executable model artifacts. A future distributable artifact format must have its own audited loader.

The adapter accepts a supported URL and returns a task-specific result containing state, label/decision, observed evidence, model version, calibrated probability only when eligible, and limitations. An unsupported URL returns `not_assessed` with the reason. A missing, incompatible or corrupt artifact returns `unavailable`, and the existing rules can still be displayed separately. No exception or missing artifact turns into a legitimate/safe label.

Numerical scores and explanatory feature weights are distinct from observed evidence. For a linear model, character-feature contributions may explain its score, but those fragments alone are not a threat rationale. Show inspectable structural observations and clear limitations; never invent a domain reputation, ownership history or webpage behaviour.

Phase 0 continues to launch without ML packages. Only an explicit artifact configuration enables this adapter. Preserve the existing research JSON/model format for the baseline rather than reinterpret it as the new calibrated artifact. Loading the URL artifact must not activate a combined-message model automatically.

## Resource and reproducibility requirements

Use a dedicated Python 3.11 environment with locked compatible NumPy/scikit-learn/feature-parser dependencies. PyTorch is not required for this first CPU subsystem. Pin the suffix snapshot and write setup/run instructions for Windows, with paths handled safely when the username contains spaces.

Run one training job at a time. Measure process peak RAM and elapsed time on this laptop; the standard CPU run targets at most 8 GiB RAM. Keep character features sparse and avoid densifying the URL matrix. If the source/run exceeds the target, reduce the declared feature cap or publish a deterministic group-sampled benchmark scope before final evaluation. Do not silently alter the test distribution after viewing results.

The implementation plan will define commands for source audit, frozen split creation, training, calibration, final evaluation and standalone prediction. Re-running with the same source/config/manifests must preserve row assignments and model decisions within declared numerical tolerances. Run records include failures and exclusions, not just the best score. No network is required during training or inference after source/dependency acquisition.

## Acceptance cases

The milestone is ready when:

- The archive-to-derived-data audit is traceable, attribution is present, and label inversion is demonstrated on both classes.
- Domain/private-suffix, duplicate and conflict handling prevents cross-partition leakage; transformations and calibration use their declared partitions.
- Both learned baselines and Phase 0 rules have results on the same frozen eligible test set; negative findings and resource failures remain visible.
- Export/reload preserves decisions and model versions; unsupported URLs and absent/corrupt/incompatible artifacts produce explicit states.
- Malformed input, IP/IPv6 hosts, IDN/punycode, user-info, encoded characters and long URLs have documented behaviour, without outbound destination requests.
- A clean environment can reproduce the audit, split and prediction from documented inputs, and the model card states scope, label meaning, limitations and measured latency/memory.
- The adapter is opt-in and the existing local app, case workflows and paired baseline tools retain their supported behaviour.

Tests should focus on these boundary and leakage cases. Synthetic fixtures establish software correctness only. Passing them is not evidence of phishing detection quality; final claims require the actual frozen evaluation.

## Next handoff

After written approval, prepare the implementation plan for this subsystem only. It will turn these requirements into concrete files, commands and verification tasks. The overall research/application scope remains in the parent design; unresolved paired-data availability does not block this standalone first milestone.
