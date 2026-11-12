# Model card: text-ml-v1 (learned scam-text model)

> **Superseded by [text-ml-v2](../text-ml-v2/model-card.md).** v1 rates genuine Indian transactional messages (bank alerts, OTPs, salary, delivery, college notices) as scams at 91–99%. That was found through the community-network simulation, and v2 fixes it.

**Status: experimental, live in the local app.** This is Sentinel's first learned model shown to users. It sits next to the rule observations and never replaces them, and every result states its limits.

## What it does
It classifies one English message as **ham** (legitimate), **spam** (unwanted promotion) or **smishing** (SMS phishing). Its scam score is P(spam) + P(smishing), calibrated by temperature scaling, and it warns when that score is at least **0.90**. It explains flagged messages by removing one word at a time and measuring how much the scam log-odds fall.

| Item | Value |
|---|---|
| Base model | `distilbert-base-uncased` (66M parameters), fine-tuned for 3 classes |
| Training | 4 epochs, AdamW, learning rate 3e-5, batch size 32, square-root inverse-frequency class weights, seed 13, Apple M4 (MPS), 305 seconds |
| Best epoch (calibration macro-F1) | 4 |
| Temperature | 1.2545 |
| Runtime | ONNX Runtime on CPU, 9.2 ms per message when batched. ONNX and PyTorch logits differ by at most 3e-6. |
| Artifact | `models/text-ml/v1/` (`model.onnx`, `tokenizer.json`, `manifest.json`, with SHA-256 checksums checked at load) |

## Data
Source: Mishra & Soni (2022), *SMS Phishing Dataset for Machine Learning and Pattern Recognition*, Mendeley Data, doi:10.17632/f45bkkt8pr.1, CC BY 4.0. It was cross-checked against the UCI SMS Spam Collection (Almeida & Hidalgo, 2011, CC BY 4.0). Full counts are in the [data audit](data-audit.json).

- **Rows.** 5,971 rows were read and 5,790 kept: 4,829 ham, 434 spam and 527 smishing.
- **Exclusions.** 111 exact duplicates were removed. 70 rows were excluded because duplicate copies carry different labels in the source (spam in one copy, smishing in another). This label noise is itself a finding.
- **UCI cross-check.** 4,908 messages also appear in UCI. Ham and spam never conflict. 251 messages that UCI calls spam are labelled smishing in Mendeley.
- **UCI is not used for training.** It doesn't separate spam from smishing, and adding its rows to some classes only would teach source style instead of content.
- **Splits.** Rows are split 70/15/15 by template group: the same text with numbers and links masked. That gives 5,666 groups and no group in two splits, with matching class shares in each split. The test split has 725 ham, 66 spam and 79 smishing.

## Results (test split, 870 messages, scored after all choices were made)

| Model | Accuracy | Macro-F1 | Ham F1 | Spam F1 | Smishing F1 | Calibration error (ECE) |
|---|---|---|---|---|---|---|
| TF-IDF word + character n-grams, logistic regression (baseline) | 0.962 | 0.874 | 0.990 | 0.767 | 0.867 | 0.018 |
| **DistilBERT, calibrated (text-ml-v1)** | **0.972** | **0.896** | **0.997** | **0.824** | **0.868** | **0.011** |

Calibration lowered the expected calibration error from 0.0195 to 0.0111 without changing which class wins.

**Scam vs ham** (spam and smishing together) at the warning threshold:

| Operating point | Threshold | Precision | Recall | Ham false-positive rate |
|---|---|---|---|---|
| Baseline (1% FPR rule) | 0.289 | 0.947 | 0.986 | 1.10% |
| text-ml-v1, first rule | 0.152 | 0.953 | 0.979 | 0.97% |
| **text-ml-v1, current rule** | **0.900** | **1.000** | **0.959** | **0.00%** (0 of 725) |

Bootstrap 95% confidence intervals (2,000 resamples, at the first threshold): macro-F1 0.855–0.936, scam recall 0.953–1.000, ham FPR 0.4%–1.8%. The test set is small, so differences of about a point between models are within noise.

**Confusion matrix** (rows are the true class, columns the predicted class: ham, spam, smishing): ham `724 1 0`, spam `3 56 7`, smishing `0 13 66`. Most errors are spam and smishing mistaken for each other, which matches the label noise seen in the source.

### Threshold revision
The first threshold rule took the *lowest* threshold that kept calibration ham false positives at or under 1%, which gave 0.152. While testing the live demo, harmless institutional notices scored 0.18 and 0.74, so the rule was flagging extra ham for no gain in recall. On the calibration split, recall was flat from 0.152 to 0.9 while false positives fell from 1.1% to 0.41%. The rule was changed to "best calibration recall within the target, highest threshold among ties, capped at 0.9", and re-applied using calibration data only. The test split was then scored a second time. Both results are reported above, and the change is recorded in `manifest.json` under `revisions`.

### Robustness (scam test messages, 30% of words perturbed, first threshold)
| Perturbation | text-ml-v1 scam recall | Baseline scam recall |
|---|---|---|
| None | 0.979 | 0.986 |
| Leetspeak (`fr33 pr1z3`) | 0.993 | 0.959 |
| Cyrillic homoglyphs | 0.979 | 0.966 |
| Dotted spacing (`f.r.e.e`) | 0.959 | 0.959 |

There are only 145 scam messages, so the transformer's apparent gain under leetspeak is noise. The finding is that neither model degrades sharply under these simple disguises. Stronger attacks, such as paraphrasing and new scam styles, weren't tested.

## Limits
- **Domain.** It was trained on English SMS from roughly 2011–2022. Email, social media posts, other languages and newer scam styles are out of distribution. The demo showed formal institutional notices scoring 0.18 and 0.74, below the threshold but not near zero.
- **Spam vs smishing** is the weakest distinction, because of label noise in the source.
- **The probability is calibrated only on this corpus.** It isn't a real-world risk estimate.
- **Explanations.** Leave-one-word-out explanations show which words the model relies on. They aren't proof of intent, and context such as a sender or a real link destination isn't modelled.
- **No identity checks.** The model doesn't verify senders, visit links or check reputation. Those checks belong to the rules and the URL work.
- **No learning from feedback.** User feedback in the app never retrains the model, as the project design requires.

## Reproduce
See [docs/text-ml-workflow.md](../../../docs/text-ml-workflow.md).
