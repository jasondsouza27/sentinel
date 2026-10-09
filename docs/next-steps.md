# Sentinel: current state and next steps

Updated on 2026-10-09. The active project folder on this computer is `C:\Users\Jason Dsouza\Desktop\major project`. Open this folder in Codex or your editor; the previous OneDrive project entry points to an empty folder. Run launchers from this new folder.

## Current priority: broaden URL data before deployment

On 2026-10-09 the [source investigation](url-data-expansion-feasibility-2026-10-09.md)
verified the official Mendeley URL-label CSV and measured 92 legitimate query URLs across
87 domain groups outside the existing protected primary domains. This is preliminary
coverage, before joint conflicts and new reservations. The user approved that direction;
the [written URL-v3 specification](superpowers/specs/2026-10-09-sentinel-url-v3-design.md)
was approved on 2026-10-09. Its [eleven-task implementation plan](superpowers/plans/2026-10-09-sentinel-url-v3.md) was approved for inline implementation with one independent final review; implementation has started in an isolated worktree. No new rows are admitted or model fitted.

A focused [URL-v2 data/robustness specification](superpowers/specs/2026-10-07-sentinel-url-v2-data-design.md)
was approved on 2026-10-07. Its [implementation plan](superpowers/plans/2026-10-07-sentinel-url-v2-data.md)
was approved for inline implementation with one independent final review.
The [v2 reproduction guide](url-v2-workflow.md) documents implemented acquisition,
provenance, isolation, bounded model/control fits and frozen evaluation commands.
Real acquisition is complete: 666,315 observations across 77 shards, 660,130 canonical
URLs after audit and a 200,000-row frozen development set. Paths/non-www coverage passes,
but only **6 benign query-bearing development URLs** remain against a minimum of 30.
Training is blocked; no v2 fit, calibration, artifact, accuracy or comparison was produced.
The [research card](../output/research/url-ml-v2/model-card.md), [aggregate status](../output/research/url-ml-v2/research-status.json)
and [delivery record](url-v2-delivery-record.md) record measured counts, hashes, resources
and review dispositions. The [source audit](url-v2-source-audit.md) retains both initial
feasibility evidence and complete acquisition receipts. Official ISCX access and authenticated
chronological validation remain unavailable.

The next URL research step is a documented source of diverse, annotated legitimate URLs,
including queries, followed by a **new** protocol/version and independent final set. Keep
these assignments frozen: do not change seed/cap/minima, invent rows or reuse final rows
to rescue coverage. This is a data-quality result, not a reason to deploy the v1 model.

The first ML milestone is integrated and pushed to the private GitHub repository. The independent review findings were reproduced and fixed; the [delivery record](url-ml-delivery-record.md) documents all decisions and correction audits.

The first approved [ML foundation plan](superpowers/plans/2026-10-05-sentinel-ml-foundation.md) has produced an audited 235,343-URL dataset, domain-isolated frozen splits, two trained CPU branches, separate calibration, immutable artifacts, inference CLI and optional API. See the [reproduction workflow](url-ml-workflow.md) and [final model card](../output/research/url-ml-v1/model-card.md).

The benchmark achieved 97.07% positive F1, but **url-v1 is research-only**. All legitimate source rows are HTTPS www homepages with empty paths and queries; ordinary benign documentation URLs are falsely flagged. This measured source-format confounding persists despite domain isolation. Next, acquire diverse legitimate paths/queries and non-www hosts alongside phishing examples, define a new frozen version and independent source/temporal holdout, and evaluate again before enabling learned live warnings. Do not tune or whitelist against the staged smoke cases or the final test.

The [approved year-long design](superpowers/specs/2026-10-05-sentinel-year-long-design.md) still defines the balanced research/application scope. The main paired-message question, contextual harm/profile ML, team investigation workflows, dashboard redesign and user pilot remain future milestones. The human collection and browser work below can continue independently.

## Ready now

- The local app, shared API, Chrome extension, research baselines and collection workflow are implemented.
- All 78 Python tests without ML dependency skips and 12 web-client checks passed in a fresh locked Python 3.11 environment on 2026-10-06. The original dependency-free server entry point also passed separately. The [web-app browser test record](web-app-smoke-test-2026-10-05.md) covers analysis, recovery, saving, reopening, feedback and layout. Chrome toolbar/context-menu checks, a confirmed report download and UI deletion remain pending.
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
