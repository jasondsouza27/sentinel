# Sentinel: current state and next steps

Updated on 2026-10-05. The active project folder on this computer is `C:\Users\Jason Dsouza\Desktop\major project`. Open this folder in Codex or your editor; the previous OneDrive project entry points to an empty folder. Run launchers from this new folder.

## Ready now

- The local app, shared API, Chrome extension, research baselines and collection workflow are implemented.
- All 31 Python tests and 12 web-client regression tests passed on 2026-10-05. The [web-app browser test record](web-app-smoke-test-2026-10-05.md) covers analysis, recovery, saving, reopening, feedback and layout. Chrome toolbar/context-menu checks, a confirmed report download and UI deletion remain pending.
- `data/curation/ncsu_candidates.csv` contains 100 unreviewed phishing candidates.
- `data/curation/legitimate_sms_candidates.csv` contains 18 unreviewed potential legitimate SMS candidates from UCI and NUS.
- Source and candidate hashes are recorded in the local audit files. Raw sources and candidate sheets stay local and ignored by Git.
- `data/curation/intake.csv` remains empty. No final phishing evaluation or user pilot has been run.

## Next research task: admit a verified batch for review

1. Open each candidate sheet as UTF-8 text, or import every spreadsheet column as Text. Follow the [source audit](real-dataset-source-audit.md) to locate its original record. Check the pairing, remove personal details or secrets, and confirm the source's reuse terms. Do not visit submitted destinations from the Sentinel server.
2. Gather independent evidence for legitimate requests. A UCI ham label, a NUS contribution or a familiar domain alone is insufficient. The two sources supplied only 18 diverse candidates, so collect more verified pairs from a comparable channel and period. Record evidence privately under the team's control. Do not force uncertain cases into the legitimate class.
3. Copy only admitted cases into the intake and fill `collected_on`, `collection_basis` and `redaction_reviewed`. Keep the candidate sheets and source files unchanged. Do not invent sending dates or campaign IDs. Collection admission does not assign the final research label.
4. When the batch is ready, follow the [two-reviewer workflow](collection-workflow.md). Prepare independent sheets, adjudicate disagreements and exclude unresolved cases. The workflow requires human decisions; the application will not silently label these candidates.
5. Inspect source, channel, date, domain and campaign imbalance before freezing a test set. Both labels are required in the final held-out set. A comparison between NC State phishing and old UCI/NUS messages could reflect source differences, so describe that limit and expand the collection before claiming general performance.

## Browser validation can proceed alongside collection

Start `start-sentinel.cmd` from the active project folder and load its `extension` directory unpacked in Chrome. Complete and record the [extension smoke test](extension-smoke-test.md), including selected text, link checking, case deletion and an unavailable server. Use the synthetic examples in that checklist.

The user chose to continue web-app checks before loading the extension. Those checks found and fixed stale results after a failed request, late replies overriding a cleared/opened assessment, saving races and narrow-panel history overflow. See the browser record for the precise coverage; do not record the deferred Chrome or download checks as passed.
