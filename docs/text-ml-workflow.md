# Learned scam-text model (text-ml-v1, v2): reproduction guide

**v2 is the served model.** It fixes v1's false alarms on genuine Indian transactional messages; see the [v2 model card](../output/research/text-ml-v2/model-card.md).

Sentinel's first learned model that runs live. It classifies a message as **ham**, **spam** or **smishing** (SMS phishing). Its probability is calibrated, and it explains each flagged message at the word level. The [model card](../output/research/text-ml-v1/model-card.md) has the results and limits.

## Pipeline

| Stage | Module | Output |
|---|---|---|
| Verified acquisition and audit | `sentinel/text_ml/source.py` | `data/text-ml/dataset.jsonl`, `audit.json` |
| Template-grouped, stratified splits (70/15/15) | `sentinel/text_ml/splits.py` | `data/text-ml/splits.json` |
| Fine-tuning, temperature calibration, threshold, single test evaluation, robustness study, ONNX export | `sentinel/text_ml/training.py` | `models/text-ml/v1/`, `output/research/text-ml-v1/evaluation.json` |
| Checked loading, inference, leave-one-word-out explanations | `sentinel/text_ml/service.py` | used by `/api/analyze` and `/api/scan` |

Design rules, following the project's existing research protocol:

- **Pinned sources.** The source archives are pinned by SHA-256, and the pipeline refuses any other bytes.
- **Duplicates.** Exact duplicates collapse to one row. Duplicates whose copies carry different labels are excluded, not guessed.
- **Templates stay together.** Messages that share a template (the same text with numbers and links masked) stay in one split, so resent spam can't leak from training into the test set.
- **Choices are made on calibration data.** The best epoch, the temperature and the warning threshold are all chosen on the calibration split. The threshold is set so that at most 1% of ham is flagged there.
- **The test split is scored once,** after export, through the same ONNX runtime the app uses. That run also records how closely the exported model matches the PyTorch model.
- **Fixed failure states.** A missing runtime or artifact, or a checksum mismatch, makes the model report itself unavailable. Sentinel then keeps working with rules only.

## Reproduce

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 -m venv .venv-text-ml
.venv-text-ml/bin/python -m pip install -r requirements-text-ml.txt
mkdir -p data/text-ml/raw
curl -L -o data/text-ml/raw/mendeley-smishing.zip "https://data.mendeley.com/public-files/datasets/f45bkkt8pr/files/edb361de-918d-469f-9106-e84823830665/file_downloaded"
curl -L -o data/text-ml/raw/uci-sms.zip "https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip"
.venv-text-ml/bin/python -m sentinel.text_ml prepare
.venv-text-ml/bin/python -m sentinel.text_ml train
.venv-text-ml/bin/python -m sentinel.text_ml predict "Your parcel is held. Pay the 1.99 fee at http://example.test/track"
./start-sentinel.sh
```

### v2 (served)

```bash
curl -L -o data/text-ml/raw/india14.csv "https://huggingface.co/datasets/anmolshrivastav/scam_ham_india_14_languages/resolve/34e2c413aefd2e8f2a6e93177a155f29733290a5/scam_ham_india_14_languages.csv"
.venv-text-ml/bin/python -m sentinel.text_ml prepare-v2
.venv-text-ml/bin/python -m sentinel.text_ml train --version v2
.venv-text-ml/bin/python -m sentinel.text_ml select-v2
```

`select-v2` compares the transformer, the TF-IDF model and their average on calibration data only, writes the winner into `models/text-ml/v2/manifest.json`, and only then scores test and the [challenge set](../sentinel/text_ml/challenge_set.jsonl).

To check either model against your own real messages, kept locally (a CSV with columns `text,label`, label `ham` or `scam`):

```bash
.venv-text-ml/bin/python -m sentinel.text_ml evaluate-private my-messages.csv
```

It prints counts and the CSV row numbers of mistakes, never the text.

`start-sentinel.sh` serves v2 (or v1 if v2 is missing) and turns the model on automatically when `.venv-text-ml` and `models/text-ml/v1/manifest.json` exist. Set `SENTINEL_RULES_ONLY=1` to run with rules only. `/api/health` reports `text_model.state`.

## Where it shows up

- **Web app and extension popup:** a "Learned scam-text model" card with the calibrated probability, the threshold, and the checked message with its most influential words highlighted.
- **Auto-scan:** a flagged message gets at least a review marker. It gets a high marker when the model's probability is at least 90% or a rule also fires. The marker panel names the key words. At most 5 items per batch are explained, to keep scanning fast.

## Verification, 2026-11-05
- **Tests.** `tests/test_text_ml.py` has 12 tests that use a fake model, so they run without the ML packages. `tests/test_text_ml_artifact.py` has 4 tests that run against the real artifact and are skipped when it's absent. The app-side Python suite passes with 87 tests, and the Node suite with 68.
- **Chrome.** Chrome 156 on macOS, with a throwaway profile driven over the DevTools protocol and the server started by `start-sentinel.sh` with the model on.
  - The auto-scan demo passed all steps. The model raised "student mail will close… one-time password" to high.
  - The web app shows the model card with highlighted words ([screenshot](images/text-ml-webapp.png)).
  - The marker panel shows the model's evidence ([screenshot](images/text-ml-autoscan.png)).
- **Startup note.** Loading the model takes a few seconds. A page opened before the server is ready gets its markers on the scanner's next retry, up to 15 seconds later.
