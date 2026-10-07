# Sentinel URL v2: multi-source data and robustness design

Date: 2026-10-07. Status: proposed; awaiting review of this written specification.
Parent: [approved year-long design](2026-10-05-sentinel-year-long-design.md).
Existing reference: [URL-v1 model card](../../../output/research/url-ml-v1/model-card.md).
Source evidence: [v2 source audit](../../url-v2-source-audit.md).

## Agreed intent and scope

The user requested a substantial year-long engineering project with balanced ML research
and a usable application. They approved the first ML foundation and asked to continue
with the proposed multi-source importer and v2 evaluation workflow. The purpose of this
follow-up is to make URL research cover ordinary browsing formats and measure whether
performance persists across domains, collection periods and sources. A larger dataset
or a higher headline score alone is not success.

Constraints carried forward: Ryzen 7 7435HS, 16 GiB RAM, CPU-first training, at most four
native training threads, at most 8 GiB training-process RAM, no compulsory paid service,
HTTP(S) inputs capped at 2,048 characters, and no request to a submitted destination.
English remains the application language; URL metadata does not establish page language.

This design adds research data acquisition, source adapters, provenance, isolation,
format audits, frozen robustness evaluations and documentation. It reuses the existing
model factories and inference adapter. Message fusion, harm/profile ML, authenticated
team workflows and dashboard redesign follow their own focused specifications. Personal
cases, feedback and the empty paired-message intake are not training inputs here.

## Approach decision

| Approach | Benefit | Cost or limitation |
| --- | --- | --- |
| **Pin and project a documented corpus, then hold out a second source** | Practical benign page formats, traceable observations, bounded acquisition and independent checks | Additional Parquet ingestion dependency; historical external source access is pending |
| Add handpicked benign links to PhiUSIIL | Small acquisition effort | Selection bias and demonstrated-test tuning would undermine the experiment |
| Crawl arbitrary sites and build a new labelled corpus | Potentially current observations | Crawling does not establish labels; expands data-access and infrastructure scope |

Use the first approach. Preserve url-v1 and its frozen results as a historical reference.
The earlier in-chat v2 outline supplies the direction; approval of this written design
is required before producing its detailed implementation plan.

## Sources and labels

Primary candidate: [PhreshPhish](https://huggingface.co/datasets/phreshphish/phreshphish),
pinned to revision `eabec4b7a66324b79cc8a0ad856d1731dc26fe1a`. Use only `url`, `label`,
`date` and opaque source identifier `sha256` from its published train/test Parquet files.
Map `benign -> 0`, `phish -> 1`. Record its CC BY 4.0 attribution and stated anti-phishing
research use. Actual accepted counts and date semantics must be measured locally.
Its [paper](https://arxiv.org/html/2507.10854v2) describes temporal partitioning; Sentinel
must check the pinned release rather than assume that property holds automatically.

External candidate: official [ISCX-URL2016](https://www.unb.ca/cic/datasets/url-2016.html).
Accept local files obtained through its official distribution, with source citation,
original filename/member identity and local SHA-256. Declare CSV URL-column/header or
one-URL-per-line format explicitly; never infer labels from a renamed file. Admission
requires an audited category-to-original-member mapping. An unknown member schema is
unsupported until that source adapter is documented, rather than guessed. Admit only documented benign and
phishing categories: `benign -> 0`, `phishing -> 1`. Exclude spam, malware and defacement.
A download date is not a source observation date. The official form currently has an
access error, so acquisition is pending; no unattended form submission, mirror substitution
or invented availability is part of this design.

[PhishTank](https://phishtank.net/developer_info.php) remains a future positive-only
snapshot/reputation input. It cannot supply a complete benign-versus-phishing holdout,
and it may share upstream records with other corpora. Neither a missing feed entry nor
a popular-domain ranking establishes a legitimate label. PhiUSIIL is a documented bias
reference, not a silent source of v2 benign examples. Do not generate URLs, invent dates,
repair scheme-less source URLs by guessing a protocol, or relabel uncertain records.

Source labels are historical source annotations, not Sentinel's verification of live sites.
Published sources can share feeds, domains and campaigns. “Source-disjoint” describes
release separation; statistical independence must not be claimed merely from names.

## Acquisition and reproducible storage

Use a new ignored `data/url-ml-v2/` root. No source or report is written over url-v1.
Separate source manifests, projected raw metadata, audited rows/exclusions, frozen
assignment manifests, run diagnostics and evaluations. New binary models use an immutable
version under the existing ignored `models/url-ml/` root. Public output contains aggregate
reports and permissioned examples only; private URL tokens never enter Git or logs.

PhreshPhish acquisition resolves the pinned release's file inventory and records sizes,
source object identifiers, expected full-file hashes when supplied, and the pinned card.
Read exact Parquet footer ranges, then only selected metadata column chunks. A seekable
HTTP range reader must validate HTTPS redirects, status 206, Content-Range, identity
encoding, stable object identity and requested byte counts. Use fixed source repository
paths; never follow a URL stored in a row. Initially allow only `huggingface.co` and the observed `us.aws.cdn.hf.co`;
any additional redirect host needs a documented source-endpoint audit before being allowed.
Signed CDN query strings are transport details and must not enter manifests or logging.

Use PyArrow for metadata and projected batch decoding, with prebuffering disabled and
bounded metadata parsing. Do not deserialize pickle, execute dataset scripts, load HTML
columns or invoke a page renderer. A reader must refuse requests into excluded HTML column
ranges; do not silently fall back to downloading a whole shard if range access fails.
A source projection preserves original fields and has its own SHA-256. Partial-file
acquisition must explicitly say `full_file_checksum_verified: false`; a published full
object hash is expected metadata, not a checksum Sentinel actually computed.

Initial limits: 30-second network timeout, at most three retries per failed range,
2 MiB footer limit, 32 MiB individual selected-column range limit, and 2 GiB total acquired
response bytes for one projection run. Account for retries and rejected responses. No
concurrent shard reads; decode at most 4,096 rows per batch with decoding threads disabled.
Abort with preserved diagnostics when a cap, schema check or source-identity check fails.
No completed projection manifest is published for a partial run. Resume only byte-verified
ranges belonging to the same revision, inventory and projection configuration.

These are proposed bounds, not observed complete-corpus requirements. Run a small range/
decoding pilot first. If the release exceeds a bound, stop and amend the declared protocol
before acquisition or modelling; do not quietly take the first files and report them as
representative. The eight-byte footer probe establishes range support, not complete import
performance or safety.

Keep ingestion dependencies in a separately locked Windows Python 3.11 environment,
`.venv-url-data`. Resolve and verify a compatible PyArrow wheel during implementation.
Keep the existing model lock and `.venv-ml` unchanged. Standard server startup must remain
free of PyArrow and other optional ML imports.

## Canonical records and integrity

An observation records source ID/revision, original split/category, shard and row ordinal
or local file/member/line, original URL, source label and authentic source date with its
meaning. Missing dates stay missing. Stable observation IDs derive from the pinned source
identity and row reference; source identifiers are never model features.

Reuse the corrected offline UrlParser with the frozen private-inclusive PSL snapshot
(SHA-256 `e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66`)
and its implementation revision/hash. Do not auto-update the snapshot during a run. Preserve original display text separately. Retain all
provenance observations when multiple records normalize to one URL; count exact duplicates.
If canonical labels conflict, exclude all observations for that URL. Unsupported URLs,
invalid labels, missing fields, oversized values and malformed dates have distinct audited
reasons. Unknown suffixes are flagged and their full-host grouping limitation disclosed.

V2 manifests distinguish a source-catalog digest from individual source-file hashes. They
must have separate dataset/protocol versions; the single-source v1 loader must not accept
them accidentally. A documented conversion can produce existing UrlRow/DatasetBundle
training inputs while keeping v2 provenance and its digest meaning explicit. Source
catalog digests have their own named fields; source-file digests retain their original
meaning. A compatibility envelope must identify the provenance schema and be validated
before training or artifact export. Changes to
training/artifact metadata must preserve v1 loading and cannot reuse a v1 field silently
with a different meaning. No source, split, date or provenance identifier becomes a feature.

## Freeze before fitting

Reserve the author's PhreshPhish test observations for final evaluation; never return them
to training to meet a size target. Within eligible published training observations, allocate
whole domain groups to train/validation/calibration at target 80/10/10, seed 42. A deterministic
whole-group development cap is 200,000 rows, chosen by seeded group order with the selection
algorithm and skipped groups recorded. Size limits can exclude a large group but must never
split it; publish how that affects coverage and source/class/format distributions.

Domain/IP and equivalent-URL groups stay together across all model-development partitions
and held-out tracks. Equal opaque source IDs also form one component within the same source.
Held-out ownership wins when a group occurs in development and a reserved test: prune its
development observations, retain the reserved test observations and count the removal.
Holdout-domain lists can enforce isolation, but holdout labels cannot tune model selection.

An admitted ISCX benign/phishing corpus is an external historical holdout, entirely excluded
from fitting, threshold selection and calibration. Remove overlaps with development and the
primary test under the declared priority, recording every exclusion and retained count. A
second release sharing feeds is not an independent replication; unknown campaign/template
relationships remain a stated limitation. No random-row fallback is allowed.

For the temporal claim, require authentic collection-date semantics and check that every
used development date is earlier than every retained primary-test date. If this fails or
semantics are unresolved, report temporal validation unavailable and explain the diagnostic;
do not shift the cutoff after seeing model scores. An ISCX source with no authentic row
dates is historical external validation, not a prospective or time-correct test.

Both labels are required in every development and evaluable held-out track. Minimum final
track support is 100 rows and 30 domain groups per class; the same minima apply to validation
and calibration before modelling. Training requires 1,000 rows and 100 groups per class.
Failure leaves the affected experiment incomplete; it cannot be replaced by synthetic cases.
Development and primary-test benign data must each include at least 100 non-root-path,
100 non-www-host and 30 query-bearing URLs, with overlap among strata allowed. These are
format-coverage gates, not guarantees of representativeness or detector accuracy.

Freeze source catalog, exclusions, selected row IDs, assignments, protocol/config and parser/
PSL hashes before fitting. Independent models use the exact same eligible evaluation rows.
An unavailable external source yields an explicit incomplete robustness track; it must not
appear as passed in a report or be silently replaced by the known-biased v1 source.

## Models, evaluation and release boundary

Reuse character TF-IDF/logistic and lexical histogram boosting, their approved bounded
configuration grids, four-thread fresh-process fits, 8 GiB resource target and separate
calibration. Select recall under the existing 5% validation FPR budget, with the existing
tie policy; add a predeclared 1% validation-budget sensitivity result. Neither threshold
can be selected on calibration or final tests. Keep calibrated probabilities unavailable
when support, score variation or slope checks fail.

Compare the two learned branches and fixed URL rules. Include a training-only format
baseline using HTTPS, www-host, non-root-path and query-presence indicators to expose easy
structural shortcuts; this diagnostic is not eligible for the deployed candidate choice.
The v1 model may be reported as a transfer diagnostic with explicit overlap against its
entire earlier dataset. Any v1/v2 paired performance comparison must use only common test
rows from domains not present in v1's earlier development data. Different test populations
cannot substantiate a claimed improvement from v1's 97.07% headline score.

Report primary and external tracks separately: precision/recall/F1, confusion counts,
actual FPR, average precision, calibration/Brier/ECE, coverage, whole-domain bootstrap
intervals, format/class/source subgroups, cold/warm latency and measured peak RAM. Tiny
subgroups or constant bootstrap outcomes need an explicit uncertainty limitation. Show
conditional low-prevalence precision scenarios without presenting them as deployment rates.
Known staged benign documentation examples remain software/sanity cases, outside final
accuracy evidence and never a basis for whitelisting, thresholds or model search.

Final evaluations reference frozen model/protocol hashes and refuse overwrite. Record failed
fits and acquisitions with underlying errors, parameters, attempted ranges and available
resource measurements. Raw content stays private. Any revision prompted by final-test errors
requires a new independent final set; the old result remains published with its limitations.

The milestone succeeds when adapters, provenance, isolation and evaluation are reproducible
and limitations are honestly reported, including a negative or incomplete robustness result.
No automatic activation of v2 or “safe” verdict is added. Learned live warnings require a
separate release decision supported by external validation and application checks.

## Verification and next handoff

Required checks include: ignored private outputs; byte-range refusal on status 200 or changed
object identity; requested-column isolation from HTML; corrupted cached bytes; malformed
labels/dates; cross-source duplicate/conflicting URLs; holdout/domain overlap; giant groups;
missing classes and formats; unknown dates; positive-only external inputs; immutable outputs;
failure-report preservation; v1 artifact/CLI compatibility; and unchanged default API startup.
No accuracy test uses fabricated examples. Software fixtures are synthetic and identified.

Self-review: scope is one URL data/robustness subsystem; no placeholder source or promised
performance; unavailable external access is explicit; original v1 compatibility and provenance
semantics are protected. Next: written-spec review, then a focused implementation plan with
exact interfaces, regression cases and the preserved inline execution preference. Source
acquisition, dependency installation, product changes and retraining follow that review.
