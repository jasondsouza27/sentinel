# English conversation and directed-abuse workflow

The module compares a target message with its preceding conversation. Its binary
task is English directed abuse; a label does not establish intent, repeated
harassment, phishing, or the identity of a speaker. The app keeps these assessments
separate and saves the exact reviewed input and result with a short-lived receipt.

The real CAD v1.1 study is **unavailable at the protected allocation gate**. The
fixed allocation has 175 positive training cases (minimum 200), five validation
components and eight calibration components (minimum ten each). No real harm
model, final-test score, or learned live warning is delivered from this cohort.
The tests use invented data to verify software; their scores are not findings.

## Environments and private data

Run from the project outside OneDrive. The API and application need only the
Python standard library. CPU research uses Windows CPython 3.11.17 and the existing
ML/data locks: sixteen core packages in `requirements-ml-win-py311.lock.txt`
and seventeen unique pins when `requirements-url-data-win-py311.lock.txt` is
included. Install their exact versions into an
isolated environment; do not replace pins with current versions:

```powershell
python -m venv .venv-harm-cpu
& .\.venv-harm-cpu\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-ml-win-py311.lock.txt -r requirements-url-data-win-py311.lock.txt
& .\.venv-harm-cpu\Scripts\python.exe -m pip check
```

On this computer the existing `.venv-url-v2-check` environment supplies those CPU
dependencies. Set the working directory to the checkout and use its interpreter
by absolute path when running a worktree.
The preserved CPU lock contains version pins rather than wheel hashes; use the
official registry and verify the installed inventory. The separate encoder lock
additionally requires hash-verified wheels and offline `--require-hashes` installation.

`data/context-harm/`, `models/context-harm/`, and `.venv-harm-neural/` are ignored.
Sources, text, author/thread IDs, challenge reviews, predictions and fitted weights
stay private. Public delivery contains aggregates, methods and hashes only.

## Reproduce admission and the failed allocation

```powershell
python -m sentinel.context_harm.cli challenge-init --root data/context-harm
python -m sentinel.context_harm.cli source --root data/context-harm
python -m sentinel.context_harm.cli audit --root data/context-harm
python -m sentinel.context_harm.cli freeze --root data/context-harm
```

Use the locked CPU interpreter for these commands. `source` verifies the author
archive, selected TSV and codebook. It downloads no released models, predictions,
comment destinations or source images. Record a codebook consistency inspection
before any successful freeze. The supplied study's private inspection receipt
binds the archived codebook hash and preserves the reported-abuse limitation.

The audit reserves known authors from all published test-thread rows, including
excluded/context records. It purges whole development threads sharing those
authors, then protected masked exact/near duplicates and reserved challenge
ownership. Original train/dev threads are pooled; this is a different protocol
from the paper's benchmark. Missing authors remain unknown. Invalid source graph
threads are excluded; an unsupported intermediate parent stops reconstruction.

Both primary models use the same context-available cases and at most four ancestor
turns, with no siblings or later replies. Exact duplicates use NFC/casefold and
whitespace normalization after URL/username masking. Meaningful targets also use
the documented 64-bit word-trigram SimHash rule, Hamming distance at most three.
The implementation binds normalization/tokenization and source hashes.

Allocation uses one seed-42 largest-first tie order and 70/15/15 targets. This
allocation fails its gates; the CLI must return unavailable, write no frozen
replacement partitions and start no real fitting. Failure of this greedy
allocation is not proof that every mathematical allocation is impossible. Do not
retry seeds, cut components or relax gates to obtain a favourable result.

## Model stages for a future admitted version

These stages require a frozen ready study. They are implemented and tested with
explicit synthetic fixtures, but cannot run on the current unavailable cohort:

```powershell
python -m sentinel.context_harm.cli train-cpu --root data/context-harm --models models/context-harm
python -m sentinel.context_harm.cli neural-pilot --root data/context-harm --models models/context-harm --neural-python .venv-harm-neural/Scripts/python.exe
python -m sentinel.context_harm.cli train-neural --root data/context-harm --models models/context-harm --neural-python .venv-harm-neural/Scripts/python.exe
python -m sentinel.context_harm.cli pack --root data/context-harm --models models/context-harm
python -m sentinel.context_harm.cli evaluate --root data/context-harm --artifact models/context-harm/artifact --output output/research/context-harm-v1
```

CPU target/context branches use separate sparse TF-IDF spaces and six fixed
logistic configurations per branch. Native workers require Windows Job Object
ownership before requests or ML imports; deadlines, process-tree RSS and bounded
output apply. Scoring sends feature-only stdin payloads without unsaved input
files. Fit failures publish no successful partial candidate.
CPU training, encoder training and the optimizer pilot share one nonblocking
Windows reservation across processes and output directories; a crashed owner
cannot leave a permanent reservation. Source connections, headers and body reads
also run in an owned bounded worker, since a socket inactivity timeout does not
bound an entire request while bytes continue to arrive.

The optional encoder has its own exact 26-wheel lock and generic DistilBERT
revision. Source byte/disk/time bounds and a training-only CUDA optimizer pilot
must pass before full candidates. Both neural branches preserve the whole target
and share the token-compatible subset; targets over 252 WordPiece tokens abstain.
The current production gate failure prevents acquisition/installation/pilot and
full fits. An unavailable pilot is a recorded outcome, not a skipped test.
Every encoder pilot, fit and scoring worker measures its actual interpreter
and base-executable hashes, installed inventory, CUDA version and default-device
properties before loading tokenizers or models. Those measurements must match
the approved probe, and fitted/scored records retain the verified runtime.

Selection uses validation recall under 5% FPR, then precision, lower FPR and
configuration ID. Calibration uses separate component-grouped out-of-fold checks;
unsupported or worsened calibration suppresses numerical probability. It never
changes the raw threshold. Research artifacts verify implementation, locks,
source, cohort, tokenizer/weights and settings before deserialization. Local hash
checks do not authenticate an artifact from an untrusted distributor.

Final access is durably reserved once before scoring. An identical interrupted
operation can resume; completed scoring and post-reservation refits are denied.
Current encoder runtime attestation is bound before the final reservation, so an
interrupted operation cannot silently resume under a different runtime.
The report compares identical cases with component-bootstrap uncertainty and
marks sparse/dominant-component intervals unavailable. A later approved data or
method revision needs a newly reserved held-out version. Verify archived report
hashes for reproduction; never rerun a completed final test.

## Empty challenge and application

```powershell
python -m sentinel.context_harm.cli challenge-prepare --root data/context-harm
python -m sentinel.context_harm.cli challenge-finalize --root data/context-harm
python -m sentinel.context_harm.cli challenge-audit --root data/context-harm
```

The intake starts empty. Collect permissioned, traceable real cases in the six
documented families. Two different humans review separate blinded forms;
disagreements require a third reviewer/adjudication. Uncertain labels are excluded.
Opaque reviewer IDs attest independence locally; the tool cannot verify the
humans' identities. Model predictions and phrase matches cannot supply gold.
Reserve any development-derived challenge ownership before fitting.
This version has reserved an empty intake. Use a new private root for a future
collection/version; do not edit an existing reservation to add cases.

```powershell
python -m sentinel.server --port 8787
node --test tests/web_client.test.mjs tests/extension_popup.test.mjs tests/conversation_editor.test.mjs
python -m unittest discover -s tests -v
```

The turn editor supports linear and reply conversations, target selection and
explicit preceding-context coverage. A missing language declaration is an English
assumption; other declared languages are not assessed by the learned module.
The extension remains explicitly initiated and target-only, with unchanged
permissions. Actual Chrome toolbar/context-menu checks remain separately deferred.

`/api/analyze` issues a receipt alongside result fields. New clients save
`{input,result,assessment_receipt}`; the server verifies the exact snapshot and
does not reanalyse it. Receipts expire after 900 seconds and are invalid after
server restart; recheck before saving. Legacy input-only saves create a new
assessment. Clearing or editing hides stale results and disables saving. Saved
cases support reopening, feedback, export and deletion.

Initial schema-1 artifacts are research-only and cannot activate learned warnings.
The optional adapter reports unavailable while rule observations continue. A
separate methodology/error review and approved release are still required.
