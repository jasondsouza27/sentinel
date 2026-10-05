# Sentinel

**Sentinel: An Explainable Social Media Safety Assistant for Suspicious Profiles, Phishing Links, and Harmful Content**

Sentinel is a local college-project prototype. A user submits a message, URL, conversation excerpt, or available profile facts. It returns separate fraud, harmful-content, and profile assessments, with observed evidence, unavailable checks, and an action to consider. The browser extension uses the same API as the web app. Analysis is not saved until the user chooses **Save case**.

## Run locally

Requires Python 3.10 or newer. No Python packages or cloud account are needed for the prototype.

On Windows, double-click [start-sentinel.cmd](start-sentinel.cmd). It uses the bundled Python available on this computer, or a separately installed Python if present.

```powershell
python -m sentinel.server
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). The server listens only on your own computer. To run tests:

```powershell
python -m unittest discover -s tests -v
```

For the web client's asynchronous analysis and saving checks, developers can also use Node.js 22 or newer. No npm packages are required; Node is not needed to run Sentinel:

```powershell
node --test tests/web_client.test.mjs
```

The [web-app browser test record](docs/web-app-smoke-test-2026-10-05.md) documents the checked workflows, fixes and remaining browser checks.

The web app can analyze a message alone, a URL alone, or both together. Expand **Have profile details?** to supply available counts and an organisation domain. A pasted profile URL does not give Sentinel access to private profile or posting history.

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

The next [local review batch](data/curation/legitimate_sms_candidates.csv) adds 18 potential legitimate SMS candidates from the UCI and NUS corpora. These are unreviewed, contain no Sentinel labels, and have not been added to the empty intake. The [source audit](docs/real-dataset-source-audit.md) records the selection and its limits; follow the [next steps](docs/next-steps.md) before training.

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
- `sentinel/storage.py` and `sentinel/server.py` — local cases and shared API.
- `web/` and `extension/` — user interfaces.
- `tests/` — automated checks.
- `docs/` — implementation and research guidance.

The six-month research and pilot schedule remains to be carried out by the project team. The software and presentation provide a working starting point; no real-world performance or user-study result is claimed here.
