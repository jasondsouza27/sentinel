# URL source audit

Audited on 2026-10-05 for Sentinel's first trained URL-string subsystem.

[PhiUSIIL, Prasad and Chandra (2024), UCI dataset 967](https://archive.ics.uci.edu/dataset/967/phiusiil%2Bphishing%2Burl%2Bdataset) is licensed CC BY 4.0. Source label 0 means phishing and 1 means legitimate; Sentinel reverses these explicitly. Only the URL column is used to derive features; webpage and population features are discarded. Source labels are historical benchmark annotations, not current verification of sites.

The acquired CSV contains **235,795** records, matching UCI's advertised count. After canonical duplicate removal and strict URL support checks, **235,343** remain: **100,493 phishing** and **134,850 legitimate**, across **197,293** domain groups. Exclusions: **439 duplicates**, **8 oversized/empty URLs**, **5 invalid hosts**, **0 conflicting-label rows**.

The [official Public Suffix List](https://publicsuffix.org/list/) snapshot includes private domains and is reused offline under MPL 2.0. The original acquisition, audit rows and private exclusion references stay in ignored local storage. No source URLs or tokens are published. Nothing from this URL-only audit is admitted into the paired-message intake.

| File | SHA-256 |
|---|---|
| source.csv | `a236549cd369cd80bd478ff8e1779cbf44c58d5c3f79f7a51a1adbed7d06d1c6` |
| source.zip | `0a639fd03aea6308c5b1c10c92aa23c2ce1505447a9137271865cd0badc9a59a` |
| suffix.dat | `e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66` |
| derived rows | `593c39ddb0d0c8825c1a0b06987659f3dfdb0ddba6d6e11c4cec00d1570a508e` |

Seed-42 whole-domain allocation is frozen at 70/10/10/10. Both classes appear in every partition; all row IDs and domains are isolated. Largest retained domain group: 3079 rows. Assignments are private; the table reports only aggregate counts.

| Partition | Rows | Phishing | Legitimate | Groups |
|---|---:|---:|---:|---:|
| calibration | 23534 | 10049 | 13485 | 19729 |
| test | 23534 | 10049 | 13485 | 19729 |
| train | 164741 | 70346 | 94395 | 138106 |
| validation | 23534 | 10049 | 13485 | 19729 |

Comparison and calibration results will be published after their own evaluation gates.

Training-only pilot: 2,000 rows from 1,810 whole training groups. Character TF-IDF peak working set 161030144 bytes, lexical HGB 143659008 bytes; each used four native threads and its own process. Both stayed below 8 GiB; the 50,000-character-feature cap remains unchanged. Full-data measurements still need to be recorded.

## Deployment limitation found during actual evaluation

All retained legitimate URLs have HTTPS, www-prefixed hosts, empty paths and no query. The source does not cover legitimate ordinary page/query formats. A separate benign smoke check falsely flagged a reserved documentation URL and Python documentation. This is source-format confounding, retained across domain-isolated splits. The frozen candidate remains research-only; see the [final model card](../output/research/url-ml-v1/model-card.md) and [aggregate format audit](../output/research/url-ml-v1/source-format-audit.json). No test/staged-case tuning or intake admission was performed.
