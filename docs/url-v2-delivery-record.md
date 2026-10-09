# Sentinel URL v2 delivery record

Recorded on 2026-10-09. The approved inline implementation adds pinned bounded metadata
acquisition, an original-observation audit, whole-component isolation, reusable CPU
training/calibration, format controls, immutable artifacts and frozen robustness evaluation.
The actual data run **stopped before fitting**: only six benign query-bearing URLs remain
in development, below the predeclared minimum of 30. There is no v2 model artifact or
accuracy result. This completes the data run with a reproducible incomplete outcome;
the independent review and integration are still being finalized.

## Measured research outcome

- All 77 pinned PhreshPhish shards: 666,315 observations; 45,871,391 received payload bytes,
  including metadata/retries; HTML excluded. Full source checksums were not computed.
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
the canonical-reader correction passed 125 Python checks with zero skips; 12 web-client
checks also passed. A separate `-S` compatibility check passed the default stdlib-only API.
All 32 snapshotted v1/case/intake files remain byte-identical after acquisition.

The actual audit exposed a scalability defect: 20,001 SQL SELECTs for a synthetic
10,000-row reader profile. A regression failed at 121 SELECTs for 60 canonical rows; one
ordered scan made it pass and reduced the original synthetic profile to one SELECT.
Synthetic elapsed time fell from 1.898 to 1.259 seconds. These are software measurements,
not detection accuracy. The real CLI guard verifies that all original audit/protocol
sidecar hashes still match; its receipt is recorded in the aggregate status.

## Independent final review

Pending. One fresh reviewer will review the whole branch, approved plan/spec, source audit,
tests, privacy/provenance boundaries and measured incomplete outcome. Findings will be
regraded by user effect; important/critical findings receive one regression-first fix pass,
and every disposition is recorded here and in the preserved private ledger. No trained
model or evaluation is required to bypass a failed data gate.

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
   need those handles; the public interface and portable provenance stay unchanged.
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
