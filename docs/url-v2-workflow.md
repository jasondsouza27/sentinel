# Reproduce Sentinel URL v2 research

The v2 code adds pinned metadata acquisition, a complete observation audit, frozen
connected components, two CPU model branches, a format-only control, and separate
source/temporal robustness reporting. Learned warnings remain disabled in the normal app.
Implementation checks use invented fixtures; their scores are never project findings.
Actual acquisition and modelling status is recorded in the delivery report after the
real-data experiment. Official ISCX access is still pending.

## Runtimes and offline snapshot

Use Windows x64 CPython 3.11. The separate data lock does not change the existing ML
lock. No GPU or paid service is required. Use a task-specific variable:

```powershell
$sentinelPython311 = Join-Path $env:APPDATA 'uv\python\cpython-3.11.17-windows-x86_64-none\python.exe'
& $sentinelPython311 -m venv .venv-url-data
.venv-url-data\Scripts\python.exe -m pip download --only-binary=:all: -r requirements-url-data-win-py311.lock.txt --dest data/url-ml-v2/wheels
$sentinelArrowHash = (Get-FileHash -Algorithm SHA256 -LiteralPath 'data/url-ml-v2/wheels/pyarrow-25.0.1-cp311-cp311-win_amd64.whl').Hash.ToLowerInvariant()
if ($sentinelArrowHash -ne '62cd0d785b8aa6675ee355f9fc02252a340f4441257c42674937826fd7594325') { throw 'Arrow wheel hash mismatch' }
.venv-url-data\Scripts\python.exe -m pip install --no-index --find-links data/url-ml-v2/wheels -r requirements-url-data-win-py311.lock.txt
& $sentinelPython311 -m venv .venv-ml
.venv-ml\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-ml-win-py311.lock.txt
```

PyArrow 25.0.1 CPython-3.11 Windows wheel identity was verified against official PyPI
metadata before installation. The data environment has ten exact package pins, with
shared packages constrained to the unchanged ML lock. The [bundled public suffix
snapshot](../resources/README.md) is unmodified MPL-2.0 public metadata, SHA-256
`e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66`.
It enables offline reproduction without publishing labelled research URLs. Do not update
it during a run. Audit accepts an explicitly supplied byte-identical copy only.

## Acquire metadata, audit, and freeze

[PhreshPhish](https://huggingface.co/datasets/phreshphish/phreshphish), by the PhreshPhish
[paper authors](https://arxiv.org/abs/2507.10854), is CC BY 4.0 and intended for
anti-phishing research. The revision is
`eabec4b7a66324b79cc8a0ad856d1731dc26fe1a`; source labels `benign` and `phish` map to
0 and 1 respectively. These are historical annotations, not verification of live sites.
Only `url`, `label`, `date`, and opaque `sha256` metadata are decoded. No row URL, HTML,
language column, DNS query, or renderer is requested.

```powershell
.venv-url-data\Scripts\python.exe -m sentinel.url_v2.cli catalog --root data/url-ml-v2
.venv-url-data\Scripts\python.exe -m sentinel.url_v2.cli project-pilot --root data/url-ml-v2
.venv-url-data\Scripts\python.exe -m sentinel.url_v2.cli project --root data/url-ml-v2
.venv-url-data\Scripts\python.exe -m sentinel.url_v2.cli audit --root data/url-ml-v2 --psl resources/url-v2-suffix.dat
.venv-url-data\Scripts\python.exe -m sentinel.url_v2.cli freeze --root data/url-ml-v2
```

Review the pilot before full projection. The pilot is the first sorted train/test shard,
labelled a transport/schema pilot, never the complete source. Bounds are 30 seconds per
request, at most three retries, 2 MiB footer, 32 MiB selected range, 2 GiB cumulative
received payload including metadata and retries, and 4,096 rows per single-thread batch.
HTTPS endpoints are restricted to the audited Hugging Face and US CDN hosts. A metadata-only
footer envelope prevents Arrow's usual large footer window from touching HTML. Every
chunk is audited before a seekable view permits decoding. Strong object identity,
Content-Range, body size and cache SHA-256 must match. Partial-file acquisition always
states `full_file_checksum_verified: false`; an expected full hash is not a computed one.

Interrupted full projection resumes explicitly:

```powershell
.venv-url-data\Scripts\python.exe -m sentinel.url_v2.cli project --root data/url-ml-v2 --resume
```

Resume verifies the same catalog/config/object/cache and retains every spent byte.
Pilot/full purposes have separate journals. No parallel shard access or full-body fallback
is allowed. A cap, unsupported schema or unapproved host stops the run with diagnostics.
Amend the declared protocol/config before another acquisition/model run; do not silently
import the first shards or relax grouping. Completed outputs refuse overwrite.

The indexed audit preserves every observation and all nonconflicting duplicate references.
Canonical case IDs hash normalized URL UTF-8 bytes. All observations of contradictory
labels are excluded; missing/unsupported/oversized URLs, invalid labels and malformed
dates have separate reasons. Schemes and dates are never guessed. Valid dates remain
chronology-unknown until their collection meaning and timezone are authenticated with
source evidence. Authenticated date-only inputs cover the whole day.

Published test ownership wins over development, followed by the external source.
Domain/IP, equivalent URL and same-source opaque-ID links form indivisible components.
Development is capped at 200,000 whole-component rows, then allocated 80/10/10 with seed 42.
Training requires 1,000 rows/100 domain groups per class; validation, calibration and
final tracks require 100 rows/30 domain groups per class. Development and primary benign
coverage each require 100 non-root paths, 100 non-www hosts and 30 query-bearing URLs.
Connected-component support is reported separately; few components weaken uncertainty
estimates even when domain-count gates pass. Failure blocks training rather than cutting
large components. Temporal validation requires every used development interval to end
strictly before every primary interval starts; otherwise the temporal claim is unavailable.

## Optional official local ISCX admission

[ISCX-URL2016](https://www.unb.ca/cic/datasets/url-2016.html) access currently requires an
official process that displayed a server error during the source audit. No form or mirror
was used. After official acquisition, a researcher must provide an audited mapping with
original archive/member identities, category evidence and exact member hashes. No filename
inference or external verification claim is made by Sentinel. Minimal line-format shape:

```json
{
  "schema": "iscx-local-mapping-v1",
  "official_url": "https://www.unb.ca/cic/datasets/url-2016.html",
  "acquisition_basis": "Describe the actual official acquisition and review",
  "acquired_at": "Use the actual acquisition date in YYYY-MM-DD",
  "original_archive": "Use the actual original archive identity",
  "members": [{
    "local_path": "Absolute or mapping-relative verified local file",
    "sha256": "The actual 64-character lowercase member SHA-256",
    "original_member": "The original safe relative member path",
    "category": "benign",
    "evidence_ref": "Private category-mapping evidence",
    "format": {"kind": "lines", "encoding": "utf-8"}
  }]
}
```

For CSV use `kind: csv`, explicit `encoding`, `header: true` and `url_column: URL`
(or `header: false` and an integer column index). This is a schema example, not an
admissible invented source mapping. Only benign/phishing observations are admitted;
spam/malware/defacement members are verified and counted as excluded. Acquisition dates
never become row dates. Cite UNB/CIC and its original dataset papers under the
[dataset policy](https://www.unb.ca/cic/datasets/).

```powershell
.venv-url-data\Scripts\python.exe -m sentinel.url_v2.cli admit-iscx --root data/url-ml-v2 --mapping path/to/reviewed-mapping.json
```

Admission must precede audit/freeze for that run. Later access needs a new root/version;
changing source inputs invalidates frozen provenance. A positive-only or absent external
source remains an unavailable binary holdout. It cannot be replaced by v1 or synthetic data.

## CPU pilot, immutable artifact, and frozen evaluation

Hand the verified root to the unchanged ML environment; it does not need PyArrow.

```powershell
.venv-ml\Scripts\python.exe -m sentinel.url_v2.cli pilot --root data/url-ml-v2
.venv-ml\Scripts\python.exe -m sentinel.url_v2.cli train --root data/url-ml-v2 --artifact models/url-ml/url-v2 --version url-v2
.venv-ml\Scripts\python.exe -m sentinel.url_v2.cli evaluate --root data/url-ml-v2 --artifact models/url-ml/url-v2 --out output/research/url-ml-v2 --v1-root data/url-ml --v1-artifact models/url-ml/url-v1
.venv-ml\Scripts\python.exe -m sentinel.url_v2.cli predict --artifact models/url-ml/url-v2 --url https://example.org/
```

Omit both v1 options together if the verified old artifact/data are unavailable.
The 2,000-row CPU pilot retains whole components. Six character/logistic and four lexical
HGB fits run sequentially in fresh processes with four native threads and an 8 GiB limit.
Selection uses validation recall under 5% FPR, then precision/configuration order. Frozen
branch candidates additionally get 1% validation thresholds without another search.
Separate calibration keeps the existing support/variation/positive-slope guards.
A once-fit four-format logistic control is excluded from deployment and calibration.

V2 has an explicit provenance schema and catalog digest; v1 `source_sha256` meanings and
exact artifact file sets remain unchanged. The v2 artifact adds checked protocol and
format-diagnostic sidecars. Every file/schema/runtime/provenance check precedes any
model deserialization. Load only locally generated trusted joblib; hashes are not
pickle authentication. Generic inference verifies diagnostics without loading their model
and never imports Arrow. All current source/assignment files are checked again before
final prediction. No evaluation chooses thresholds or fits anything.

Primary and external results stay separate. Reports contain confusion counts, precision,
recall/F1/average precision/FPR, selected-model calibration/Brier/ECE, whole-component
1,000-replicate seed-42 intervals, small/constant-outcome warnings, source/class/format
subgroups, conditional prevalence scenarios, cold/100-warm inference and fit peak RAM.
V1 transfer reports overlaps against all earlier data. Paired v1/v2 comparisons use exactly
the same v2 test rows and exclude entire components containing any v1 development domain,
including domains in pruned v2 observations. Different-population headline scores cannot
measure improvement. Source separation alone does not prove independence.

Private layout is `sources/`, `cache/`, `audited/`, `protocol/`, `runs/`, `failed-runs/`.
Private scores retain row IDs; published JSON/cards contain aggregates only. Commands print
sanitized status/hashes; failed stages return 2 and retain exclusive sanitized diagnostics,
with an inline fallback if persistence fails. Saved cases and the paired-message intake
are never inputs. Do not tune on final results: a revision needs a new independent final set.
There is no automatic activation or confirmed-safe verdict.

## Complete verification environment

```powershell
& $sentinelPython311 -m venv .venv-url-v2-check
.venv-url-v2-check\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-ml-win-py311.lock.txt -r requirements-url-data-win-py311.lock.txt
.venv-url-v2-check\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/web_client.test.mjs
```

The union environment must run all ML/Arrow checks without optional-dependency skips.
The default `-S` API compatibility check separately proves the original dependency-free
three-module contract and explicit case-saving ownership. Fixture metrics are software
checks only. Read the delivery record for the real corpus counts, measured gates and
independent review before interpreting any claimed project result.
