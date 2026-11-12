# Model card: text-ml-v2 (scam-text model, false-alarm fix)

**Status: experimental. This is the model the launcher now serves** (`start-sentinel.sh` falls back to v1 if v2 is absent). v2 fixes v1's main failure: v1 rated genuine Indian transactional messages (bank alerts, OTPs, salary, delivery, college notices) as scams at 91–99%.

## Why v1 failed
In v1's only training source, the legitimate messages are almost all personal chat, while nearly every business-style message is spam. v1 learned that order numbers, account codes and "Your…" mean spam. Its own test set couldn't reveal this because it has the same bias. The [community-network simulation](../network-v1/results.md) exposed it: 98% of genuine bulk messages were flagged.

## What changed
1. **Data.** Added the English and Hinglish rows of *Indian Multilingual Scam & Ham SMS* (anmolshrivastav, Hugging Face, revision 34e2c41, MIT, **tagged synthetic**). That's 1,000 ham (OTP, bank alerts, recharge, billing and personal chat) and 1,000 scams (KYC, digital arrest, task jobs, impersonation). Scams map to *smishing*. The source is pinned by SHA-256, and the details are in [data-audit.json](data-audit.json).
2. **Splits.** Every v1 row keeps its v1 split, so the **v1 test set is unchanged** and the comparison is fair. The new rows are split 70/15/15 by template group (1,427 groups): 5,447 train, 1,172 calibration and 1,171 test rows in total.
3. **Thresholds are chosen on the runtime the app serves (ONNX).** v2's first threshold was chosen on PyTorch scores: 0.546, a value inside a flat region of recall. On ONNX scores the same rule gives 0.846. All thresholds are now computed on ONNX outputs.
4. **Model selection on calibration data.** There were three candidates: the transformer, a TF-IDF word and character n-gram logistic regression, and the **average of the two**. The rule, fixed before looking at test or challenge results, was: highest calibration macro-F1 with calibration ham FPR ≤ 1%, ties going to the lower FPR. **The average won** (calibration macro-F1 0.933, FPR 0.34%, scam recall 98.65%). Warning threshold: **0.611**.

The base model and training configuration are unchanged from v1: DistilBERT fine-tuned for 4 epochs. Training took 305–415 seconds on an M4. The temperature is 1.2916, and the best epoch was 4.

## Results

### Unchanged v1 test set (870 Mendeley SMS)

| Model | Macro-F1 | Scam precision | Scam recall | Genuine flagged |
|---|---|---|---|---|
| text-ml-v1 (threshold 0.9) | 0.896 | 1.000 | 0.959 | 0 / 725 |
| **text-ml-v2 (average, 0.611)** | **0.897** | **1.000** | **0.966** | **0 / 725** |

The fix cost nothing on the original task. Confusion matrix for v2 (rows are the true class, columns the predicted class: ham, spam, smishing): ham `725 0 0`, spam `5 54 7`, smishing `0 12 67`.

### Full v2 test set (1,171 rows), the three candidates

| Candidate | Macro-F1 | Precision | Recall | Genuine flagged (FPR) |
|---|---|---|---|---|
| Transformer (0.846) | 0.920 | 1.000 | 0.976 | 0.00% |
| TF-IDF + logistic regression (0.305) | 0.910 | 0.973 | 0.987 | 0.91% |
| **Average (0.611)** | **0.925** | **1.000** | **0.983** | **0.00%** |

The 301 synthetic held-out rows score perfectly: 151 of 151 scams caught and 0 of 150 genuine flagged. **Don't read this as real-world accuracy.** The rows come from the same template generator as the training rows, so the generator's style is easy to learn. (Their macro-F1 shows 0.667 only because they contain no spam class.)

### Independent challenge set (44 messages, written before v2 was trained)
[challenge_set.jsonl](../../../sentinel/text_ml/challenge_set.jsonl) contains 24 genuine Indian-style messages (bank debit and credit, OTP, EMI, delivery, PNR, insurance, college, Hinglish chat) and 20 modern scams. Neither model trains on it.

| Model | Genuine wrongly flagged | Scams caught |
|---|---|---|
| text-ml-v1 | **17 / 24** | 14 / 20 |
| v2 transformer alone | 3 / 24 | 11 / 20 |
| v2 TF-IDF alone | 4 / 24 | 17 / 20 |
| **text-ml-v2 (average)** | **2 / 24** | **14 / 20** |

The set is tiny (n = 44), so treat these as indicative only. The TF-IDF model alone catches the most scams here, but it was not selected: the choice was made on calibration data before the challenge set was scored. Still missed by v2 (score against the 0.611 threshold):
- "new number, need money for college fees" (0.55)
- a crypto "daily returns" pitch (0.58)
- a task-commission prepay (0.50)
- "your son is detained, transfer now" (0.39)
- a Hinglish "send me 10 hazaar (₹10,000) on UPI" request (0.15)
- an army officer buying furniture through a QR code (0.06)

Still wrongly flagged: a Zomato OTP (0.77) and a shop bill paid by card (0.70).

### Robustness (perturbed scam test messages; transformer alone, v2 transformer threshold)
Leetspeak 0.980, Cyrillic look-alike letters 0.976, **dotted spacing 0.835** (v1: 0.959). The ensemble's character n-grams partly offset this, and the community network's fingerprints undo dotted spacing.

### Runtime
About 1.9 ms per message batched on CPU (ONNX plus the lexical model). The ONNX output matches the trained PyTorch model to within 3e-6.

## Limits
- **Synthetic data:** the new training data is synthetic and template-based. **v2 has not been validated on real recent Indian SMS.** Run `python -m sentinel.text_ml evaluate-private your.csv` on your own redacted messages (columns `text,label`). It prints only counts and row numbers, never text.
- **Languages:** English and Hinglish only. The other 12 languages in the source were left out, because the tokenizer is English-only.
- **Modern conversational scams** are still often missed. The [community network](../../../docs/community-network.md) is designed to cover these.
- The lexical member is a scikit-learn pickle. It is loaded only after its SHA-256 matches the manifest, but it still requires scikit-learn at runtime.
