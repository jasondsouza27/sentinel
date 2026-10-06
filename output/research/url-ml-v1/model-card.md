# Sentinel URL-v1: research-only candidate

Completed first ML foundation milestone on 2026-10-06. **Do not present url-v1 as a reliable live detector.** The reproducible pipeline works, but this source does not support deployment claims.

## Main finding: source-format confounding

All **134,850 legitimate** retained source URLs are **HTTPS, www-prefixed homepages with an empty path and query**. Legitimate documentation pages, query-bearing URLs and non-www hosts are absent. The phishing class contains varied formats. Domain-disjoint partitions therefore retain this class/source correlation. The strong held-out scores below do not establish generalisation across ordinary browsing URLs.

A separate staged smoke check flagged `https://example.org/` and `https://docs.python.org/3/library/urllib.parse.html`. The former is an [IANA documentation domain](https://www.iana.org/help/example-domains); the latter is an [official Python documentation page](https://docs.python.org/3/library/urllib.parse.html). These checks are separate from the final test and did not cause tuning, whitelisting or retraining. Their values are recorded by staged case name, without admitting any cases into research intake.

## Frozen benchmark

Train 164,741; validation/calibration/test 23,534 each. Seed 42; whole registrable/private-domain groups. Final test has 19,729 groups. Source label 0 phishing maps to Sentinel 1; only derived URL features were used.

| Method | Precision | Recall | Positive F1 | False-positive rate |
|---|---:|---:|---:|---:|
| Character TF-IDF + logistic (selected) | 94.48% | 99.80% | 97.07% | 4.35% |
| Lexical histogram boosting | 94.31% | 99.38% | 96.78% | 4.47% |
| Phase 0 URL rules | 78.15% | 7.65% | 13.94% | 1.59% |

Selected configuration: C=10, no class weighting, 50,000 sparse features. Raw validation threshold: `0.018116173898282417`. Threshold stays frozen after calibration.

| Selected metric | Estimate | 95% whole-domain interval |
|---|---:|---:|
| Precision | 94.48% | 93.47% to 95.44% |
| Recall | 99.80% | 99.71% to 99.89% |
| Positive F1 | 97.07% | 96.51% to 97.59% |
| False-positive rate | 4.35% | 4.00% to 4.73% |

Confusion counts: TP 10029, FP 586, TN 12899, FN 20. Intervals use 1,000 seed-42 domain resamples. Average precision is 0.999394. Supported-input coverage is 1.0; exclusions are reported in the source audit.

Sigmoid calibration passed its sample/slope guards on 23,534 separate rows. Test Brier 0.002013, 10-bin ECE 0.001526. These are within-source reliability measurements; the staged errors show they do not make numerical outputs live-site confidence. Other baselines were not calibrated, so their probability metrics are null.

## Resources and practical limits

Ten sequential CPU fits succeeded. Maximum peak working set 990,318,592 bytes (0.92 GiB); summed fit time 493.45 seconds. Four native threads; no GPU/PyTorch dependency. Cold load plus first assessment 1.151 seconds; warm median 6.75 ms and p95 9.09 ms over 100 test URLs. The cold figure starts in an already-imported Python process; a fresh CLI process additionally pays import/startup overhead.

At assumed 0.1% prevalence, the measured rates imply only 2.25% expected precision, assuming those rates transfer. Actual live rates are unvalidated. Alerts require review; not-flagged is never safe. Submitted sites, DNS, redirects, reputation and account history are not requested by this model.

## Artifact and reproduction

The artifact reference is SHA-256 of canonical manifest JSON (sorted keys, compact separators), not the pretty-printed file bytes: `020db47e5103e0eb28194a793c5ddd37a8e4f0a161da2ffd45ae4b0899b59709`. Every component file also has its own byte checksum. Binary models, raw rows and frozen assignments stay local and ignored. Final reports are outside the immutable artifact. [Workflow](../../../docs/url-ml-workflow.md) and [source audit](../../../docs/url-ml-source-audit.md) provide commands, attribution and hashes.

The frozen split manifest reproduced exactly. An independent repeat of the selected fit reproduced all 500 validation scores with maximum absolute difference **0.0** (tolerance 1e-6). The committed lock passed **68 Python tests without dependency skips** and **12 web-client tests** in a fresh environment. The stdlib server entry point also passed without ML packages on a separate ephemeral port.

## Next gate

Expand both labels with diverse legitimate paths, queries, schemes and host formats; include independently obtained source and temporal holdouts. Pre-register a new version and repeat evaluation before considering deployment. Do not repair this frozen benchmark by whitelisting staged examples. Genuine paired-message collection, contextual harm/profile models, investigation UI and the usability pilot remain separate future milestones.
