# Reproduce Sentinel's URL ML milestone

**The measured url-v1 candidate is research-only:** all legitimate source URLs are www HTTPS homepages with empty paths. Staged benign documentation URLs are falsely flagged. Read the [final model card](../output/research/url-ml-v1/model-card.md) before interpreting outputs. Broader source/temporal validation and legitimate page/query examples are required.

This is the first trained subsystem of the approved year-long project. It provides a
URL-string classifier, evaluated baselines, a checked local artifact and optional API.
It does not train contextual harm/profile models or establish message-plus-URL benefit.
The [source audit](url-ml-source-audit.md) records attribution, exact hashes and counts.

## Runtime

Use Python 3.11, Windows x64, CPU and the committed resolved lock. The measured runtime
is CPython 3.11.17. No neural/GPU runtime is required. The Python runtime must remain
installed; a virtual environment references it. On this machine uv provisioned it
without changing the registered system Python. From the project directory:

```powershell
$sentinelPython311 = Join-Path $env:APPDATA 'uv\python\cpython-3.11.17-windows-x86_64-none\python.exe'
& $sentinelPython311 -m venv .venv-ml
.venv-ml\Scripts\python.exe -m pip install -r requirements-ml-win-py311.lock.txt
.venv-ml\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/web_client.test.mjs
```

If Python 3.11 is already registered, `py -3.11 -m venv .venv-ml` is equivalent.
The original app remains dependency-free; `python -m sentinel.server` runs Phase 0.
The ML test suite must have no optional-dependency skips in the ML environment.

## Acquisition, audit and split

[PhiUSIIL, Prasad and Chandra (2024), UCI dataset 967](https://archive.ics.uci.edu/dataset/967/phiusiil%2Bphishing%2Burl%2Bdataset)
is CC BY 4.0. Only the original archive and [official suffix list](https://publicsuffix.org/list/)
are fetched, with size/time/HTTPS limits. Submitted sites are never opened. The source
uses 0 phishing, 1 legitimate; Sentinel uses 1 phishing, 0 legitimate. CSV fields other
than URL and label are discarded. Historical labels do not verify current sites.

```powershell
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli fetch --root data/url-ml
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli audit --root data/url-ml --config configs/url-ml-v1.json
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli split --root data/url-ml --config configs/url-ml-v1.json
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli pilot --root data/url-ml --config configs/url-ml-v1.json
```

Preserve the acquired `raw` directory, including its acquisition manifest. Reproduction
requires the exact supplied snapshot hashes; the current online PSL can change. `fetch`
reuses existing bytes only after hash verification. Audit/split/pilot refuse overwrite;
when completed, later commands load and verify those existing outputs. To run a separate
experiment use a new root and artifact version rather than editing frozen files.

Canonicalisation preserves path/query/fragment spelling, normalises scheme/host/IDNA
and default ports, and rejects invalid or over-2,048-character inputs. Private suffixes
are enabled. Unknown suffixes group conservatively by full host; IP addresses group by
normalised address. Duplicates and all conflicting labels are audited. Domain groups
are frozen together into train/validation/calibration/test at 70/10/10/10 with seed 42.
No random-row fallback is permitted.

## Train, freeze and evaluate

```powershell
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli train --root data/url-ml --config configs/url-ml-v1.json --artifact models/url-ml/url-v1 --version url-v1
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli evaluate --root data/url-ml --artifact models/url-ml/url-v1 --out data/url-ml/final-evaluation.json
.venv-ml\Scripts\python.exe -m sentinel.url_ml.cli predict --artifact models/url-ml/url-v1 --url https://example.org/
```

Fits run one at a time in fresh CPU processes with four native threads; peak working
set and elapsed time are recorded per candidate with an 8 GiB target. The pilot uses
at most 2,000 rows from whole training groups. TF-IDF uses float32 sparse, case-sensitive
3-5 character grams and at most 50,000 features; six logistic configurations. Lexical
HGB uses only 16 derived URL features, four depth/rate configurations and no internal
random validation. Vocabulary, preprocessing and fits see only training inputs.

Validation chooses maximum recall subject to FPR <=5%, then precision and config order.
Unique tied scores are handled together, including an all-negative decision. The chosen
fit is never retrained on validation/calibration. Separate calibration fits a sigmoid
on clipped score logits; at least 100 rows/20 per class and a finite positive slope are
required. These guards do not prove reliability. Decisions keep the raw validation
threshold, while probability is omitted if calibration is unavailable.

Final evaluation references the frozen artifact hash and compares the selected fit,
the best validation candidate of each trained branch, and fixed Phase 0 URL warnings
on exactly the same test partition. It reports confusion counts, precision/recall,
positive/macro F1, average precision (PR area), FPR, Brier, 10-bin ECE/reliability and
1,000 seed-42 whole-domain bootstrap 95% percentile intervals. Undefined/unsupported
metrics are null. Prevalence scenarios are conditional calculations, not deployment
estimates. Cold/warm timings include model loading and single-URL inference as labelled.

Local source/row/split files and binary artifacts remain ignored. Published output is
aggregate only. Artifact checksums detect corruption, not a malicious replacement;
load only locally produced trusted joblib directories. Dependencies, schema, labels,
PSL and every file hash are checked before deserialisation. Inference rebinds parsers
to the verified artifact PSL and does not require the source dataset.

## Use and remaining work

[Optional API configuration](url-ml-api.md) keeps learned results separate from existing
fraud rules, harm and profile outputs. The current UI is Phase 0; standalone prediction
and the opt-in API expose this milestone. A not-flagged result never establishes safety.
Probabilities describe the source benchmark distribution, not current live-site confidence.

This URL-only experiment excludes webpage/population features and does not reproduce
PhiUSIIL's full paper experiment. A source-held-out domain test is not temporal or
external-source validation. Main paired-message research still needs reviewed genuine
message-link cases and legitimate comparisons. Contextual harm, cautious profile ML,
team investigations, dashboard redesign and the usability pilot follow in later milestones.
