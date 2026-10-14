# Sentinel

**Sentinel: An Explainable Social Media Safety Assistant for Suspicious Profiles, Phishing Links, and Harmful Content**

Sentinel is a **year-long engineering major project** combining applied machine-learning research with a local social-media safety application. A user submits a message, URL, ordered conversation, or available profile facts. It returns separate fraud, harmful-content, and profile assessments, with observed evidence, unavailable checks, and an action to consider. The browser extension uses the same API as the web app. Analysis is saved only when the user chooses **Save case**.

The [approved year-long design](docs/superpowers/specs/2026-10-05-sentinel-year-long-design.md) guides the balance between ML experiments and application development. The implemented research infrastructure covers verified sources, group-isolated datasets, bounded training, calibration, checked local artifacts and guarded final evaluation. See the [URL ML reproduction guide](docs/url-ml-workflow.md), [paired-study workflow](docs/paired-study-workflow.md) and [conversation/harm workflow](docs/context-harm-workflow.md).

## Current status

Updated **2026-10-14**. The conversation/harm software milestone is implemented, independently reviewed and integrated into the repository's default branch, `codex/sentinel`.

| Area | Implemented | Current research/release status |
|---|---|---|
| Web app and extension | Explicit content checks through one shared API; evidence, uncertainty and suggested actions | Local application available; actual Chrome toolbar/context-menu testing remains pending |
| Conversation investigation | Ordered linear/reply turns, target selection, preceding-context coverage, signed assessment saving, reopen, feedback, export and deletion | Later turns are excluded from the selected target's context; edits require another check before saving |
| URL detection | Audited URL-v1/v2/v3 studies, CPU classifiers, calibration and protected evaluation | URL-v3 measured; its false-positive results block live learned warnings |
| Paired message–link detection | Evidence-bound two-reviewer workflow, group splits, CPU branch/fusion training and single-use evaluation | Real intake remains empty; no paired phishing performance is claimed |
| English directed-abuse detection | Verified CAD admission, protected cohorts, CPU/conditional encoder tooling, calibration and final-evaluation controls | Fixed CAD allocation fails three support gates; no real harm model or final score |
| Profile assessment | Indicators from supplied profile facts | Bot likelihood and identity remain unestimated; no trained profile model |

The local app currently provides rule observations and explicitly marks unavailable learned checks. The research models have not been released as live warnings.

**Recorded verification:** 477 Python tests and 61 client tests passed with zero skips. One independent review found three Important issues, all corrected with failing-then-passing regressions: absolute download deadlines, shared training admission across processes/model families, and verification of the encoder runtime actually executing each worker. The same reviewer cleared the delivery records. The primary-folder HTTP check verified signed save, reopen and deletion.

Clean-clone source/admission reproduction passed with all 17 pinned ML/data packages. It reused checksum-verified acquisition bytes after the fresh download failed; a second fresh-download success and actual CUDA performance remain unverified. Details and report hashes are in the [delivery record](docs/context-harm-delivery-record.md) and [aggregate verification](output/research/context-harm-v1/verification.json).

## Research progress

The first actual URL-only benchmark is complete: **97.07% F1**, **99.80% recall** and
**4.35% false-positive rate** on 23,534 domain-held-out URLs. **The url-v1 model remains
research-only:** all legitimate source URLs are www HTTPS homepages with empty paths;
staged benign documentation links are falsely flagged. These scores do not establish
live reliability. Read the [final model card](output/research/url-ml-v1/model-card.md)
and [aggregate results](output/research/url-ml-v1/evaluation.json). Broader URL formats are now tested in URL-v3 below; independent source and temporal validation remain unmet.
The standard launcher keeps the learned model disabled. The [delivery record](docs/url-ml-delivery-record.md) documents the independent review, its three corrected findings, 78 passing Python tests and 12 web-client checks.

The approved [URL-v2 data/robustness plan](docs/superpowers/plans/2026-10-07-sentinel-url-v2-data.md)
now has a pinned range importer, complete observation provenance, connected-component
protocol, compatible bounded training, format control and frozen source-specific evaluation.
The real importer acquired **666,315 observations** and audit retained **660,130 canonical
URLs** with 43.7 MiB of journal-counted metadata/range payload, without downloading dataset HTML.
Historical redirect-body bytes were unmetered; the [delivery record](docs/url-v2-delivery-record.md)
qualifies that receipt and documents the corrected importer. The frozen
200,000-row development set has only **6 benign query-bearing URLs**, below the required 30,
so **v2 training is blocked**. No v2 accuracy, artifact or improvement over v1 is claimed.
See the [research card](output/research/url-ml-v2/model-card.md), [aggregate status](output/research/url-ml-v2/research-status.json),
[delivery record](docs/url-v2-delivery-record.md) and [v2 reproduction guide](docs/url-v2-workflow.md).
Official ISCX access and authenticated chronology remain unavailable. Learned warnings stay disabled.

The completed [URL-v3 study](docs/url-v3-workflow.md) adds a pinned Mendeley URL-label source to the preserved PhreshPhish data, audits 671,521 canonical URLs and trains a CPU candidate on a frozen 200,000-row development set. The selected character TF-IDF model reached **0.927 F1 / 5.76% false-positive rate** on 166,369 primary URLs and **0.839 F1 / 22.39% false-positive rate** on 4,348 supplemental URLs. Legitimate query URLs were falsely flagged 13/52 and 27/44 respectively; a synthetic `example.com` check also flagged incorrectly. This is a useful research result, **not a deployable warning model**. The supplemental track is group-held-out from a development source, not independent-source or temporal validation. See the [aggregate evaluation](output/research/url-ml-v3/evaluation.json), [model card](output/research/url-ml-v3/model-card.md) and [delivery record](docs/url-v3-delivery-record.md). Learned live warnings remain disabled.

The [paired message–link study workflow](docs/paired-study-workflow.md) now provides an evidence-bound two-reviewer packet, counts-only readiness audit, sealed four-way group split, CPU message/URL/fusion training, paired held-out evaluation and an optional research-only API card. **The real paired phishing study remains unavailable:** the intake has no admitted cases. Synthetic software tests are not research findings, and no learned paired warning is active.

The [English conversation/harm workflow](docs/context-harm-workflow.md) adds ordered
linear/reply turns, target selection, preceding-context coverage and exact signed
assessment saving. Its research tooling includes verified CAD ingestion, protected
cohorts, bounded sparse CPU models, conditional compact-encoder training, calibration,
checked artifacts and single-use final evaluation. **The real CAD allocation is
unavailable:** training has 175 positive cases rather than 200; validation and
calibration have five and eight components rather than ten. No real harm model or
final score is claimed. See the [research card](output/research/context-harm-v1/model-card.md),
[status](output/research/context-harm-v1/research-status.json) and
[browser verification](docs/context-harm-web-smoke-test.md). Existing rules remain usable.

The immediate harm research milestone is a reviewed data/protocol revision that
meets training and independent-component support while preserving held-out
ownership. Keep the current protected test unscored; changing seeds or lowering
gates to obtain a favourable result is outside the approved study. Permissioned
human challenge collection and paired message–link review can proceed alongside
this work. See [next steps](docs/next-steps.md).

## Run locally

The local application requires Python 3.10 or newer. Its default mode needs only
the Python standard library and no cloud account. Run commands from your project
checkout; keep private research data outside OneDrive. Research environments and
the full test suite have additional requirements described below.

On Windows, double-click [start-sentinel.cmd](start-sentinel.cmd). It uses the bundled Python available on this computer, or a separately installed Python if present.

```powershell
python -m sentinel.server
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). The server listens only on your own computer.

The web app can analyze a message alone, a URL alone, or both together. Enable the
conversation editor to add ordered turns, select a target and specify replies.
Only preceding context is considered. **Save case** preserves the exact reviewed
input and assessment; editing the conversation requires another check. Save
receipts expire after 15 minutes or a server restart, so recheck when prompted.

Expand **Have profile details?** to supply available counts and an organisation
domain. A pasted profile URL does not give Sentinel access to private profile or
posting history.

## Research setup and verification

Full Python verification and CPU research use **Windows CPython 3.11.17** and the
17 unique package pins across the existing ML/data locks. Use that exact
interpreter when creating the isolated environment below:

```powershell
python -m venv .venv-ml
& .\.venv-ml\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-ml-win-py311.lock.txt -r requirements-url-data-win-py311.lock.txt
& .\.venv-ml\Scripts\python.exe -m pip check
& .\.venv-ml\Scripts\python.exe -m unittest discover -s tests -v
```

On the development computer, the existing `.venv-url-v2-check` environment
already supplies those dependencies and can be used instead. These CPU locks
contain exact version pins; the optional encoder has its own hash-pinned lock
and guarded setup in the [harm workflow](docs/context-harm-workflow.md). The
recorded full suite ran without a neural environment or real CUDA training.

For the conversation editor, web-client and extension checks, use Node.js 22 or
newer. No npm packages are required; Node is not needed to run Sentinel:

```powershell
node --test tests/web_client.test.mjs tests/extension_popup.test.mjs tests/conversation_editor.test.mjs
```

The [conversation browser record](docs/context-harm-web-smoke-test.md) documents
actual target/reply editing, exact saving/reopening/export, safe text display,
deletion, offline recovery and layout checks. The [earlier browser record](docs/web-app-smoke-test-2026-10-05.md)
preserves the previous checks. Synthetic pipeline tests demonstrate software
behaviour; their scores are not findings about real detection quality.

## Chrome extension

1. Start the local server.
2. Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select the `extension` directory.
3. Select text and click the Sentinel toolbar button, then **Use selected text** and **Check with Sentinel**. You can also right-click selected text or a link and choose a Sentinel action.

The extension checks content only when you invoke it. Its permissions cover the active tab after a user action and the local API at `127.0.0.1:8787`. If the context menu cannot open the popup automatically, click the toolbar button; the selected text or link will be waiting there.

Before a college demonstration, complete the [extension smoke test](docs/extension-smoke-test.md) in Chrome and record the result.

## Reputation data and research model

The app does **not** download or visit submitted URLs. Without a reputation CSV, it explicitly reports that the feed is unavailable. If the team obtains a current PhishTank CSV, pass its local path:

```powershell
python -m sentinel.server --phishing-feed data/phishing-feed.csv
```

The feed should have a `url` column and may have `verified` and `online` columns. Only rows marked `yes` for these fields are loaded. A link absent from the feed is **unlisted**, not safe. Follow the source's access terms and update policy before using its data.

`sentinel.research` trains three reproducible multinomial Naive Bayes baselines from one CSV of **paired messages and URLs**. It reports held-out precision, recall, F1, false-positive rate, and prediction latency. `data/example_pairs.csv` contains invented `.example` cases solely to test the pipeline; its metrics are not project findings. Use reviewed, permissioned cases from the local [collection workflow](docs/collection-workflow.md) for the actual experiment. After finalizing and freezing the dataset, use `curate-sentinel.cmd evaluate data\curation` for the hash-verified final result. Separately, you can train a prototype model from the reviewed training file; its report is a training-only validation result:

```powershell
python -m sentinel.research data/curation/locked/train.csv --report-out data/train-validation.json --model-out data/model.json
python -m sentinel.server --model data/model.json
```

The required CSV columns are `case_id,message,url,label,domain_group`; a reviewed dataset may also include `campaign_group`. `label` is `1` for a suspicious or phishing request and `0` for a legitimate request. `domain_group` groups destination domains that must stay in the same split; the evaluator also groups domains found in message text, duplicate wording after removing URLs, and any manually assigned `campaign_group`. It removes URL spans from message-only features. The deployed model vote is labelled uncalibrated; no numeric confidence is shown. See [evaluation protocol](docs/evaluation-protocol.md) before reporting results.

The first [real-pair exploratory benchmark](docs/first-research-benchmark.md) uses a public email spam/ham corpus. Its importer retains unambiguous single-link messages, audits exclusions, and runs five fixed group-held-out splits. On this corpus, combining message and URL tokens showed a small, inconsistent F1 gain over message-only input. The source labels are spam/ham, not verified phishing, so this model is **not** used for live phishing warnings. Aggregate [audit](output/research/assassin_audit.json) and [evaluation results](output/research/assassin_evaluation_5seeds.json) are included; raw mail and derived paired CSV stay local.

For the actual phishing study, use the [collection and two-reviewer workflow](docs/collection-workflow.md). It starts with an empty local intake file, separates reviewers' labels, requires resolution of uncertain cases, and freezes a test set with file hashes before evaluation. The workflow can be run with [curate-sentinel.cmd](curate-sentinel.cmd) on this Windows computer.

The [real-dataset source audit](docs/real-dataset-source-audit.md) identifies a peer-reviewed SMS phishing release with original message–link pairs. A local importer selected 100 unreviewed candidates for the team. It supplies phishing candidates, but no linked legitimate comparison group; the main experiment still needs independently verified legitimate pairs and team review.

The private local review batch at `data/curation/legitimate_sms_candidates.csv` adds 18 potential legitimate SMS candidates from the UCI and NUS corpora. It is not included in the repository. These are unreviewed, contain no Sentinel labels, and have not been added to the empty intake. The [source audit](docs/real-dataset-source-audit.md) records the selection and its limits; follow the [next steps](docs/next-steps.md) before training.

## Scope and privacy

- Message and URL rules are indicators, not proof. Low observed concern never means confirmed safe.
- Harmful-content results flag phrases for human review. A single message cannot establish cyberbullying, speaker intent, or a repeated pattern.
- Profile checks use only supplied facts. High posting volume or an unusual follow ratio alone cannot establish a fake or automated account. Bot likelihood remains unestimated until an appropriate model is trained and validated on obtainable features.
- Saved cases stay in a local SQLite file at `data/cases.db`. Use **Delete** to remove a case or **Export JSON** to get a report. Feedback is stored locally and is never fed into training automatically.
- The app accepts browser requests from its own local origin and Chrome extension origins. It is designed for a personal laptop demo, not public internet hosting or multi-user accounts.

## Project layout

- `sentinel/analysis.py` — assessment rules and explanations.
- `sentinel/research.py` — paired-data baseline training and evaluation.
- `sentinel/curation.py` — local collection, independent review, adjudication, and locked test split.
- `sentinel/url_ml/`, `sentinel/url_v2/` and `sentinel/url_v3/` — URL research, source admission, protected studies and guarded inference.
- `sentinel/paired/` — evidence-gated four-way paired study, CPU fusion models and guarded optional service.
- `sentinel/context_harm/` — conversation contracts, CAD admission, protected cohorts, bounded CPU/encoder workers, calibration and research evaluation.
- `sentinel/assessment_receipts.py` — signed input/result receipts for exact reviewed-case saving.
- `sentinel/storage.py` and `sentinel/server.py` — local cases and shared API.
- `web/conversation.js` — target/reply conversation editor.
- `web/` and `extension/` — user interfaces.
- `tests/` — automated checks.
- `docs/` — implementation and research guidance.

The proposed twelve-month schedule is in the year-long design. The original
implementation plan and presentation describe the starting prototype. URL
research, the paired-study software path and conversation/harm research tooling
are implemented. Remaining work includes supported real harm training and
evaluation under a revised protocol, permissioned paired/challenge collection,
reviewed release decisions, profile ML, team investigation workflows, dashboard
expansion and the voluntary user pilot. No paired phishing performance, trained
harm quality or user-study result is claimed here.
