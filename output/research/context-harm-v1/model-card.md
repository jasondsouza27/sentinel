# Sentinel English directed-abuse study: unavailable allocation

Recorded on 2026-10-14. The software supports a target-only/context comparison,
but **no real harm model was trained and the protected test was not scored**.
No contextual gain, accuracy, calibrated confidence or live reliability is claimed.

CAD v1.1 is attributed to Vidgen et al., *Introducing CAD: the Contextual Abuse
Dataset*, under CC BY 4.0. The [author release](https://zenodo.org/records/4881008)
and [paper](https://aclanthology.org/2021.naacl-main.182/) define the historical
Reddit labels. Archive/member/codebook identities and the consistency review are
recorded in [source-audit.json](source-audit.json).

The source contains 26,550 coalesced utterances, with 23,416 eligible targets.
Conservative ancestry/cap filtering yields 14,408 context-available primary cases
and 8,964 missing-context diagnostics. One ordering-inconsistent thread excludes
42 targets; two additional targets exceed the character limit. Unsupported
intermediate parents stop reconstruction; the tool does not invent connections.

All known authors from published test threads, including excluded/context rows,
are reserved. Whole development threads are purged for author overlap, then masked
exact/near-duplicate ownership. Remaining original train/dev threads are pooled.
The primary development pool has 1,624 cases (1,356 negative, 268 positive); the
protected primary test contains 3,315 cases (2,767 negative, 548 positive).
These are admission counts, not model evaluation results.

The fixed seed-42 greedy 70/15/15 allocation fails three production gates:

| Partition | Cases | Negative | Positive | Components | Failed gate |
| --- | ---: | ---: | ---: | ---: | --- |
| Training | 1,094 | 919 | 175 | 122 | At least 200 positives required |
| Validation | 280 | 241 | 39 | 5 | At least ten components required |
| Calibration | 250 | 196 | 54 | 8 | At least ten components required |

The failure describes this one allocation; it is not proof that every possible
allocation is mathematically infeasible. No seed retry, component cutting,
replacement split, criterion change, fitted artifact or final receipt was used.
See [cohort-audit.json](cohort-audit.json) and [research-status.json](research-status.json).

The conditional encoder outcome is `neural_unavailable: protected_cohort_unavailable`.
No package/model bodies, neural installation, CUDA preflight, training pilot or
full encoder fits were performed. Software tests cover pinned sources, token
coverage, failures and resource boundaries using invented/controlled fixtures;
they do not measure physical GPU memory, throughput or learned quality.

The challenge intake is empty and reserved, with evaluation pending. Future
permissioned cases need two independent humans and adjudication; predictions
cannot supply labels. Use a new private collection/version root. Quotation alone
does not determine a negative label; CAD can label reported abuse without explicit
distancing. A content prediction would not establish speaker intent or harassment.

The app's ordered conversation workflow and reviewed-snapshot saving are usable.
Learned live warnings remain unavailable; phrase observations remain separate.
Historical Reddit labels do not establish current, multilingual or cross-platform
accuracy. A subsequent approved data/protocol version and separate release review
are needed before training or activating learned warnings.
