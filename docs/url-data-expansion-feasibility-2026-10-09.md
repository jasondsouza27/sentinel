# Sentinel: URL data expansion feasibility

Research recorded on 2026-10-09. This is a source investigation and a recommendation, not an approved URL-v3 specification or a completed training run. The [aggregate evidence](../output/research/url-data-expansion/source-feasibility.json) contains counts, source identities and remaining checks without raw case URLs.

## Intended outcome

The user wants a year-long engineering project balancing trained ML research with a usable investigation application. The established laptop constraints are CPU-first execution with four worker threads and an 8 GiB fitting limit. This investigation assumes the next priority is the URL training-data gap named in the [completed v2 delivery](url-v2-delivery-record.md). Success here means finding a documented, licensed source whose actual full URLs could broaden legitimate coverage without changing the frozen v2 experiment.

## The current corpus cannot close the gap by increasing its cap

A read-only scan of all 660,130 audited v2 canonical URLs found 68 legitimate query-bearing URLs across 28 domain groups. Only **7** are eligible for development before the cap; the frozen 200,000-row development set contains 6 and the cap-excluded pool contributes just 1. Both values are below the required 30. The protected primary cohort and its connected components cannot be moved into training to rescue coverage.

The original audit and protocol manifest identities still match the delivered hashes. All eight data sidecars also match the checksums in those manifests. No v2 data, ownership, seed, cap, support threshold or model changed during this investigation.

## Recommended candidate: Hannousse and Yahiouche's URL benchmark

The official [Mendeley version 3](https://data.mendeley.com/datasets/c2gw7fy2j4/3), DOI `10.17632/c2gw7fy2j4.3`, declares CC BY 4.0 and May 2020 collection. Its small `dataset_B_05_2020.csv` includes URL strings and explicit legitimate/phishing labels. The [authors' paper](https://arxiv.org/html/2010.12847) describes crawling beyond popular-domain homepages, additional Yandex-derived legitimate samples, PhishTank/OpenPhish positives and a per-domain collection cap. Those methods leave source-selection and shared-feed limitations; they do not establish contemporary safety or statistical independence.

The official public file inventory supplied a 3,661,166-byte CSV and SHA-256 `21093e2902e5441c86a6daf95e86e7c332046e477fdf109a579d7bd81e586d6c`. A complete, bounded, in-memory read matched both. The inspected CSV was not saved, admitted to training or added to the paired-message intake. No dataset script, HTML/pickle object or submitted destination was opened. Inspection used only URL and status fields; published network/content feature columns were not used as Sentinel inputs.

The raw table contains 11,430 rows, split equally between its two labels, including 191 legitimate URLs with queries. The existing offline parser excluded 10 observations and collapsed 2 further canonical duplicates, leaving 11,418 canonical URLs. There were no within-source contradictory canonical labels.

| Preliminary canonical population | Legitimate URLs | Legitimate query URLs | Query domain groups | Phishing URLs |
| --- | ---: | ---: | ---: | ---: |
| Whole candidate | 5,710 | 191 | 117 | 5,708 |
| Outside all frozen v2 primary-reserved domains | 3,895 | **92** | **87** | 5,150 |
| Overlaps those reserved domains | 1,815 | 99 | 30 | 558 |

This overlap screen covers domains in primary-owned cases and cases excluded for belonging to primary-reserved connected components. It is reconnaissance, not a replacement for a joint canonical/conflict audit. Additional exclusions and new final-set reservations may reduce the 92 candidates. No new split or passing training gate is claimed.

## Alternatives and trade-offs

1. **Use the measured Mendeley candidate first (recommended).** The official URL table is small, checksum-verifiable and contains both classes with useful query diversity after the preliminary overlap screen. Its age and collection sources must remain visible. A new version must specify source roles and protected final cohorts before fitting.
2. **Audit Phish360 first.** The [authors' paper](https://www.mdpi.com/2076-3417/16/2/751) describes 10,748 samples, including legitimate login pages, and academic availability. Their [repository](https://github.com/almakhamreh/Multimodal-Phishing-Benchmarks) links a roughly 0.6 GB Parquet release. No file identity, local query coverage or Sentinel split independence has been measured here. Two direct author-page fetches timed out. This is a promising later source, with a larger transport/metadata audit before use.
3. **Prioritize fresh, team-reviewed collection.** The [existing collection workflow](collection-workflow.md) can gather consented, authentic message-link pairs and supporting evidence. It best matches the real application and year-long combined-evidence question, but requires human participants, reviewers and time; software cannot invent their labels or dates. It remains necessary whichever URL benchmark is selected.

The official [Grambeddings route](https://web.cs.hacettepe.edu.tr/~selman/grambeddings-dataset/) uses a required researcher-information form; nothing was submitted. The official [PhishStorm record](https://research.aalto.fi/en/datasets/phishstorm-phishing-legitimate-url-dataset/) lists its dataset licence as unspecified. Neither was automatically acquired or admitted.

## Proposed next design scope

Subject to the user's source/design decision, prepare a URL-v3 specification around the measured Mendeley source: a bounded official-file adapter, explicit historical label/date provenance, a joint conflict audit, and new frozen training/validation/calibration/final cohorts that keep connected domains together. Preserve the existing v2 files and protected holdout domains. Keep a complete source-role and exclusion ledger, and require support/coverage checks before a resource-capped fit.

Evaluation would report per-source results, legitimate-query false positives, uncertainty, source shortcuts and missing date/campaign evidence. Threshold/model selection must use development data; final cohorts cannot guide tuning. A group-held-out cohort from a training source must be named as such, not represented as an independent-source or chronological test. Contemporary team-reviewed cases remain a separate requirement for real-life validation.

The approved execution preference remains inline implementation with one independent final review. Product code, a new frozen protocol, fitting and application activation have not started. The user approved this source/design direction on 2026-10-09. The user also approved the [written URL-v3 specification](superpowers/specs/2026-10-09-sentinel-url-v3-design.md) on 2026-10-09. Its [detailed implementation plan](superpowers/plans/2026-10-09-sentinel-url-v3.md) now awaits review; implementation has not started.
