# Collect and review Sentinel message–link cases

The [intake file](../data/curation/intake.csv) starts empty on this computer. In a fresh copy of the project, create it with `.\curate-sentinel.cmd init data\curation`. It is a local research worksheet, not an app case-history export. Do not put demonstration `.example` cases, passwords, private account histories, or unredacted personal identifiers in it. The `data/curation/` directory is excluded from version control because it may contain real messages.

## 1. Collect cases

Edit `data/curation/intake.csv` as UTF-8 text (for example, in VS Code), or import it into a spreadsheet with **every column explicitly set to Text**. Do not double-click untrusted CSV files to open them in spreadsheet software: message text beginning with `=`, `+`, `-`, or `@` may be interpreted as a formula. Use the same text-only import for reviewer and adjudication sheets, and export them as UTF-8 CSV. Enter one message–link pair per row. Both likely phishing attempts **and** legitimate messages with links are needed. Do not attach a URL from a different message. Use the original linked destination without visiting it on the Sentinel server. If its query string contains a personal token, redact it carefully or exclude that case; record the decision in your private collection notes. Record the date your team collected the case, not an inferred message-sending date.

| Column | Enter |
| --- | --- |
| `case_id` | An opaque unique ID such as `case-001`; no names or phone numbers. |
| `message` | The original message text after removing personal details. |
| `url` | The HTTP(S) link from that message or linked post. |
| `source_name` / `source_ref` | Dataset or consent record and a stable row/reference ID. |
| `campaign_group` | Optional opaque ID shared by cases your team has evidence belong to one campaign, even across different domains. Leave blank when unknown. |
| `channel` | `social_post`, `social_dm`, `sms`, or `email`; this keeps platform transfer visible. |
| `collected_on` | Collection date in `YYYY-MM-DD` format. |
| `collection_basis` | `licensed_public` or `consented`. Check the actual source terms or consent before use. |
| `pair_evidence` | `in_message` if the same URL, including scheme, port, path and query, appears in the text; `same_post` for an attached hyperlink. |
| `pair_note` | For `same_post`, explain how the link and text were observed together in one post. |
| `redaction_reviewed` | `yes` after someone checks for personal details and secrets. |

Keep any consent records or screenshots separately under team control. `source_ref` can be an opaque pointer to that record. The workflow verifies obvious input mistakes; it cannot prove a source's licence, consent, human redaction, or a `same_post` attachment. A nonempty `pair_note` is only a human attestation; retain evidence separately and check it during review. For a bare `www.` link, record its normalized `http://` form unless the source independently establishes an HTTPS destination.

Aim for both classes within each channel and source where possible. If all suspicious cases come from one dataset and all legitimate cases from another, a model may learn the source's writing style instead of deception. Report results by channel when sample sizes permit; an email-only result is not social-media performance. Assign the same `campaign_group` only when you have evidence cases are related; the split keeps that group on one side. Unknown or paraphrased campaigns can still leak, so review these manually before freezing.

## 2. Review independently

After the intake is ready, run this from the project folder:

```powershell
.\curate-sentinel.cmd prepare data\curation
```

This freezes the intake file by hash and creates `reviewer_a.csv`, `reviewer_b.csv`, and `adjudication.csv` in `data/curation/`. Give each reviewer only their own sheet. The sheets omit the source name and any source label, so reviewers judge the message and link independently. Each reviewer fills every row with their own `reviewer_id`, `review_label`, and a brief `review_reason` based on observed evidence:

- `1` — a confirmed or well-supported deceptive attempt to obtain credentials, money, or another sensitive action; record the specific evidence.
- `0` — a message and link independently verified as legitimate through their source, not just one with no obvious warning signs.
- `?` — unclear, ordinary spam, or insufficient evidence. Do not force a binary label.

The two reviewer IDs must be different. Do not edit the message, URL, or intake file after sheets are prepared. If more cases are collected later, start a new collection directory instead of silently changing this batch.

## 3. Resolve disagreements and finalize

For any disagreement or `?`, discuss the case and add its `case_id`, `final_label`, and reason to `adjudication.csv`. The final label must be `0`, `1`, or `exclude`. Unresolved cases stop finalization; they are not silently assigned a label.

```powershell
.\curate-sentinel.cmd finalize data\curation
```

This creates `final_pairs.csv` for the research model and a counts-and-hashes `final_audit.json`. The audit hashes the intake, both reviewer sheets, adjudication, and final pairs so later changes are detected. The paired file remains local and ignored by version control. At this point, inspect duplicate campaigns and ambiguous cases manually. Source labels, if any, are provenance only; two reviewers still determine Sentinel's research label.

## 4. Lock a test set once

After there are enough independent destination groups and both labels, run:

```powershell
.\curate-sentinel.cmd freeze data\curation
.\curate-sentinel.cmd evaluate data\curation
```

`freeze` writes `locked/train.csv`, `locked/test.csv`, and hashes in `locked/manifest.json`; it refuses to overwrite an existing lock. `evaluate` checks the hashes and compares message-only, URL-only, and combined models on that same test set. Save the manifest hash in a dated research log or with your supervisor; a purely local hash file can be rewritten along with the data. Do not select features or tune the model after reading the locked test results. If you need to iterate, split off a validation set from the training file and reserve the locked test set for the final report.

The current intake is empty, so no phishing evaluation or pilot outcome is claimed. The earlier [spam/ham benchmark](first-research-benchmark.md) remains an engineering baseline with different labels.
