# English conversation/harm module: source feasibility investigation

Date: 2026-10-12. Status: **source investigation complete; focused design and implementation are pending review**. The user selected this module as Sentinel's next milestone. No harm model has been trained, no protocol has been frozen, and no final test has been scored.

The [approved year-long design](superpowers/specs/2026-10-05-sentinel-year-long-design.md) requires an English module using ordered conversation turns, a message-only/context comparison, conversation/user isolation where the source permits it, and human-reviewed challenge cases. The current `sentinel.analysis` implementation still uses phrase rules and a quotation/reporting heuristic. The [aggregate audit](../output/research/context-harm-source-audit.json) contains source hashes and counts only; it contains no comments, usernames or annotator IDs.

## Recommended source: CAD v1.1, with a revised development cohort

[CAD's author repository](https://github.com/dongpng/cad_naacl2021) links the [Zenodo release](https://zenodo.org/records/4881008). The [paper](https://aclanthology.org/2021.naacl-main.182/) describes annotations made with conversation context. Zenodo's record metadata identifies the data licence as CC BY 4.0. The author notes corrections in v1.1; use that version and retain attribution. This investigation downloaded only `data.zip`, not the released trained models or predictions.

Verified source pins:

| Item | Measured identity |
| --- | --- |
| Record | `10.5281/zenodo.4881008` |
| Archive size | 9,941,773 bytes |
| Published archive checksum | `md5:63091d7a48bac5666e818fefed1f6575` |
| Measured archive SHA-256 | `69f5ed2fd7b40de21fe54c620549f0be6c34eaf55b8de06ff481cabe3e9476d2` |
| Selected member | `data/cad_v1_1.tsv` |
| Member SHA-256 | `7287d635e1d35ae1e64779ffe107df16f493c6ccc4084c4497bbf3f56ae0f349` |

The full member has 27,494 annotation rows representing 26,550 distinct utterance IDs. Multiple annotation rows can refer to one utterance; their text agrees in this release. Coalescing labels and respecting the author's `train`, `dev`, `test` and exclusion flags leaves 23,417 eligible utterances. Thread IDs, parent references, ordering, author metadata and contextual annotations are present. These measured counts precede Sentinel's final label, text, context and duplicate exclusions.

### Isolation problem and feasible alternative

The published eligible splits share zero thread IDs. However, training/dev share 573 known authors, training/test share 501, and dev/test share 203. Connecting all eligible threads through known authors produces a component with 22,420 of 23,417 utterances (95.74%), making a conventional four-way component split unsuitable.

A preliminary alternative preserves every published test thread. Remove whole original training/dev threads if any known author in that thread also occurs in a test thread; include authors of context/excluded rows when checking this overlap. Pool the remaining original training/dev threads before allocating Sentinel training, validation and calibration. Connect this pool by known authors. This leaves:

| Candidate cohort | Threads | Utterances | Utterances with any directed-abuse category |
| --- | ---: | ---: | ---: |
| Purged development pool | 405 | 2,982 | 422 |
| Preserved published test | 342 | 5,307 | 906 |

The pool has 241 known-author components; the largest has 711 utterances (23.84%) and 127 directed-abuse targets. This makes a grouped development allocation plausible. Actual class support after all exclusions and allocation remains a gate. By contrast, preserving the original train/dev separation and sequentially purging overlaps leaves only 1,229 training utterances with 102 directed-abuse targets; pooling is the stronger candidate.

Unknown/deleted author markers remain unknown and are excluded from identity joins. Metadata has quoted `"NA"` values, notably in root-link fields. Treating these as real shared IDs incorrectly creates a giant component. Use the author's TSV `QUOTE_NONE` convention, canonicalize metadata wrappers, and preserve actual quotation marks in comment text. Isolation is limited to **known** authors; the source cannot establish independence for unavailable identities. Purging also changes source/class composition and requires a retention report.

### Context and label checks still required

Same-thread direct parent lookup plus a verified root post/title alias resolves usable context for 2,395 development targets, including 382 directed-abuse targets, and 4,801 test targets, including 819 directed-abuse targets. Another 524/423 development/test targets have no parent reference; 63/83 have unavailable or unsupported parent text. Root aliases must be checked against the supplied root-link and thread metadata. Missing context must remain explicit; arbitrary previous rows or sibling replies cannot substitute for a parent.

A simple target-text comparison found 15 distinct normalized texts shared between the proposed pool and test. These are diagnostics, not a completed leakage audit. The design must define and verify duplicate/near-duplicate ownership using target and available context, and check full ancestry, cycles, text caps and retained class/group support before freezing. Neither model may receive gold annotations, rationales, author/thread IDs, split indicators or later replies as features.

CAD's primary annotations distinguish identity-, affiliation- and person-directed abuse, neutral content, counter-speech and slur annotations. The [author baseline loader](https://raw.githubusercontent.com/dongpng/cad_naacl2021/master/src/contextual_abuse_dataset.py) omits the separate slur category. Sentinel must explicitly review its own task mapping against the codebook: slur-only and mixed labels cannot silently become neutral. Counter-speech may co-occur with abuse, so its presence alone cannot cancel another annotation. The three directed-abuse categories above are a feasibility count, not an approved final binary mapping.

## Other candidates

**Civil Comments in Context (CCC):** The [author data documentation](https://github.com/ipavlopoulos/context_toxicity/tree/master/data) describes target/parent pairs with in-context and out-of-context annotations; the [research paper](https://arxiv.org/abs/2111.10223) states a CC0 data licence. The verified author `CCC.csv` has 9,929 rows, unique target IDs and no empty target/parent text. Its SHA-256 is `d424a5b6cd9dc90156a6caedb09634262ea92e619c323221b81eb3f72702ae29`, at source commit `5df49c294e6a41f0ba351e65fda7c315aa4cc168` (7,761,632 bytes). It lacks thread/article IDs and parent IDs; grouping repeated text alone cannot establish complete conversation isolation.

[TensorFlow Datasets documents an enriched context configuration](https://github.com/tensorflow/datasets/blob/master/docs/catalog/civil_comments.md), including article/parent metadata, a different reported row count, and a warning about parent leakage in existing base splits. That release was not acquired or checked here. It would need a separate provenance, join and label audit. CCC's toxicity ratings and CAD's directed-abuse categories are different tasks and should not be pooled as interchangeable labels.

**HASOC:** The [organizers' conversational task description](https://hasocfire.github.io/hasoc/2022/call_for_participation.html) targets code-mixed languages. It remains a later multilingual lead, not the default source for the selected English-first study.

## Proposed direction for the focused design

Recommend CAD v1.1 with the test-preserving purge and grouped development pool, subject to the remaining gates. Compare target-only and preceding-context inputs on the same cases and task-aligned labels. Establish CPU TF-IDF baselines; define a bounded compact-encoder pilot before committing to a neural candidate. Select all candidates before opening the sealed final evaluation.

The application should accept ordered turns, local speaker IDs and an explicit target turn, preserve reply relationships, report context coverage and provide an optional versioned harm result alongside existing analysis. Quoted/reported speech, counter-speech and ordinary disagreement need a separately adjudicated challenge set. This source supports an abuse-classification experiment; it does not establish real-world identity, intent or repeated cyberbullying.

This is a recommended design direction, not an implementation specification or permission to activate a model. The next step is reviewing this direction, then writing the focused specification and implementation plan.
