# Sentinel URL-v2 source feasibility audit

Initial feasibility review: 2026-10-07; implementation/acquisition evidence: 2026-10-08;
frozen outcome recorded on 2026-10-09. The following initial sections describe what was
known before the approved [design](superpowers/specs/2026-10-07-sentinel-url-v2-data-design.md)
and plan were implemented. Later sections record the complete 77-shard acquisition.
**V2 training is blocked by benign-query coverage (6 observed, 30 required).** See the
[research card](../output/research/url-ml-v2/model-card.md) and [delivery record](url-v2-delivery-record.md).

## Primary candidate

[PhreshPhish dataset card](https://huggingface.co/datasets/phreshphish/phreshphish)
provides URL, label, date and identifier metadata alongside HTML. Its preview includes
benign non-homepage paths. The card declares CC BY 4.0 and anti-phishing research use.
The displayed corpus occupies about 36.6 GB; it is unsuitable for a naive full download
for this URL-only task. Published cardinalities are descriptive, not Sentinel audit counts.
One stated test total disagrees with the sum of its stated class counts, so use locally
measured accepted counts rather than treating the card as an integrity manifest.

The [authors' paper, revision 2](https://arxiv.org/html/2507.10854v2) describes collection
from multiple phishing feeds and benign browsing/search observations, with temporal and
similarity filtering. Those methods do not prove live labels or guarantee Sentinel's
URL/domain protocol; collection dates and overlap must be audited on the selected release.
[Authors' code](https://github.com/PhreshPhish/phreshphish) is reference material only;
Sentinel will not execute a downloaded dataset script.

Public [repository metadata](https://huggingface.co/api/datasets/phreshphish/phreshphish)
was read through HTTPS on this date. It reports public, ungated access and immutable revision
`eabec4b7a66324b79cc8a0ad856d1731dc26fe1a`, last modified 2026-02-09. The inventory lists
56 training and 21 test Parquet shards. Benchmark lists were not fetched or used as cases.

A bounded request to the pinned `data/train-000.parquet` read only its final eight bytes:
HTTP 206, `Content-Range: bytes 49639678-49639685/49639686`, Parquet `PAR1` footer marker,
and footer-metadata length 1,653 bytes. The redirect ended on `us.aws.cdn.hf.co`; signed
transport parameters were neither recorded nor published. This demonstrates one range
response only. Whole-source projection size, schema consistency, source checksums and
format coverage remain unmeasured. The existing bundled Python has no PyArrow, and no
installation was attempted during the design stage.

[Apache Arrow's ParquetFile documentation](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetFile.html)
supports column selection and batch reading. The design requires a bounded reader that
prevents whole-shard/HTML fallback; a production implementation must verify those limits
with request tracing and refusal tests before acquiring the corpus.

## External historical candidate

[ISCX-URL2016 official description](https://www.unb.ca/cic/datasets/url-2016.html)
describes crawled benign page URLs and distinct phishing, spam, malware and defacement
categories. Use only benign/phishing categories for the proposed binary experiment.
The [UNB dataset policy](https://www.unb.ca/cic/datasets/) requests dataset/paper citation
for use or redistribution. Do not assume all categories mean phishing or that old labels
represent present website status.

The linked [official distribution](https://cicresearch.ca/CICDataset/ISCX-URL-2016/)
presents a personal-information form and currently displays a server error. Nothing was
submitted. No official archive bytes/member schema/checksum has been verified. Therefore
this candidate remains acquisition-pending, with a proposed local-file adapter after
acquisition through the official process. No arbitrary mirror is admitted by this audit.
Without authentic per-row dates it cannot support a temporal claim.

## Other sources and decisions

[PhishTank developer documentation](https://phishtank.net/developer_info.php) describes
verified/online records with submission and verification times. Unkeyed acquisition is
limited; no key was requested and no feed downloaded. It is positive-only and potentially
shares records with PhreshPhish, so it is not a complete independent classification test.

The existing PhiUSIIL source/model stay frozen. Popular-domain lists and handpicked benign
examples are not an adequate replacement for diverse, task-aligned source annotations.
The existing paired-message intake remains a separate human-review workflow.

Recommendation: implement PhreshPhish URL-column acquisition and a multi-source canonical
manifest/isolation workflow; support officially acquired ISCX local input without claiming
that external validation is already available. Keep model activation disabled while the
new robustness tracks and the application's release checks remain incomplete.

## Implementation evidence (2026-10-08)

The approved importer now has real multi-row-group Arrow fixture tests proving that
metadata-only footer parsing and selected-column reads avoid HTML/lang chunks. Catalog
revision/hash checks, hostile/expired redirects, interrupted bytes, cumulative resume
budgets, corrupt caches, external column files and immutable publications are tested.
The separate ten-pin ingestion lock includes verified PyArrow 25.0.1; the ML lock is
unchanged. The bundled MPL-2.0 suffix snapshot is byte-identical to the original.
These initial software/transport checks used invented fixtures, not research cases or
accuracy results. The complete real acquisition and measured gates are recorded below.
Official ISCX members remain unavailable; no form was submitted or mirror used.

## Complete pinned metadata acquisition (2026-10-08)

All 77 shards were projected: 498,255 published train observations and 168,060
published test observations, 666,315 in total. This confirms the actual test-row
count; the inconsistent card class totals are not substituted for measured counts.
All shards use large-string URL/label/opaque-hash fields and date32 day fields.
HTML, target, language and language-score fields were excluded from every view.

The full run received 45,871,391 payload bytes (43.7 MiB), including its metadata
receipt and retries, versus 36,576,373,578 bytes of whole source objects. The largest
footer was 5,257 bytes, largest selected column span 355,922 bytes and largest
batch 4,096 rows. Observed peak process-tree RSS was 68,829,184 bytes; elapsed
time was 1,797.7 seconds. The separate two-shard pilot read 2,000 rows, received
273,377 bytes and peaked at 55,062,528 observed RSS bytes in 28.1 seconds. Neither
pilot scores nor invented test fixtures are research findings.

The range journal records 567 attempts: 23 timeouts, four remote disconnects and
one temporary local journal-replacement lock. Every retry retained its received
bytes; the local lock retried one already-received column without resetting the
budget. Cached ranges, strong object identity, pinned catalog and column bounds
were checked. These are partial-object range checks: full-file hashes were not
computed and `full_file_checksum_verified` remains false. No submitted URL was
requested, and the original HTML corpus was not downloaded.

The catalog manifest SHA-256 is
`03801cab6a2c91e0b8df2b3c0863e6351a24b0704765d0d1ce42d0e311142675`;
the projection manifest SHA-256 is
`9a7569d8c5e3985551099480256fd842b90ed1f05778bde87fb390c2858b7219`.
Date semantics remain unauthenticated. Canonical audit, frozen support gates and
research outcomes are recorded separately in the delivery report. The official
ISCX distribution was rechecked on this date and still showed its form and server
error; no information was submitted and no archive or mirror was admitted.
