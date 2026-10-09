# Sentinel URL v2 research card: training blocked

Recorded on 2026-10-09. **No URL v2 model was fitted, exported, calibrated or scored.**
This is the measured result of the data-quality gate, not an accuracy report. The normal
application continues to use its existing indicators with learned URL warnings disabled.

## Data and frozen protocol

The pinned PhreshPhish release supplied 666,315 observations across 77 Parquet shards.
The URL-only importer journal counted 45,871,391 payload bytes including metadata and
requested-range retries; dataset HTML was excluded. The inherited approved-redirect
handler could drain unmetered intermediate bodies, so this historical number does not
prove total transfer or the cumulative cap. The reviewed fix closes those bodies without
reading them; no retrospective redirect-body total or fresh acquisition is claimed. Audit retained 660,130 canonical URLs (362,228 benign, 297,902 phish)
from 660,164 usable observations. There were 34 duplicate observations and no label
conflicts. The 6,151 excluded source observations and all original provenance remain private.
Source labels are historical annotations, not checks of live websites.

Whole connected components preserve domain/opaque-identifier isolation. Published test
ownership takes priority: 213,286 canonical URLs with held-out component overlap cannot
enter development. Seed 42 selected 200,000 whole-component development rows; another
80,475 eligible rows were excluded by the development cap. These rules were fixed before
fitting. The split contains 160,000 train, 20,000 validation and 20,000 calibration rows.

| Benign development format | Observed | Required | Gate |
| --- | ---: | ---: | --- |
| Non-root path | 63,850 | 100 | Pass |
| Non-www host | 34,320 | 100 | Pass |
| Query present | 6 | 30 | **Fail** |

Class and domain support is sufficient in train/validation/calibration, but the pooled
benign-format gate fails. Training must stop: a large corpus alone does not establish
coverage of ordinary browsing URLs. No seed, minimum, cap or ownership rule was changed
to obtain a passing result; final rows were not borrowed for training.

| Track | Rows | Data support | Measured model result |
| --- | ---: | --- | --- |
| Primary published-test holdout | 166,369 | Available; 78,202 components | Unavailable: model not trained |
| External historical holdout | 0 | Unavailable: official source access pending | Unavailable |
| Chronological validation | Unavailable | Unavailable: dates unauthenticated | Unavailable |

The primary holdout includes 52 benign query-bearing URLs. This observation describes
support only; it cannot authorize moving those rows into development. A source-separated
track does not by itself establish independence from campaigns or templates. All v2
precision, recall, F1, FPR, calibration, confidence intervals and comparison metrics are
**unavailable**, and no improvement over v1 is claimed.

## Acquisition and resource evidence

The two-shard transport/schema pilot decoded 2,000 rows in 28.1 seconds with 273,377
journal-counted bytes and 55,062,528 sampled peak RSS bytes. The complete projection took
1,797.7 seconds and 68,829,184 sampled peak process-tree RSS bytes. Its largest footer
was 5,257 bytes, selected column span 355,922 bytes and decoded batch 4,096 rows.

The complete canonical audit took 848.7 seconds and sampled 88,920,064 peak RSS bytes.
Freezing the protocol took 715.5 seconds and 2,514,509,824 sampled peak RSS bytes.
These are acquisition/audit resources, **not model-training or inference measurements**.
The real ML-runtime readiness guard returned 2 with `training_support_incomplete`
before fitting, verified all 10 original audit/protocol files unchanged, and peaked at
2,525,544,448 sampled process-tree RSS bytes in 784.8 seconds. This confirms that the
canonical-reader performance correction retains the original real-data sidecars. Sampling at
100 ms can miss short memory spikes. No trained-fit 8 GiB limit result is claimed.

Pinned inventory, strong object identity, exact content ranges and cached-range SHA-256
were checked. Full source objects total 36,576,373,578 bytes; they were not downloaded.
`full_file_checksum_verified` stays false. Signed transport queries and submitted URL
samples are excluded from public output. Source `date32` values have no authenticated
collection semantics; parsing them cannot establish a chronological holdout.

## Software verification and next work

The fresh union of both Windows CPython 3.11 locks contains 17 exact pins with nine
identical overlaps; the original ML lock is unchanged. The canonical-reader correction
and four independently reviewed corrections passed 130 Python checks with zero skips;
the web client passed 12 checks. The default
stdlib-only API also passed. The original 32 private v1/case/intake files remained unchanged.
Fixture models demonstrate software behavior only; their scores are not project results.
The independent review found four important boundary defects; all four were reproduced
and fixed. Post-fix semantic validation preserved all original real-audit hashes.
Review dispositions are in the [delivery record](../../../docs/url-v2-delivery-record.md).

The next data milestone needs annotated legitimate paths, non-www hosts and queries,
with source/channel/date evidence, a new frozen protocol version and an independent final
set. Do not relax this gate, fabricate URLs, tune against this holdout or enable learned
user warnings. The broader year-long paired-message, harm/profile ML, investigation app
and usability work remain separate milestones.

See [aggregate status](research-status.json) for counts, exact hashes, resource receipts
and null metrics, and the [workflow](../../../docs/url-v2-workflow.md) for reproduction.

## Attribution

[PhreshPhish dataset](https://huggingface.co/datasets/phreshphish/phreshphish), revision
`eabec4b7a66324b79cc8a0ad856d1731dc26fe1a`, is CC BY 4.0. Cite the
[authors' paper](https://arxiv.org/abs/2507.10854). The source URLs are projected into
private local files; public results contain aggregate counts only. The unmodified frozen
[MPL-2.0 suffix snapshot](../../../resources/README.md) is public reference metadata.
No official [ISCX-URL2016](https://www.unb.ca/cic/datasets/url-2016.html) files or mirror
were admitted.
