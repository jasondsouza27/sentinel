# Sentinel: current state and next steps

Updated on 2026-10-13. The active project folder on this computer is `C:\Users\Jason Dsouza\Desktop\major project`. Open this folder in Codex or your editor; the previous OneDrive project entry points to an empty folder. Run launchers from this new folder.

The [paired-study software workflow](paired-study-workflow.md) is implemented. It covers evidence-ledger binding, blinded two-reviewer packets, a counts-only `audit`, group-isolated four-way lock, CPU branch/fusion models, a single-use final evaluation receipt and a research-only optional API card. The synthetic integration test verifies software behavior only. The real `data/curation/intake.csv` remains empty, so the current paired-study result is **unavailable**; no phishing-fusion performance or live learned warning is claimed.

## Current priority: English conversation/harm module

The user selected the English conversation/harm module as the next engineering milestone and approved its [focused specification](superpowers/specs/2026-10-13-sentinel-context-harm-design.md). The [source feasibility investigation](context-harm-source-audit-2026-10-12.md) verifies CAD v1.1 and CCC source structure, labels and grouping limits. The [12-task implementation plan](superpowers/plans/2026-10-13-sentinel-context-harm.md) is prepared and awaiting review. It covers protected cohorts, CPU and conditional compact-encoder comparisons, ordered app turns, exact reviewed-result saving and an empty challenge workflow. Official package metadata and Windows wheel hashes are pinned in the [planning catalog](../output/research/context-harm-neural-package-catalog.json); no package/model bodies were acquired or installed, and no training occurred. The harm module currently remains rule-based. Real paired-message collection can proceed alongside this work.

## Completed URL benchmark and paired-message data work

The approved [URL-v3 specification](superpowers/specs/2026-10-09-sentinel-url-v3-design.md)
and [implementation plan](superpowers/plans/2026-10-09-sentinel-url-v3.md) have produced
a frozen, measured URL-only study. A checksum-pinned Mendeley source contributed 11,430
observations; the joint audit retained 671,521 canonical URLs. All coverage gates passed,
so a 200,000-row development set was used for ten CPU configurations. The selected
candidate scored 0.927 F1/5.76% FPR on 166,369 primary URLs and 0.839 F1/22.39% FPR
on 4,348 supplemental URLs. Legitimate query URLs were falsely flagged 13/52 and 27/44.
A synthetic `example.com` inference was also falsely flagged. These results block
live learned warnings. Read the [public model card](../output/research/url-ml-v3/model-card.md),
[aggregate evaluation](../output/research/url-ml-v3/evaluation.json),
[delivery record](url-v3-delivery-record.md) and [workflow](url-v3-workflow.md).
The original 27 protected files, 17 exact dependency pins and empty paired-message intake
stayed unchanged.

The supplemental set is group-held-out from a source that also appears in development;
neither it nor the primary historical set supplies independent contemporary or authenticated
temporal validation. Keep both final sets sealed. Any error analysis that changes features,
thresholds, sources or cohort assignments requires a new version and a newly reserved final
set. URL-v2 remains an honest unavailable outcome because only six legitimate query URLs
passed its development gate; its [record](url-v2-delivery-record.md) is preserved.

The central year-long question is whether genuinely paired message and URL evidence
improves suspicious-message detection. The existing 100 phishing and 18 possible legitimate
SMS candidates are unreviewed, and the intake is empty. The next data milestone is to
collect independently verified legitimate pairs from comparable channels, complete the
two-reviewer admission workflow and freeze a group-isolated paired test set. The extension
and browser checks below can continue independently. No URL-v3 result proves message–link
fusion, account authenticity, harassment patterns or live-site safety.

The first ML milestone is integrated and pushed to the private GitHub repository. The independent review findings were reproduced and fixed; the [delivery record](url-ml-delivery-record.md) documents all decisions and correction audits.

The first approved [ML foundation plan](superpowers/plans/2026-10-05-sentinel-ml-foundation.md) has produced an audited 235,343-URL dataset, domain-isolated frozen splits, two trained CPU branches, separate calibration, immutable artifacts, inference CLI and optional API. See the [reproduction workflow](url-ml-workflow.md) and [final model card](../output/research/url-ml-v1/model-card.md).

The benchmark achieved 97.07% positive F1, but **url-v1 is research-only**. All legitimate source rows are HTTPS www homepages with empty paths and queries; ordinary benign documentation URLs are falsely flagged. This measured source-format confounding persists despite domain isolation. The URL-v3 study above tests broader formats, but its supplemental false-positive rate and missing independent/temporal validation still prevent activation. Do not tune or whitelist against the staged smoke cases or the final test.

The [approved year-long design](superpowers/specs/2026-10-05-sentinel-year-long-design.md) still defines the balanced research/application scope. The software for the main paired-message question is ready; its **real-data answer** remains a future milestone. Contextual harm/profile ML, team investigation workflows, dashboard redesign and the user pilot also remain. Human collection and browser work below can continue independently.

## Ready now

- The local app, shared API, Chrome extension, research baselines and collection workflow are implemented.
- The locked CPython 3.11 suite passed **236 Python checks with zero skips** in 481.235 seconds after paired-study review fixes; the Node web/extension suites passed **14/14 with zero skips**. The synthetic paired model worker smoke recorded a 144,351,232-byte peak and 58.268-second fit for 12 invented pairs and seven candidates; these are engineering measurements, not a phishing result. The [web-app browser test record](web-app-smoke-test-2026-10-05.md) covers analysis, recovery, saving, reopening, feedback and layout. Chrome toolbar/context-menu checks, a confirmed report download and UI deletion remain pending.
- `data/curation/ncsu_candidates.csv` contains 100 unreviewed phishing candidates.
- `data/curation/legitimate_sms_candidates.csv` contains 18 unreviewed potential legitimate SMS candidates from UCI and NUS.
- Source and candidate hashes are recorded in the local audit files. Raw sources and candidate sheets stay local and ignored by Git.
- `data/curation/intake.csv` remains empty. No final paired-message phishing evaluation or user pilot has been run. The separate URL-string benchmark above is complete.

## Parallel data task: admit a verified batch for review

1. Open each candidate sheet as UTF-8 text, or import every spreadsheet column as Text. Follow the [source audit](real-dataset-source-audit.md) to locate its original record. Check the pairing, remove personal details or secrets, and confirm the source's reuse terms. Do not visit submitted destinations from the Sentinel server.
2. Gather independent evidence for legitimate requests. A UCI ham label, a NUS contribution or a familiar domain alone is insufficient. The two sources supplied only 18 diverse candidates, so collect more verified pairs from a comparable channel and period. Record evidence privately under the team's control. Do not force uncertain cases into the legitimate class.
3. Copy only admitted cases into the intake and fill `collected_on`, `collection_basis` and `redaction_reviewed`. Keep the candidate sheets and source files unchanged. Do not invent sending dates or campaign IDs. Collection admission does not assign the final research label.
4. When the batch is ready, follow the [two-reviewer workflow](collection-workflow.md). Prepare independent sheets, adjudicate disagreements and exclude unresolved cases. The workflow requires human decisions; the application will not silently label these candidates.
5. Inspect source, channel, date, domain and campaign imbalance before freezing a test set. Both labels are required in the final held-out set. A comparison between NC State phishing and old UCI/NUS messages could reflect source differences, so describe that limit and expand the collection before claiming general performance.

## Browser validation can proceed alongside collection

Start `start-sentinel.cmd` from the active project folder and load its `extension` directory unpacked in Chrome. Complete and record the [extension smoke test](extension-smoke-test.md), including selected text, link checking, case deletion and an unavailable server. Use the synthetic examples in that checklist.

The user chose to continue web-app checks before loading the extension. Those checks found and fixed stale results after a failed request, late replies overriding a cleared/opened assessment, saving races and narrow-panel history overflow. See the browser record for the precise coverage; do not record the deferred Chrome or download checks as passed.
