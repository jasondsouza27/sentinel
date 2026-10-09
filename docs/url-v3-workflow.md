# Reproduce the frozen Sentinel URL-v3 study

URL-v3 is an explicit research workflow for the URL module of Sentinel's year-long
project. It reuses the preserved PhreshPhish v2 projection and adds an official,
checksum-pinned Mendeley URL-label source. Acquisition, audit, freezing, modelling,
evaluation and artifact prediction are separate commands. Ordinary application
startup runs none of them, and learned live warnings remain disabled.

Synthetic fixtures test software boundaries. Their model scores are never research
findings. See the [approved specification](superpowers/specs/2026-10-09-sentinel-url-v3-design.md)
and [implementation plan](superpowers/plans/2026-10-09-sentinel-url-v3.md) for the
predeclared study, and the delivery record for its actual outcome.

## Runtime and inputs

Use Windows x64 CPython 3.11 and the union of the two unchanged exact dependency
locks. The existing verification environment already contains that union:

```powershell
$sentinelResearchPython = '.venv-url-v2-check\Scripts\python.exe'
& $sentinelResearchPython -m sentinel.url_v3.cli --help
```

For a clean environment, create a new CPython-3.11 virtual environment and install
`requirements-ml-win-py311.lock.txt` plus
`requirements-url-data-win-py311.lock.txt` with binary wheels. Validate the installed
versions against both locks before research. Help remains available under
`python -S`; research stages need their installed dependencies.

The common defaults are `configs/url-ml-v3.json` and
`resources/url-v2-suffix.dat`. Production config admission requires the exact
predeclared values and types. Reduced source pins, support gates or grids belong
only in explicitly marked test fixtures. The private-inclusive offline suffix
snapshot is SHA-256
`e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66`.
The stored config/snapshot become immutable inputs. Do not update them during a run.

Supply the preserved, complete v2 root as read-only input. Its failed training gate
does not invalidate its historical audit/protocol. V3 verifies its catalog,
projection, audit, protocol, original owners and complete reserved domains; it
never calls the old training-readiness guard. The new root must be separate from
that input, including its diagnostics and any artifact/public output.

## Bind, acquire, audit and freeze

Run commands from the Sentinel repository. Set the v2 variable to the actual
preserved root; if implementing in a worktree, use the primary checkout's root.
The other paths must be fresh and exclusive:

```powershell
$sentinelV2InputRoot = 'data/url-ml-v2'
$sentinelV3StudyRoot = 'data/url-ml-v3'
$sentinelV3Candidate = 'models/url-ml/url-v3'
$sentinelV3PublicOutput = 'output/research/url-ml-v3'

& $sentinelResearchPython -m sentinel.url_v3.cli bind-v2 --root $sentinelV3StudyRoot --v2-root $sentinelV2InputRoot
& $sentinelResearchPython -m sentinel.url_v3.cli acquire-mendeley --root $sentinelV3StudyRoot
& $sentinelResearchPython -m sentinel.url_v3.cli audit --root $sentinelV3StudyRoot
& $sentinelResearchPython -m sentinel.url_v3.cli freeze --root $sentinelV3StudyRoot
```

Check every exit code before starting the next stage. Exit 2 preserves a private
sanitized diagnostic and prints only aggregate status; it never starts the next
stage. Binding/freeze verification replays the historical semantics and can take
several minutes on the full corpus. Do not interrupt them merely because progress
has no new row count. No URL from the submitted corpus is visited.

The official source is [Web page phishing detection V3](https://data.mendeley.com/datasets/c2gw7fy2j4/3),
Abdelhakim Hannousse and Salima Yahiouche, DOI 10.17632/c2gw7fy2j4.3,
CC BY 4.0. Only `dataset_B_05_2020.csv`, file ID
`575316f4-ee1d-453e-a04f-7b950915b61b`, 3,661,166 bytes, SHA-256
`21093e2902e5441c86a6daf95e86e7c332046e477fdf109a579d7bd81e586d6c`
is accepted. The page and inventory must confirm identity and attribution.
The 87 feature columns are ignored; URL/status and provenance are projected.
Strict UTF-8 CSV has exact unique required headers, consistent record width, 16 KiB
fields and at most 20,000 records. Missing/unknown cells retain distinct audit
exclusions. Dataset-A DOM/pickle files and publisher scripts are unused.

Acquisition permits HTTPS/443 only on the pinned Mendeley and observed public
S3 hosts. Requests use identity encoding and 30-second timeouts, three attempts
per resource, 2 MiB metadata/page, 4 MiB CSV and a durable 16 MiB total HTTP-body
budget, including rejected responses and retries. Intermediate redirects are
closed unread. Actual received bytes and conservative crash reservations are
reported separately. These are body measurements, not header overhead or a
verified historical PhreshPhish transfer total. Signed redirect values remain
private/redacted.

An interrupted acquisition can be retried with the identical command. It retains
spent bytes and attempts and verifies complete cached receipts. An unregistered
or partial file is never admitted; immutable completed source outputs are verified
on reuse. Audit, binding and protocol outputs refuse overwrite.

The joint audit retains original Phresh observations, including exclusions needed
to find recognized-label conflicts. All contradictory canonical URLs are excluded.
Originally reserved domains remain protected even if a conflict removes their
original case.

## Inspect support before fitting

Freeze success (exit 0) means the protocol was saved, not that training is authorized.
Read `training_ready` and all reported gates. Primary is the surviving subset of
original Phresh test-owned cases, with no newly added cases. Fixed half-by-component
hash reservation creates the Mendeley supplemental track before fitting; only
Mendeley owns its scored cases. It is group-held-out from a source also used in
development, not independent-source validation.

All eligible Mendeley development components are included before filling the
200,000-row ceiling with whole Phresh-only components. An oversized mandatory pool
stops freezing. Seed 42 and the 80/10/10 component allocation are fixed; there is
no seed search or truncation. Achieved fractions are reported.

Training requires 1,000 rows/100 domain groups per class; validation, calibration
and both final tracks require 100/30. Both development sources require 100/30 per
class. Legitimate-format gates require 100 non-root paths, 100 non-www hosts and
30 nonempty-query URLs in training, pooled development and each final track.
Counts of connected components are reported separately. Any failed gate blocks
pilot and training before a learner is invoked.

To freeze and publish an aggregate support report in the same command, add
`--output $sentinelV3PublicOutput` to `freeze`. This reserves that immutable output
directory. For a study that passes and will be evaluated later, omit that option;
evaluation must have a fresh output. Failed pilot/train commands also accept an
optional `--output` for an unavailable status/card. Such a gate failure has
`metrics: null` and `models_fitted: false`. Failures after fitting may have
`models_fitted: null` when completion cannot be established, rather than inventing
a clean outcome. The private diagnostic is authoritative for partial work.

A failed protocol remains a valid negative research outcome. Preserve it, publish
measured support with unavailable metrics, and stop modelling for that study.
Changing source/reservations/caps/seeds requires a new version and independently
reserved final data, not a renamed artifact or an undocumented rescue.

## Conditional pilot, train and evaluate

Execute these only when every gate passes:

```powershell
& $sentinelResearchPython -m sentinel.url_v3.cli pilot --root $sentinelV3StudyRoot
& $sentinelResearchPython -m sentinel.url_v3.cli train --root $sentinelV3StudyRoot --artifact $sentinelV3Candidate --version url-v3
& $sentinelResearchPython -m sentinel.url_v3.cli evaluate --root $sentinelV3StudyRoot --artifact $sentinelV3Candidate --output $sentinelV3PublicOutput
```

The pilot uses at most 2,000 whole-component training rows. Six character TF-IDF/
logistic configurations and four lexical HGB configurations run sequentially in
fresh workers, four native threads, under an 8 GiB process-tree fitting ceiling.
The monitor samples worker plus descendants, enforcing the conservative sum of
individual lifetime peaks and reporting the observed simultaneous RSS as well.
A failed or over-budget worker's model is not accepted; descendants are stopped.

Every candidate and learner entry re-verifies physical sources/config/parser/
protocol and exact frozen in-memory rows. Selection uses validation recall under
5% FPR, then precision/configuration order; the 1% sensitivity threshold is also
frozen on validation. Calibration uses only calibration data and may remain
unavailable. A four-feature format diagnostic is fitted once and excluded from
deployment/calibration. Final scoring fits nothing and selects no threshold.

Artifacts are trusted, locally generated joblib only. Hashes detect corruption;
they do not authenticate downloaded pickle. All metadata/provenance/file checks
precede deserialization. Exact v3 schema pairs with the six shared files and
three protocol/diagnostic sidecars. Generic inference loads only the main pipeline,
verifies but does not deserialize the diagnostic, and needs no Arrow.

The evaluation records a durable final-access receipt before any final score.
Any access, including failed scoring, permanently blocks fitting against that
protocol. Only the identical artifact/protocol/fixed settings can resume scoring.
A completed sealed report is verified and replayed without new scores; this also
recovers a receipt interrupted after report sealing. Missing/corrupt completed
evidence is refused. Public publication is atomic and never overwrites output.

Primary and supplemental results remain separate. Comparisons include both learned
branches, fixed rules and the format-only control at frozen operating points.
They report confusion/precision/recall/F1/macro-F1/AP/FPR, coverage, calibration
where available, class/source/format support, 1,000 seed-42 whole-component
bootstrap intervals, small/constant support warnings, conditional prevalence,
cold/100-warm latency and measured fitting resources. Legitimate-query subgroups
report false positives, their denominator and component uncertainty; phishing
recall/F1 is not inferred for that single class.

Historical annotations do not establish live safety. There are no authenticated
row dates, so temporal results are unavailable. Unknown campaigns and sampling
bias remain limitations; v1 scores on different populations are not improvement
evidence. V2 has no fitted baseline. A verified v1 transfer experiment is deferred.

## Explicit prediction and regression checks

Prediction requires only an artifact, never a study root:

```powershell
& $sentinelResearchPython -m sentinel.url_v3.cli predict --artifact $sentinelV3Candidate --url 'https://example.org/'
& $sentinelResearchPython -m unittest discover -s tests -v
node --test tests/web_client.test.mjs
```

Prediction loads a verified candidate without visiting the destination. Missing
artifacts exit nonzero. It never activates normal application warnings.

Private layout: `config.json`, `binding/`, `sources/` (including acquisition
journal), `audited/`, `protocol/`, `runs/`, `stage-lock/`, `final-access/`,
`failed-runs/`. Raw observations, URL/case IDs, receipt internals and binaries
stay ignored. Public JSON contains only measured aggregates and digests;
documentation/cards may include bibliographic links. Cases and the empty
paired-message intake are never research inputs. Preserve and compare their
hashes, both locks and the original v1/v2 asset hashes before delivery.

Run the complete union-environment Python suite with zero dependency skips and
all 12 Node checks. The separate default-server `-S` test proves the unchanged
three-module dependency-free API. Browser release checks, contemporary validation,
paired message-link research and any application activation remain separately
scoped milestones.
