# Running the tests

Three Python environments plus Node cover different parts of Sentinel. Run every command from the project folder.

| Suite | Command | Expected on macOS |
|---|---|---|
| App, models, bot detection, community network, harm rules | `.venv-text-ml/bin/python -m unittest tests.test_harm_rules tests.test_analysis tests.test_scan tests.test_server tests.test_network tests.test_text_ml tests.test_text_ml_artifact tests.test_bot_detection tests.test_bot_ml` | all pass |
| Web app and extension (JavaScript) | `node --test tests/*.test.mjs` | all pass |
| Full suite, pinned research environment | `.venv-ml/bin/python -m unittest discover -s tests -p 'test_*.py'` | everything passes except 43 `test_context_harm_*` tests (see below) |

## Setting up the research environment (`.venv-ml`)
The research artifacts are deliberately locked to **CPython 3.11** and exact package versions.

```bash
/opt/homebrew/bin/python3.11 -m venv .venv-ml
```

```bash
.venv-ml/bin/python -m pip install -r requirements-ml.in "threadpoolctl==3.7.0"
```

`threadpoolctl` has to match `requirements-ml-win-py311.lock.txt`, otherwise the harm CPU code refuses to run (`cpu_dependency_lock_mismatch`). Under the system Python (3.14) the research tests fail with `artifact_python_mismatch` or missing `tldextract`/`psutil`. That's expected.

## Known platform limits
The 43 remaining `test_context_harm_*` failures are **Windows-only by design**:
- The research harm pipeline runs its workers inside **Windows job objects** (`worker_ownership_unavailable`) and uses a Windows training mutex (`harm_training_admission_unavailable`).
- The neural branch needs the separate **Windows CUDA** runtime (`neural_unavailable`).

These tests pass in the project's locked Windows environment (`requirements-*-win-py311.lock.txt`). Live harmful-language detection in the app doesn't depend on them; it uses `sentinel/harm_rules.py`.

## Cross-platform fixes (2026-11-05)
The URL research training worker previously failed on macOS and Linux for two reasons:
- It read peak memory from a field psutil provides only on Windows. It now falls back to `getrusage`.
- Its cleanup let psutil reap the worker process, so `multiprocessing` could no longer close it. The worker is now stopped through `multiprocessing`.

All 159 URL research tests pass on macOS.
