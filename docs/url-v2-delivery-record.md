# Sentinel URL v2 delivery record

Recorded on 2026-10-09. The approved inline implementation adds pinned bounded metadata
acquisition, an original-observation audit, whole-component isolation, reusable CPU
training/calibration, format controls, immutable artifacts and frozen robustness evaluation.
The actual data run **stopped before fitting**: only six benign query-bearing URLs remain
in development, below the predeclared minimum of 30. There is no v2 model artifact or
accuracy result. This completes the data run with a reproducible incomplete outcome;
software verification and the independent review are complete, and the changes were
fast-forwarded into `codex/sentinel` under the existing repository authorization.

## Measured research outcome

- All 77 pinned PhreshPhish shards: 666,315 observations; 45,871,391 received payload bytes,
  including counted metadata/range retries; dataset HTML excluded. Historical intermediate
  redirect bodies were unmetered, so total transfer is unknown. Full source checksums
  were not computed.
- Audit: 660,130 canonical URLs, 660,164 included observations, 6,151 exclusions and 34
  non-conflicting duplicate observations. No contradictory labels occurred in this release.
- Development: 200,000 whole-component rows; train/validation/calibration 160,000/20,000/20,000.
  Benign paths 63,850 and non-www hosts 34,320 pass; benign queries 6 fail the minimum 30.
- Primary holdout: 166,369 rows with sufficient class/domain support, but no model metrics.
  External and chronological validation are unavailable; official ISCX was not acquired and
  the supplied date fields have unauthenticated collection semantics.
- No thresholds, seed, cap, ownership or support minima were changed after freezing. No
  final row was moved into development. No model fit, calibration, export or final scoring
  ran; v1-v2 improvement cannot be estimated.

The [aggregate status](../output/research/url-ml-v2/research-status.json) contains exact
manifest/config/parser hashes, class/component/format counts, null metrics and resources.
The [research card](../output/research/url-ml-v2/model-card.md) explains their limits.
The original application, paired-message intake, case history and v1 artifact remain separate.

## Verification evidence

The fresh CPython 3.11 union environment has 17 exact pins, nine identical shared pins and
no conflicts. The original 16-pin ML lock remains unchanged. The latest whole suite after
the canonical-reader correction and four review corrections passed 130 Python checks with zero skips; 12 web-client
checks also passed. A separate `-S` compatibility check passed the default stdlib-only API.
All 32 snapshotted v1/case/intake files remain byte-identical after acquisition.

The actual audit exposed a scalability defect: 20,001 SQL SELECTs for a synthetic
10,000-row reader profile. A regression failed at 121 SELECTs for 60 canonical rows; one
ordered scan made it pass and reduced the original synthetic profile to one SELECT.
Synthetic elapsed time fell from 1.898 to 1.259 seconds. These are software measurements,
not detection accuracy. The real CLI guard verifies that all original audit/protocol
sidecar hashes still match; its receipt is recorded in the aggregate status.

## Independent final review

One fresh independent reviewer inspected the complete branch through `79dabf0`, plan/spec,
source audit, tests and measured incomplete outcome. They independently passed 24 targeted
acquisition/audit/protocol checks and reproduced four important gaps with temporary fixtures,
no acquisition and no fitting. There were no critical or minor findings. All four important
grades stand by user effect; the single regression-first fix pass is complete. No re-review was dispatched.

| Finding | Cause and correction | Verification |
| --- | --- | --- |
| Unmetered redirect bodies | urllib inherited an unbounded body drain; close intermediates, retain redirect validation/loop checks, qualify old byte receipts | RED: 10,000 uncounted bytes under eight-byte budget; GREEN for all five redirect codes, oversized/interrupted bodies; whole suite 126/126 |
| Ancillary failure hid label conflicts | Retain recognized canonical URL/label before ancillary exclusion; exclude all contradictions and preserve original failure | RED for malformed dates/opaque IDs; GREEN; whole suite 127/127; real-audit semantic hashes unchanged |
| Interrupted cache broke resume | Replace unjournaled partial files using complete unique temporary payloads and atomic promotion; retain received-byte ledger | RED for partial/complete orphan files; GREEN with exact spent bytes; whole suite 128/128 |
| Mutable splits bypassed frozen fitting | Share frozen file/assignment/content checks with training and pilot boundaries | RED for labels/URLs/whole-component swaps/frozen files/shadow keys; GREEN in training and pilot; final whole suite 130/130 |

The reviewer declined to judge live v2 accuracy, deployment suitability and activation:
there is no model and the failed gate prevents fitting. The executor's ruling keeps metrics
unavailable and warnings disabled. Cost if wrong: software checks might be mistaken for live
validation; deployment still needs a separately measured release decision. Deferred minors:
none. No repeated review or untrained accuracy requirement was introduced.

## Decisions and costs

1. Use a manual worktree in the actual repository because the chat's stale project entry
   resolves outside Sentinel and app worktree tools have no repository override. Cost:
   manual registration and cleanup instead of the app's managed lifecycle.
2. Allow null original URL/label values in observations so audit can preserve distinct
   missing-value exclusions. Cost: adapters must enforce non-null values after validation.
3. Store `pyarrow==25.0.1` in the lock instead of a checkout-specific wheel URL. Cost:
   version pins need the separate verified official wheel hash for binary identity.
4. Use the specification's per-class domain-group minima and separately report connected
   component counts. Cost: fewer independent components can weaken intervals; their
   support and uncertainty must remain visible.
5. Add private root/audit handles to split bundles for changed-file checks and v1 pruning,
   excluding paths from hashed/public manifests. Cost: manually built evaluation bundles
   need those handles for evaluation and pre-fit checks; the public interface and portable
   provenance stay unchanged.
6. Bundle the unmodified frozen MPL-2.0 suffix list for offline reproducibility. Cost:
   334,734 repository bytes and retained license attribution; no labelled dataset is bundled.
7. Replace per-URL audit SELECTs with one ordered canonical scan after the measured
   scalability failure. Cost: sorting uses temporary disk and could change ordering or
   representatives; the regression and original real sidecar hashes must still match.

## Remaining milestone

Acquire task-aligned annotated legitimate URLs with diverse query/path/host formats and
source/channel/date evidence. Amend as a new version with independent final data before
fitting. Keep the v2 source/audit/protocol immutable and learned application warnings
disabled. The year-long paired message/link experiment, contextual harm/profile ML,
team investigation workflows and usability pilot remain future milestones.

## Integration and preservation

On 2026-10-09 the primary `codex/sentinel` checkout fast-forwarded from `2969dff` to the
reviewed implementation. The main-folder union environment independently passed all
130 Python checks with zero skips, and the web client passed 12/12 with zero skips.
The default stdlib-only API is included in that full suite. The final repository push
uses the existing private remote; no force push, new public dataset or ML activation
is part of this milestone. Remote HEAD/clean-check receipts are retained privately.

The source/cache/audit/protocol copy contains 575 files with equal SHA-256 hashes; the
failed-gate diagnostic is preserved too. Data and verification environments were recreated
at the main folder from exact saved wheels, with 10/17 pins and successful `pip check`.
The original ML environment/lock and all 32 snapshotted original files stayed unchanged.
The implementation ledger, reviewer report, regression logs, package wheels and run
receipts are archived under ignored `data/url-ml-v2/runs/implementation-proof/` before
manual worktree cleanup. Research JSON/cards contain aggregates only; no raw URLs,
source archives, cases, caches or model binaries are committed.

Task-completion order followed the approved Task11 brief: final review and integration
precede its completion ledger, with cleanup after proof preservation. Cost: delayed
cleanup and a fresh full suite on the merged primary tree. This resolves the generic
inline skill's task-before-finishing sequence without claiming delivery prematurely.
