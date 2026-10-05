# Sentinel evaluation protocol

## Research question

Does analysing the message and its linked URL together improve suspicious-message detection compared with either input alone?

## Dataset and labels

Collect or lawfully obtain paired message–URL cases. Record the original pair, label, source, collection date, and annotation rationale. Do not attach a URL from one dataset to an unrelated message from another. Remove personal identifiers and get permission for any private messages. Use `1` for a suspicious request and `0` for a legitimate request. Have two team members label ambiguous cases independently, then resolve disagreements before training. Keep a separate, small set of ambiguous cases for error analysis.

Use the [local collection workflow](collection-workflow.md) to keep the two reviews separate, adjudicate unclear cases, and lock a test set. A legitimate label should have independent source verification; absence of warning signs alone is insufficient.

Preserve the source's original label meaning. A corpus labelled spam/ham tests spam detection, not verified phishing. Check the data licence and avoid publishing raw messages that contain personal details. Only report paired cases where the link was present in the original message or can be traced to the same post or email.

CSV columns used by the baseline tool: `case_id,message,url,label,domain_group`, with optional `campaign_group`. `domain_group` should identify the destination domain; use `campaign_group` for confirmed related cases across domains. A held-out test set must contain both labels. The provided split keeps the same domain, campaign group, and repeated message wording together after removing URL spans. Before publishing results, also inspect paraphrases and unknown campaigns manually to prevent hidden leakage. Record class balance and sample counts.

## Experiments

Run the same train/test split for message-only, URL-only, and combined baselines. Remove all URL spans from message-only features; keep only the corresponding link's features in URL-only. Group every visible linked domain and duplicate message together before splitting, and report train/test class balance. Report precision, recall, F1, false-positive rate, confusion counts, and per-case prediction latency. Compare both macro and positive-class results if class imbalance is substantial. Repeat on several fixed seeds or use a second independent time-based test set once enough data exists. Do not tune on the held-out test set. Save the CSV version, random seed, model file, and report JSON.

Evaluate the local reputation lookup separately from the learned classifiers. It may improve detection of known phishes, but its coverage depends on feed freshness. Record feed retrieval time and count. An unlisted link must remain unverified.

## Safety and usability checks

Create test cases for a harmless link, a new but legitimate account, a quoted insult, a direct threat, missing profile activity, malformed URLs, an unavailable feed, and a phishing URL in a downloaded feed. Check whether the output identifies real observations and states its limits. Measure end-to-end API response time separately from model prediction time.

For a voluntary pilot, recruit approximately 15–20 participants, use consented or synthetic examples, and avoid collecting passwords or private account histories. Ask participants to check the same cases with and without explanations in a balanced order. Measure task completion, interpretation accuracy, and whether they know what to verify next. Report descriptive findings as a small usability pilot, not a population-level effectiveness study.

## Reporting rule

Keep demo fixtures separate from evaluation data. Publish metrics only after running the code on documented, permissioned data. Include dataset size, source, split method, class balance, limitations, and representative false positives and false negatives.
