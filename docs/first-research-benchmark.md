# First research benchmark: linked email spam versus ham

This is a reproducible **exploratory baseline**, not a phishing-detection result. The purpose is to test Sentinel's paired-data pipeline on real messages and links while the team collects a suitable phishing and legitimate social-message dataset.

## Source and pair audit

The input is `Assassin.csv` from [Seven Phishing Email Datasets](https://figshare.com/articles/dataset/Seven_Phishing_Email_Datasets/25432108), version 1, published under CC BY 4.0. The downloaded file's MD5 is `d921e0b2333bfaa058bd38193e6b3fbd`, matching the [Figshare API file record](https://api.figshare.com/v2/articles/25432108). The original [Apache SpamAssassin corpus](https://spamassassin.apache.org/old/publiccorpus/readme.html) labels messages spam and ham; **spam must not be relabelled as verified phishing**. Its messages are old and may contain personal details, so the raw and derived message CSVs stay in local ignored files. The aggregate reports contain no message text.

The importer reads the message's subject and body, retains only messages with exactly one HTTP(S) or `www` link in that same text, and never opens the link. It ignores the source's precomputed `urls` flag for pairing because that flag does not identify a linked destination. Multiple-link messages are excluded so the linked destination is unambiguous. Cases over 8,000 characters and exact normalized duplicate messages are also excluded. The audit records the following:

| Stage | Cases |
| --- | ---: |
| Source rows | 5,809 |
| Multiple links in original message | 2,439 |
| No link found in original message | 1,159 |
| Message over 8,000 characters | 296 |
| Exact duplicate message | 3 |
| Retained paired rows | 1,912 |
| Ham / spam among retained rows | 1,546 / 366 |
| Destination-domain groups | 308 |

See [machine-readable source audit](../output/research/assassin_audit.json) for hashes and exact counts.

## Experiment and result

The same group-held-out split is used for message-only, URL-only, and combined multinomial Naive Bayes models. URL spans are removed from message features, so message-only cannot read link tokens. The URL-only model receives the one linked URL; combined receives both feature sets. Globally unseen tokens are ignored at prediction time. Each run holds out 382 of 1,912 cases, with no destination-domain-group or repeated message wording overlap after URL spans are removed, and prefers a test set near the full corpus's class balance. The fixed seeds are 11, 23, 42, 71, and 101. The table reports means across those five overlapping splits; this is a stability check, **not** five independent test sets or a confidence interval. F1 treats spam as the positive class. These figures were regenerated after the URL-stripped wording split was enforced.

| Input | Mean spam F1 | F1 range | Mean macro F1 | Mean false-positive rate |
| --- | ---: | ---: | ---: | ---: |
| Message only | 0.9218 | 0.8800–0.9530 | 0.9517 | 0.0226 |
| URL only | 0.4087 | 0.2166–0.8226 | 0.5675 | 0.3102 |
| Message + URL | 0.9281 | 0.8993–0.9600 | 0.9556 | 0.0200 |

On this corpus, combining URL tokens gave a small mean F1 advantage of 0.0063 over message-only input, but the gain was absent or slightly reversed in two of five splits. The URL-only baseline had variable F1 and false-positive rate (0.0000–0.6792 across splits). These observations are useful for designing a better URL baseline and evaluating it on a genuinely phishing-labelled corpus; they do not establish performance on social media scams. The [full five-seed report](../output/research/assassin_evaluation_5seeds.json) contains the confusion counts, class balance, latency, and overlap audit for every split.

The domain-group rule is an approximation for common top-level domains. It cannot detect every shared campaign or message paraphrase. Source labels were inherited, not re-annotated; this subset excludes multi-link and long messages and comes from early-2000s email. No threshold tuning or model choice should be based on the held-out rows. The next study needs current, source-traceable phishing **and** legitimate message–link pairs, manual review of ambiguous labels, campaign-aware grouping, and a locked final test set. The [Mishra–Soni smishing dataset](https://data.mendeley.com/datasets/f45bkkt8pr/1) was inspected but unsuitable for this paired comparison: only two of its ham messages exposed a recognizable link in their text.

## Reproduce locally

Download only `Assassin.csv` from the Figshare page into `data/source_assassin.csv`. Do not open links found in the messages. With Python 3.10+:

```powershell
python -m sentinel.datasets data/source_assassin.csv data/assassin_pairs.csv --audit-out output/research/assassin_audit.json
python -m sentinel.research data/assassin_pairs.csv --seeds 11,23,42,71,101 --report-out output/research/assassin_evaluation_5seeds.json
```

The paired CSV stays local because it contains the original email text. This exploratory spam model should not be exported into Sentinel's phishing-warning UI.
