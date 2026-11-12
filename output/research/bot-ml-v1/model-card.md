# Model card: bot-ml-v1 (profile-metadata bot classifier)

> This card covers two models. The profile model is **research only**, because it failed its gate. The [activity model](#activity-model-bot-ml-activity-v1) is **released**, because it passed.

**Status: research only. It did not pass its release gate.** The model is built, verified by checksum and wired into the bot-detection module as a separate, replaceable component. Its estimate is **withheld** and never used in the classification. It's shown only when research mode is switched on explicitly (`SENTINEL_BOT_ML_RESEARCH=1`), and then labelled as such. This follows the project design: *"Provide bot likelihood only when the selected feature set passes validation. Otherwise report insufficient evidence."*

## Data
Thirteen public datasets from the Bot Repository (Indiana University OSoMe), totalling **111,168 Twitter accounts (81,692 bots, 29,476 humans)**, each pinned by SHA-256. See [data-audit.json](data-audit.json).

| Group | Datasets |
|---|---|
| Both labels (7, each a held-out test) | gilani-2017, cresci-rtbust-2019, cresci-stock-2018, midterm-2018, botometer-feedback-2019, **cresci-2015**, **cresci-2017** |
| Bots only | botwiki-2019, pronbots-2019, political-bots-2019, vendor-purchased-2019 |
| Humans only | verified-2019, celebrity-2019 |

- **Terms:** academic research only. The Bot Repository sets are mostly CC BY-NC-ND 4.0. The cresci sets (IIT-CNR, *The Fake Project*) are "for research purposes only", with no redistribution without their disclaimer. Raw data is kept local and git-ignored, and nothing derived from it is redistributed.
- **Cleaning:**
  - 3,574 accounts appearing in two datasets were deduplicated, so each belongs to only one and can't leak into its own held-out test. Most were cresci-2017's fake followers, which are the cresci-2015 accounts.
  - 70 rows whose copies disagree on the label were removed.
  - Account IDs were pseudonymised.
- **Date quirks fixed:**
  - cresci-2017's traditional_spambots_1 stores its creation date in epoch milliseconds.
  - cresci-2017 records collection time in `crawled_at`. Its `updated` field is a later database update and `timestamp` is the creation time. Using `updated` would have inflated account ages.
- **Not used:**
  - astroturf: labels but no profile data.
  - twibot-20: only a sample, restricted by its creator.
  - caverlee-2011: no username or bio text.
  - TwiBot-22: needs an application; a draft request has been prepared.
- **Balancing:** each dataset is capped at 4,000 accounts per label for training (44,229 accounts).

## Features (16, all obtainable by Sentinel at analysis time)
- Follower, following and post counts (log-scaled), account age, and posts, followers and following per day.
- The following/followers balance.
- Bio length and presence, username length, digit count and digit share, display-name length and digits, and whether a link is set.

**Deliberately excluded:**
- **verified:** nearly every verified account comes from the human-only sets, so it would reveal the dataset rather than the behaviour.
- **default profile picture:** absent for every midterm-2018 account (84% bots), so "unknown" would identify that dataset.
- **likes and list counts:** Sentinel's inputs don't collect them.

## Method
- **Candidates:**
  - Histogram gradient boosting.
  - Logistic regression.
  - **Sentinel's hand-set heuristic** as a baseline, using its profile signals.
- **Calibration:** isotonic regression on a separate calibration split, stored as plain JSON thresholds.
- **Selection rule, fixed in advance:** the highest calibration-split AUC on the same-distribution split. It chose gradient boosting.
- **Headline evaluation: leave one dataset out.** For each of the 7 datasets with both labels, train on everything else and test on all of the held-out dataset.
- **Release gate, fixed before serving:** AUC of at least **0.80 on every** held-out dataset, and same-distribution calibration error (ECE) of at most 0.05.

## Results

### Same distribution (stratified 70/15/15 across all datasets, 6,639 test accounts)

| Model | ROC AUC | F1 | Precision | Recall | Humans flagged | ECE |
|---|---|---|---|---|---|---|
| Heuristic (hand-set) | 0.742 | 0.290 | 0.933 | 0.172 | 1.3% | — |
| **Gradient boosting** | **0.967** | **0.911** | 0.937 | 0.886 | 6.3% | 0.008 |
| Logistic regression | 0.899 | 0.839 | 0.837 | 0.841 | 17.3% | 0.013 |

### Unseen datasets (leave one out): the realistic picture

| Held-out dataset (accounts) | Heuristic | Gradient boosting | Logistic regression |
|---|---|---|---|
| gilani-2017 (2,465) | 0.510 | 0.600 | 0.577 |
| cresci-rtbust-2019 (693) | 0.478 | 0.664 | 0.716 |
| cresci-stock-2018 (13,275) | 0.539 | 0.618 | 0.651 |
| midterm-2018 (50,534) | 0.978 | 0.821 | **0.979** |
| botometer-feedback-2019 (509) | 0.624 | 0.785 | 0.756 |
| cresci-2015 (5,301) | 0.945 | 0.937 | 0.920 |
| cresci-2017 (11,012) | 0.780 | 0.706 | **0.857** |
| **Mean** | 0.693 | 0.733 | **0.779** |

**Release gate: failed.** Gradient boosting's worst held-out AUC is 0.600 (gilani-2017), against the required 0.80. Logistic regression would also fail, at 0.577 on the same dataset.

### Effect of adding cresci-2015, cresci-2017 and botometer-feedback-2019
The mean unseen-dataset AUC rose from 0.651 to 0.733 for gradient boosting and from 0.713 to 0.779 for logistic regression, and same-distribution AUC rose from 0.956 to 0.967. Note that the mean now covers 7 held-out datasets instead of 4. On the original four, logistic regression improved on rtbust (0.652 → 0.716) and midterm (0.954 → 0.979) but not on gilani or cresci-stock.

## What this shows
1. **High scores on mixed data overstate real-world accuracy.** AUC 0.967 on mixed data falls to 0.60–0.98 depending on which dataset is held out. Bot detectors learn dataset-specific quirks (Yang et al., AAAI 2020; Echeverría et al., 2018).
2. **The simpler model generalises better.** Logistic regression beats gradient boosting on 5 of the 7 unseen datasets (mean 0.779 vs 0.733). The pre-set rule picked gradient boosting on same-distribution data. Next time the selection should use nested cross-dataset validation instead of being switched now on the evaluation data.
3. **More varied data helps, but profile metadata alone hits a ceiling.** gilani-2017 and cresci-stock-2018 contain bots whose profiles look human. Detecting them needs activity and content features (posting rhythm, duplication), which the heuristic already computes when posts are uploaded.
4. **The heuristic and the model are complementary.** The heuristic is near-perfect on midterm-2018 and cresci-2015 and near chance on gilani and rtbust.

## Next steps to pass the gate
- Train on **activity and content features** from the tweets these datasets include, the same signals as the heuristic, so Sentinel can use them at analysis time from uploads.
- Choose the model and data by **nested leave-one-dataset-out validation** (Yang et al.'s data-selection approach), never by the held-out test.
- Add **TwiBot-22** once access is granted.

## Reproduce

```bash
.venv-text-ml/bin/python -m sentinel.bot_detection.ml prepare
.venv-text-ml/bin/python -m sentinel.bot_detection.ml train
```

The raw archives go in `data/bot-ml/raw/`; their URLs and SHA-256 values are in `sentinel/bot_detection/ml/source.py`. The cresci-2017 archive is 465 MB. Training takes about 25 seconds on CPU.

---

# Activity model (bot-ml-activity-v1)

**Status: released. It passed its release gate.** The gate was set before training. It applies **only to X accounts with at least 20 timed posts** (uploaded, or from an API). It is shown in the report as a **separate line**; the heuristic classification is unchanged. Results are in [evaluation-activity.json](evaluation-activity.json) and the data audit in [activity-audit.json](activity-audit.json).

## Data
Only **cresci-2015** and **cresci-2017** include full post histories. The other Bot Repository sets hold one tweet per account. Each account's **latest 100 posts** are turned into features by **the same functions Sentinel applies to uploaded posts** (`sentinel/bot_detection/features.py`, shared through `ml/features.account_features`). Accounts with fewer than 20 posts are left out. **Only numeric features are stored, never post text.**

| Source / subset | Label | Accounts |
|---|---|---|
| cresci-2015 E13 | human | 1,456 |
| cresci-2015 TFP | human | 425 |
| cresci-2017 genuine_accounts | human | 1,079 |
| cresci-2015 FSF, INT, TWT (fake followers) | bot | 604 + 1,162 + 325 |
| cresci-2017 social_spambots_1 | bot | 991 |
| cresci-2017 social_spambots_2 | bot | 3,457 |
| cresci-2017 social_spambots_3 | bot | 464 |
| cresci-2017 traditional_spambots_1 | bot | 459 |
| **Total** | | **10,422** (2,960 humans, 7,462 bots) |

- cresci-2017's fake followers (2,091 accounts) are the same accounts as cresci-2015's, so they're kept only under cresci-2015.
- cresci-2017's traditional_spambots_2, 3 and 4 have profiles but **no post history**, and were skipped.

**Features (33):** 17 activity and content features plus the 16 profile features above. The activity and content features are:
- posts per day, repost share, interval regularity, repeated-interval share, burst share;
- active hours, hour-of-day entropy, quietest-6-hour share;
- exact and near-duplicate share;
- hashtags, mentions and links per post, top link-domain share;
- vocabulary diversity, spam-language share, mean log likes.

Missing values stay missing: gradient boosting handles them natively, and logistic regression uses median imputation with missing-value indicators.

## Protocol (fixed before training)
- **B. Unseen bot type (used for model selection).** Hold out one bot family (fake followers, social spambots 1, 2 or 3, or traditional spambots) together with a fixed 20% of every human subset. Train on the rest, calibrating on an inner 20% split.
- **A. Cross-dataset (the untouched final check).** Train on cresci-2015 and test on cresci-2017, and the reverse.
- **Selection:** the highest **worst-fold AUC across B**.
- **Release gate:** AUC of at least **0.80 on every fold of A and B**, and same-distribution calibration error (ECE) of at most 0.05.
- **Candidates:** gradient boosting, logistic regression, and Sentinel's hand-set heuristic computed on the same features.

## Results (AUC, then F1 and humans flagged at the 0.5 threshold)

### B. Unseen bot type

| Held-out bot family (bots / humans) | Heuristic AUC | Gradient boosting AUC · F1 · humans flagged | Logistic regression AUC · F1 · humans flagged |
|---|---|---|---|
| fake followers (2,091 / 591) | 0.700 | 0.949 · 0.491 · 1.2% | 0.946 · 0.814 · 1.7% |
| social spambots 1 (991 / 591) | 0.157 | **0.981** · 0.857 · 1.5% | 0.822 · 0.705 · 2.4% |
| social spambots 2 (3,457 / 591) | 0.956 | 0.991 · 0.997 · 2.0% | 0.992 · 0.992 · 3.1% |
| social spambots 3 (464 / 591) | 0.893 | 0.991 · 0.966 · 1.9% | 0.935 · 0.471 · 2.2% |
| traditional spambots (459 / 591) | 0.537 | 0.995 · 0.975 · 1.9% | 0.995 · 0.970 · 2.4% |
| **Worst fold** | 0.157 | **0.949** | 0.822 |

### A. Cross-dataset (untouched check)

| Train → test (bots / humans) | Heuristic AUC | Gradient boosting AUC · F1 · humans flagged | Logistic regression AUC · F1 · humans flagged |
|---|---|---|---|
| cresci-2015 → cresci-2017 (5,371 / 1,079) | 0.720 | 0.849 · 0.810 · 4.3% | 0.938 · 0.886 · 2.7% |
| cresci-2017 → cresci-2015 (2,091 / 1,881) | 0.720 | 0.884 · 0.775 · 6.7% | 0.956 · 0.904 · 1.9% |

### Same distribution (stratified 85/15, 1,567 test accounts)
- Gradient boosting: AUC 0.997, F1 0.993, precision 0.992, recall 0.994, 2.0% of humans flagged, ECE 0.007.
- Logistic regression: AUC 0.995, F1 0.985, ECE 0.009.
- Heuristic: AUC 0.735.

**Selection:** gradient boosting (worst B-fold AUC 0.949, against 0.822 for logistic regression). **Gate: passed.** The worst fold over A and B is 0.849 (cresci-2015 → cresci-2017), and ECE is 0.007.

## What this shows
1. **Activity patterns generalise far better than profile metadata.**
   - The worst held-out AUC is 0.849, against 0.600 for the profile model.
   - Social spambots 1, built to look human, are caught at AUC 0.981 when they were never seen in training. The heuristic scores 0.157 on them, which is *worse than chance*: its hand-set signals point the wrong way for these accounts.
2. **Ranking transfers better than the threshold.**
   - For held-out fake followers, gradient boosting ranks well (AUC 0.949) but catches only a third of them at 0.5 (F1 0.49). Its calibration, learned on other bot types, is conservative for a new type.
   - Across datasets, 4–7% of humans are flagged at 0.5.
   - The report therefore shows the **probability, not a verdict**, and keeps it separate from the heuristic classification.
3. **Logistic regression did better on the cross-dataset check** (0.938 and 0.956 vs 0.849 and 0.884). The selection rule, fixed in advance, used the unseen-bot-type folds and chose gradient boosting. This is reported rather than changed after the fact.

## Limits
- **Narrow training data.** There are only two source datasets, from the same research group, covering **Twitter accounts from about 2009–2017**. Today's bots, including LLM-written ones, and other platforms are out of distribution, which is why the model is applied to X only.
- **The human side of fold B isn't source-shifted.** Its held-out humans come from the same subsets as the training humans; fold A covers human shift.
- **Uploaded posts can't be verified.** A curated export can make an account look more or less automated.
- **Features only, no text.** The model sees numeric features only. Wording is assessed separately by Sentinel's text model and rules.
- **Dependencies.** The model is a scikit-learn pickle, loaded only after its SHA-256 matches the manifest. It needs the text-ml environment (scikit-learn 1.9.1); loading it under another version produces a version warning.

## Reproduce (activity model)

```bash
.venv-text-ml/bin/python -m sentinel.bot_detection.ml prepare-activity
.venv-text-ml/bin/python -m sentinel.bot_detection.ml train-activity
```

`prepare-activity` reads several GB of tweets with 8 worker processes and takes about 3.5 minutes. `train-activity` takes about 13 seconds.
