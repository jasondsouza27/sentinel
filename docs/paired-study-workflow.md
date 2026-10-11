# Paired message–link study: private collection and offline reproduction

Sentinel's paired research question is whether the **original message and the URL linked by that message** improve phishing-request detection over either input alone. This software path is implemented, but a scientific result is **unavailable** until real cases pass the human-data gates. The synthetic test fixture checks code only. It is not a dataset, a phishing score, or evidence for a live warning.

## Local environment and storage

From a clean clone on Windows with CPython 3.11, create a private environment and install the pinned 17-package lock:

```powershell
py -3.11 -m venv .venv-url-v2-check
& .\.venv-url-v2-check\Scripts\python.exe -m pip install -r requirements-ml-win-py311.lock.txt
& .\.venv-url-v2-check\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/web_client.test.mjs tests/extension_popup.test.mjs
```

Keep raw messages, URLs, source material, verification records, review sheets, split CSVs, `final_access.json`, model artifacts and private error-case IDs in an approved **local, access-controlled, nonsynced** workspace. `data/curation/` and `models/paired/` are Git-ignored, but Git ignore is not encryption or access control. Do not place private originals in a synced OneDrive folder without team approval. Do not commit them or upload them to the GitHub repository. The source screenshots/consent records belong in a separate team-controlled evidence vault; only opaque pointers belong in the ledger. Sentinel never visits submitted URLs during this workflow.

The team's four roles are: (1) collector/admission steward, who checks original pairing, permission and redaction; (2) independent reviewer A; (3) independent reviewer B; and (4) adjudicator/data steward, who resolves disagreement and audits split integrity. Reviewers decide labels from class-neutral evidence, not source-provided labels. Uncertain or ordinary-spam cases remain `?` or excluded; feedback from the app is never admitted automatically.

## Intake and evidence ledger

Use `python -m sentinel.curation init data/curation` once to create `intake.csv`, then admit only permissioned, redaction-reviewed cases whose original message and exact linked destination were observed together. The 100 NC State candidates and 18 potential legitimate SMS candidates are **unreviewed** and are not study rows. A legitimate message needs independent confirmation of the actual claimed sender or purpose. A familiar domain, `ham` label, successful page load or lack of a reputation-feed hit is not confirmation. Record `collected_on` as acquisition date; do not invent an original observation date.

Create `evidence_ledger.csv` beside the intake with exactly one row per `case_id` and these columns:

| Column | Meaning |
| --- | --- |
| `case_id` | Opaque key matching intake one-to-one |
| `evidence_id` | Unique opaque evidence-vault pointer |
| `evidence_type` | `official_confirmation`, `independent_threat_report`, `source_record`, or `consent_record` |
| `verification_ref` | Opaque pointer to private verification material, never its text or public URL |
| `observed_on` | Original observation date `YYYY-MM-DD` if known; blank otherwise |
| `source_sha256` | Source-file digest; required for `licensed_public` cases |
| `source_version` | Source release/version; required for `licensed_public` cases |
| `permission_basis` | `licensed_public` or `consented`, matching intake |
| `redaction_decision` | `redacted` or `none_needed` |

The binary study labels are `1 = phishing_request` and `0 = verified_legitimate_request`. Two reviewers and adjudication establish the label. A `source_record` or `consent_record` alone never satisfies the independently verified legitimate gate.

## Seven offline stages

Run these in order from the repository root; use the pinned environment's Python in place of `python` if needed. Every stage rejects replacement of an existing output. The CLI accepts no reduced production gates.

```powershell
python -m sentinel.paired.cli prepare --root data/curation
python -m sentinel.paired.cli finalize --root data/curation
python -m sentinel.paired.cli audit --root data/curation
python -m sentinel.paired.cli freeze --root data/curation
python -m sentinel.paired.cli train --root data/curation
python -m sentinel.paired.cli evaluate --root data/curation
python -m sentinel.paired.cli predict --root data/curation --message 'Example only' --url 'https://example.com/'
```

`prepare` validates intake and ledger, creates a blinded `case_packet.csv` with opaque evidence pointers, two reviewer sheets and preparation hashes. Each reviewer fills their own ID, `0`/`1`/`?` label and reason. The adjudicator fills `adjudication.csv` for disagreement or uncertainty. `finalize` refuses changed intake, ledger or packet and creates hash-bound final rows only after both independent reviews resolve. It never auto-labels a candidate.

`audit` reports counts and cross-tabs only: class, opaque source, channel, known observation month, unknown dates, domains and connected groups. It returns `status: unavailable` when the intake is empty (`reasons: ["empty_intake"]`), when there are too few reviewed cases, when legitimate verification is missing, or when `source_label_confounded` or known-period confounding blocks a primary claim. A nonempty unfinished batch returns `pending_review`. A passing report is only `eligible_for_freeze`, not evidence of representativeness.

`freeze` requires at least **2,000** reviewed pairs and **1,000 per class**. The sealed test must support **100 per class** and **30 distinct destination groups**. The fixed seed is 42; train/validation/calibration/test target 70/10/10/10, with connected domains from every message URL, documented campaigns and URL-stripped repeated wording kept together. A giant component or infeasible split fails; it is not divided to fill a quota. The pinned private-inclusive suffix snapshot hash is checked. The old two-way `locked/` research baseline is untouched; the new four-way lock lives in `study-v1/`.

`train` reads only hash-verified train, validation and calibration partitions. It fits two message, two URL, two early-fusion candidates and late fusion only when five group-disjoint out-of-fold partitions support it. Validation selects a threshold within the 5% false-positive-rate budget; calibration uses only the calibration partition. CPU work is sequential, uses at most four native threads and a monitored 8 GiB worker cap. The artifact contains hashes, environment versions, thresholds and a model card and is always `release_status: research_only`.

`evaluate` writes `study-v1/final_access.json` **before** opening the sealed test. It permits a retry only for the same interrupted protocol/artifact/output identity; a completed `final-evaluation/` is single use. The aggregate report compares combined against both individual branches with 1,000 connected-group paired bootstrap replicates, while private case IDs stay in `private_error_cases.json`. Never tune the cohort, features, thresholds or source mix after viewing this test; a new version requires a newly reserved final set.

`predict` reports unavailable for this milestone's research-only artifact. The optional web/extension `paired_assessment` is disabled by default; passing `--paired-model` or `SENTINEL_PAIRED_MODEL_PATH` only exposes an **unavailable** card for a schema-1 research artifact. A separately reviewed release format and error review are needed before learned warnings can be activated. Existing rule observations remain available.

## Current handoff

The real intake has no admitted rows, so the paired study remains **unavailable**. The next team task is collecting comparable, permissioned phishing and independently verified legitimate message–destination pairs, redacting them, completing two independent reviews, and inspecting `audit`. Do not graft unrelated URL labels onto messages or relax the production criteria to manufacture a result. If feasible data never arrives, report that limitation honestly while continuing the separate URL, harmful-content, profile and application work.

Verification on 2026-10-12: 234 Python tests passed with zero skips in 314.030 seconds; 14 Node web/extension tests passed with zero skips. A separate **synthetic 12-pair worker smoke** fitted seven candidates in 58.268 seconds and recorded a 144,351,232-byte peak worker/process-tree measurement, below the configured 8 GiB cap. The real intake's counts-only audit returned `status: unavailable`, `reasons: ["empty_intake"]`, and zero admitted cases. These measurements verify software operation on this laptop; they do not measure phishing detection accuracy.
