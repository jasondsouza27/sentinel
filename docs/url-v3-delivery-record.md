# Sentinel URL-v3 delivery record

Recorded on 2026-10-11. This milestone implements a reproducible URL-only research workflow inside the year-long Sentinel project. It preserves the earlier v1/v2 artifacts and frozen v2 final owners, acquires one checksum-pinned additional source, audits the joint corpus, and reserves a separate supplemental final track. The ordinary web app still uses its existing rules; learned URL warnings remain disabled. URL-only research cannot establish the proposed message–link fusion result.

## Measured source and frozen cohort

All commands ran under Windows x64 CPython 3.11.17 with the exact 17 installed pins from the unchanged shared dependency locks. The old v2 study was read-only input. The v3 study, model candidate and command receipts are ignored private assets; the public research output contains aggregates only.

| Stage | Actual result | Elapsed |
| --- | --- | ---: |
| `bind-v2` | Verified the historical catalog, projection, audit, protocol and 166,369 original primary cases; extracted 78,202 protected domain groups, exactly matching the earlier source investigation. The historical v2 training gate was false and was not bypassed or rewritten. | 812.641 s |
| `acquire-mendeley` | Pinned `dataset_B_05_2020.csv`: 3,661,166 bytes, SHA-256 `21093e2902e5441c86a6daf95e86e7c332046e477fdf109a579d7bd81e586d6c`, 11,430 URL/status observations. HTTP body receipt: 3,784,900 measured bytes, including 123,734 metadata bytes; interrupted upper bound zero. | 20.453 s |
| `audit` | 677,745 observations from both sources; 671,584 admitted observations and 671,521 distinct canonical URLs (367,911 labelled legitimate, 303,610 phishing). Sixty-three non-conflicting duplicates. Exclusions: 5,741 scheme, 371 host, 18 length and 31 other parser reasons. No recognized-label conflict reported. | 2,398.859 s |
| `freeze` | Training-ready 200,000 development rows: 160,000 train, 20,000 validation and 20,000 calibration. Original primary: all 166,369 retained, zero removed. Supplemental: 4,348 separately reserved cases. The 78,202 protected domains stayed outside development. | 1,491.219 s |

The joint audit manifest is `d888c182a57c42164cef56cdb9d94e7a40f7dc9061f6fd8c8358f30dcaec7a79`; the frozen protocol manifest is `3d87c3dd6263837c32744717fd4957579fb1d5eb8c2341dc126acfca0de99e13`. The original v2 protocol digest is `3953a7fcb9785d3cee720c5a115e451716a2c81df1389ce439ab7b69a8fcaa96`. Exact source, group, class, ownership and format support are in the private protocol and aggregate freeze report. The production config, cap, seed, source revisions and minimum support were not changed after the source investigation.

The previously blocking legitimate-query gate now passes: 54 URLs in pooled development, 43 in training, 52 in primary and 44 in supplemental, against a predeclared minimum of 30 in each applicable set. Both source-development class/domain gates pass. The Mendeley source supplies 4,697 development rows before the remainder of the 200,000-row cap is filled. This establishes permission to run the prescribed resource pilot; it is not an accuracy result.

The Mendeley collection month is documentary and provides no authenticated row dates. The supplemental track is group-held-out from a source also represented in development, not an independent source or temporal validation. Historical labels do not certify current URL safety. No submitted URL destination was opened during acquisition or audit. The primary user-facing fraud study still needs genuine message–link pairs and independent held-out evaluation.

## Reproduction and boundary evidence

Use [the URL-v3 workflow](url-v3-workflow.md) for the exact ordered CLI and its no-retry rules. Private command receipts and sanitized logs live under ignored `data/url-ml-v3/runs/implementation-proof/`; raw URLs, source payloads, final scores, model binaries and local paths are absent from tracked research outputs. The pre-run snapshot covers 27 original v1/v2/case/intake files, their SQLite sidecars when present, and 17 installed packages. The case-intake CSV contained zero admitted rows. A post-run byte comparison is required before integration.

The full suite after the independent review fix passed 191 Python checks with zero skips in 241.954 seconds. All 12 web-client checks passed with zero skips. Earlier stage-specific suite receipts remain in the private implementation ledger. The default server remains stdlib-only; ML commands require the locked research environment. Synthetic fixtures verify contracts and failure boundaries and do not provide research performance claims.

## Decisions and their costs

1. Use a manual worktree in the actual Sentinel checkout because this chat's stale OneDrive project entry does not contain the repository. Cost: explicit private-data preservation and manual worktree cleanup after integration.
2. Allow the v3 historical verifier to stage read-only v2 audit validation under the new v3 study root through an optional scratch path. Cost if wrong: validation staging or cleanup could regress; the write-denying fixture checks the old input remains untouched.
3. Completed evaluation may replay only a sealed, identity-checked private report. A receipt interrupted after sealing can be finished without rescoring. Cost if wrong: corrupt or stale scores might be reused; tests cover mismatched artifact/settings, missing or tampered files, and one final-access receipt.
4. Prime the private verified-study snapshot only after one full semantic load and matching before/after physical digests. Every fitting entry still rehashes the physical sources, parser, config and protocol and compares frozen rows. Cost if wrong: stale rows could reach fitting; a watched mutation regression and one-load assertion cover the boundary.
5. Preserve the three sealed public URL-v3 files byte-for-byte in Git with narrow `-text !eol` attributes. The repository's global LF rule otherwise changed their CRLF bytes on staging, invalidating the recorded public evaluation SHA-256. Cost: these three generated aggregate files keep CRLF in Git instead of the repository's usual LF; a staged-byte regression check proves equality.
6. Charge a failed buffered HTTP read's full reserved size to the separate interrupted-body upper bound when the exception exposes no reliable partial bytes. Cost: an early timeout can exhaust the acquisition budget conservatively; releasing the reservation could exceed the declared cumulative limit. The successful verified acquisition and its sealed evaluation were not rerun or modified.


## Real resource pilot

The pilot completed successfully in 1,561.235 seconds, including full semantic re-verification of the historical source, joint audit and frozen protocol. It selected 2,000 rows across 1,461 whole connected components. The first character TF-IDF/logistic candidate fitted in 1.831 seconds inside its worker; its conservative process-tree peak was 171,794,432 bytes. The first lexical HGB candidate fitted in 1.414 seconds with a 148,045,824-byte conservative tree peak. Both workers used four native threads, reported one monitored process each, and stayed below the fixed 8,589,934,592-byte ceiling. These are fitting resource checks on the pilot subset, not detection scores or a guarantee for the full 160,000-row training set.


## Real training and candidate smoke check

All ten predeclared configurations completed successfully in 2,500.687 seconds, including the repeated full-study verification, six character TF-IDF/logistic fits, four lexical HGB fits, the format-only control and calibration/export. The greatest conservative process-tree fitting peak reported by the ten candidate workers was 1,276,379,136 bytes, below the fixed 8 GiB ceiling. The validation-selected candidate is character TF-IDF/logistic with `C=10`, balanced class weights and raw threshold `0.38372611874561074`. Its immutable artifact manifest is `1ccaa15e08e6baae002d6cbe9505e4161ef44f2539a590feed8a2e7e9d124896`. The candidate remains local, ignored by Git and disconnected from ordinary application warnings.

A post-export synthetic inference on `https://example.com/` returned a phishing flag. This is an obvious false positive for a reserved example domain and a useful deployment warning, not a held-out benchmark measurement. The model and threshold were not adjusted from that probe; the predeclared frozen evaluation proceeds with unchanged settings. This one case alone is enough to keep learned live warnings disabled, regardless of aggregate benchmark scores.


## One-time frozen evaluation

Evaluation exited successfully in 1,832.750 seconds. The final-access receipt was written before the first score and now records a complete sealed report tied to the unchanged protocol and artifact. The public [evaluation JSON](../output/research/url-ml-v3/evaluation.json), [status](../output/research/url-ml-v3/research-status.json) and [model card](../output/research/url-ml-v3/model-card.md) were published atomically. The public evaluation file SHA-256 is `a6308501297956298e78bb9f6ff05e155cd92a2881f55f8e8df7c8c1d651b204`. No new fitting is allowed against this protocol.

The validation-selected character TF-IDF candidate is evaluated at the predeclared 5% validation FPR operating point. Scores below describe historical URL annotations, not live-site safety.

| Frozen track | URLs / components | Precision | Recall | F1 (component-bootstrap 95% interval) | False-positive rate (95% interval) | Legitimate-query false positives |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Primary, original v2 owners | 166,369 / 78,202 | 0.9319 | 0.9223 | 0.9271 (0.9083–0.9396) | 5.76% (3.75–8.91%) | 13/52 = 25.0%; 14 components |
| Supplemental, Mendeley group holdout | 4,348 / 3,265 | 0.8296 | 0.8483 | 0.8388 (0.8162–0.8591) | 22.39% (19.42–26.03%) | 27/44 = 61.36%; 44 components |

Primary confusion counts are TP 70,712, FP 5,168, TN 84,535 and FN 5,954. Supplemental counts are TP 2,074, FP 426, TN 1,477 and FN 371. The query false-positive intervals are broad: 8.10–58.63% primary and 47.67–75.00% supplemental. These subgroup estimates use only legitimate query URLs; they say nothing about phishing recall for queries. All intervals use 1,000 seed-42 whole-connected-component bootstrap replicates. The supplemental track is smaller and not source-independent.

The lexical HGB branch reached F1 0.8751/FPR 3.02% on primary and F1 0.6920/FPR 30.85% on supplemental. The format-only diagnostic reached F1 0.4863/FPR 0.31% primary and F1 0.6924/FPR 21.65% supplemental; it was never eligible for model selection. Fixed Phase-0 rules and the 1% validation-FPR sensitivity operating points are also included in the JSON. For the selected model, that stricter sensitivity gave primary FPR 1.71% and supplemental FPR 8.67%, with lower recall. These are frozen secondary results, not thresholds chosen from final rows. Historical v1 cohorts are not headline comparators, and v2 has no fitted model.

The local CPU cold load plus first prediction took 3.290 seconds; 100 warm distinct URLs had median 13.1 ms and 95th percentile 16.2 ms. These are machine-specific measurements, not a web-service latency guarantee.

The large supplemental false-positive rate, high query false-positive counts and the `example.com` smoke false positive mean the candidate is **not suitable for live warnings**. No profile, harmful-content or paired message–link benefit follows from this URL-only evaluation. External contemporary and authenticated temporal validation remain unavailable; the application continues using its existing non-ML behavior.

## Final preservation and verification

The post-run rehash found **zero changes** among 27 protected v1/v2/case/intake files, zero changes among the 17 exact installed dependency pins, and zero admitted rows in the paired-message intake. The evaluation receipt, candidate and row-level score evidence remain ignored private files. The public output contains aggregate status, metrics and explanatory limitations. All three staged public files matched their sealed on-disk bytes exactly; the staged evaluation SHA-256 still equals `a6308501297956298e78bb9f6ff05e155cd92a2881f55f8e8df7c8c1d651b204`. The final post-review Python suite passed 191/191 with zero skips in 241.954 seconds, including the stdlib-only API check and the buffered-read regression; the Node web suite passed 12/12 with zero skips in 0.421 seconds.

## Independent review and integration

The approved single independent whole-branch review inspected the complete URL-v3 change against the approved design and measured evidence. It reported one Important finding, no Critical or Minor findings: `HTTPResponse.read(n)` can consume bytes inside a buffer and then raise `TimeoutError` without exposing a partial result. The old handler cleared the reserved `n`, allowing a later retry to undercount HTTP body bytes. The reviewer confirmed the protected ownership and publication boundaries, and declined to independently establish source-label truth, current real-world accuracy or an instantaneous memory ceiling between samples. Those limits remain stated above.

The finding was reproduced with a real `HTTPResponse` and `BufferedReader`: three body bytes were consumed during `read(8)`, while the old journal recorded zero measured and zero uncertain bytes. A regression failed on that exact outcome. The fix now records zero measured and eight uncertain bytes, persists the charge across reopening, and refuses another network attempt once the test budget is exhausted. Eight URL-v3 transport and eight existing URL-v2 range checks pass; the complete post-fix suite passed 191 Python and 12 Node checks. Integration receipts follow after the final local and remote verification. No second review or final scoring run was performed. No learned warning is activated by integration.
