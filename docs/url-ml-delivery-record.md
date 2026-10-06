# URL ML foundation delivery record

Recorded on 2026-10-06. This is the first trained subsystem of the approved year-long
Sentinel project. The measured url-v1 result is research-only because the source has
severe legitimate-URL format confounding. The standard launcher keeps it disabled.


Delivery verified: implementation commit `07960624dfdddc5cbd48d9faaa7a5a77214799b0`
was fast-forwarded into `codex/sentinel` and pushed to the existing private repository
[jasondsouza27/sentinel](https://github.com/jasondsouza27/sentinel). Remote SHA verification
matched the implementation HEAD. The active Desktop project independently passed all
78 Python tests and 12 web-client checks after integration. Its preserved real artifact
served the optional API; the separate default stdlib-only API kept ML disabled. Neither
smoke check saved cases or changed the running server.

All 16 acquired/derived private research files and all 7 immutable artifact files were
byte-hash verified in the active project. Its dedicated Python 3.11 environment and
16 locked packages remain installed. After this verification, the temporary plan scratch
directory, fully merged implementation worktree and merged feature branch were removed.
The primary project and original case/curation data are preserved. The final code and
aggregate reports are on GitHub; private source rows and binary artifacts stay local.

One fresh independent reviewer examined commits 6f844e1..de68f8d against the approved
specification and plan. The verdict was “With fixes”: no Critical findings, three
Important findings and one Minor. Each Important finding was reproduced with failing
regression tests, corrected inline, and verified by the complete suite. No second review
was dispatched. Final fresh-lock verification: 78 Python tests, no dependency skips;
12 Node web-client checks; git diff --check clean.

The host correction audit found zero changes across 235,795 raw source outcomes and
235,343 frozen URL identities/groups. All 23,534 original calibration scores pass the
new variation guard. Historical data, splits, fitted models, thresholds and final-test
results are preserved. Failed experiments now write private, exclusive diagnostic
reports outside immutable trained artifacts.

The reviewer set aside production quality, later application milestones, intentional
string preservation/grouping, Phase 0 intake behavior, trusted-local pickle loading,
historical rerun claims and ambiguous browser syntax. The executor's explicit decisions
and costs for each are included below. The deferred Minor consists of two old future-tense
sentences in the source-audit document; measured results are already present below them.

Implementation and final review evidence

# SDD ledger — plan: docs/superpowers/plans/2026-10-05-sentinel-ml-foundation.md
Execution: user approved Native implementation on 2026-10-05; first whole-branch base 6f844e1.
Baseline: Python 31/31, Node web client 12/12 passed.
Ruling: native worktree tool cannot resolve Sentinel from the obsolete OneDrive chat workspace — use explicit Git worktree at .worktrees/url-ml in the verified Sentinel repository — cost if wrong: worktree is managed by Git rather than the app.
Ruling: Python 3.11 is not registered — use locally bootstrapped uv to provision the approved runtime and venv without changing system Python/PATH — cost if wrong: additional dependency acquisition and a uv-managed base interpreter must be preserved.
Pre-flight: 1→2/3/4/6 UrlParser/record/hash contracts align.
Pre-flight: 2→3 DatasetBundle and manifest fields align; loader verifies source/derived/PSL hashes.
Pre-flight: 3→4/5/6 SplitBundle partitions align; inference artifact must not require source rows.
Pre-flight: 4→5 model pipelines/raw class-1 scores align; process isolation provides peak resource records.
Pre-flight: 5→6 Selection/Calibration/RunBundle align; raw threshold remains decision authority.
Pre-flight: 6→7 service states and assessment JSON align; disabled path cannot import optional ML dependencies.
Pre-flight: 2–7→8 CLI commands align; existing frozen outputs must be loaded, not overwritten.
Tasks 1–8: completion evidence follows below.
Task 1: Ruling: uv downloaded a usable 3.11.17 runtime but its minor-version junction check failed — create venv using the verified runtime executable directly — cost if wrong: uv alias remains unreliable; direct interpreter path is required.
Task 1: Ruling: disable PSL disk cache rather than create one beside the snapshot — keeps artifacts immutable and avoids stale caches — cost if wrong: small startup parsing cost.
Task 1: RED: parser suite 6 failures, all missing URL parser feature; installed CPython 3.11.17 and all candidate dependency pins.

Task 1: Ruling: preload tldextract via its public extract_str session argument and explicitly close local responses - fixes upstream requests-file Windows handle retention - cost if wrong: small extra startup load and a local-session compatibility dependency.
Task 1: complete (commits 6f844e1..77c76e7, tests: ./.venv-ml/Scripts/python.exe -m unittest discover -s tests -v → OK)
Task 2: complete (commits 77c76e7..df055b4, tests: ./.venv-ml/Scripts/python.exe -m unittest discover -s tests -v → OK)
Task 3: complete (commits df055b4..e3fc2e2, tests: ./.venv-ml/Scripts/python.exe -m unittest discover -s tests -v → OK)
Task 4: complete (commits e3fc2e2..50ba778, tests: ./.venv-ml/Scripts/python.exe -m unittest discover -s tests -v → OK)

Task 5: Ruling: retain the best already-fitted model and validation threshold from each branch for the final same-test comparison - avoids unplanned retraining and is required to compare all baselines - cost if wrong: somewhat larger trusted artifact and baseline metadata.
Task 5: complete (commits 50ba778..481caf5, tests: ./.venv-ml/Scripts/python.exe -m unittest discover -s tests -v → OK)
Task 6: complete (commits 481caf5..5b0eeea, tests: ./.venv-ml/Scripts/python.exe -m unittest discover -s tests -v → OK)
Task 7: complete (commits 5b0eeea..4f65e9c, tests: ./.venv-ml/Scripts/python.exe -m unittest discover -s tests -v → OK)

Task 8: Ruling: preserve the frozen result and designate url-v1 research-only after the source-format audit showed every legitimate record is an HTTPS www homepage with an empty path - benign documentation links fail and no final-test/staged-case tuning is allowed - cost if wrong: broader data and external/temporal validation remain prerequisites for useful live deployment.

Task 8: Ruling: execute the plan final review/integration/push checkbox after the task completion checkpoint as the executing-plans final branch gate - the whole-branch reviewer must consume the completed research deliverables - cost if wrong: task completion and final delivery must be tracked separately until that gate is finished.
Task 8: Evidence: 10/10 real fits succeeded, peak 990318592 bytes; final F1 0.9706736353, FPR 0.0434556915; 1000 domain resamples. Frozen split identical; independent repeated fit max score difference 0.0 on 500 validation URLs. Fresh lock 68/68 Python with zero dependency skips and Node 12/12; stdlib startup verified separately.

Task 8: Fixed bounded forbidden-POST body handling after one Windows connection-abort failure. test_forbidden_post_consumes_bounded_body_before_response RED (0 bytes consumed) -> GREEN; fresh locked environment full suite 69/69 with no ML skips. Model, threshold and held-out results unchanged.
Task 8: complete (commits 4f65e9c..de68f8d, tests: ./.venv-ml/Scripts/python.exe -m unittest discover -s tests -v → OK)

Final review: one fresh reviewer (gpt-6-astra), whole branch 6f844e1..de68f8d. Verdict With fixes. Re-grade by user impact: three Important findings retained; no Critical. One Minor documentation status inconsistency deferred. No re-review.
Final: fixed URL host identity and ambiguous numeric IPv4 grouping — test_unicode_host_mapping_precedes_ip_classification_and_is_idempotent, test_browser_numeric_ipv4_aliases_are_unsupported, test_unicode_alias_conflicts_and_ambiguous_ip_exclusions RED→GREEN, suite 72/72.
Final: minor (deferred): two old future-tense sentences in docs/url-ml-source-audit.md should be reconciled with the completed measurements already published below them.
Final: fixed degenerate score calibration — test_constant_imbalanced_scores_do_not_manufacture_confidence and test_clipped_and_numerically_tied_logits_are_unavailable RED→GREEN, suite 74/74.
Final: Ruling: reject ambiguous short, octal and hexadecimal IPv4 host spellings rather than implement every browser alias — numeric hosts must have one canonical identity for source conflict removal and splitting — cost if wrong: some browser-loadable URLs return unsupported until a separately evaluated canonicalization policy is added.
Final: Ruling: keep parser schema v1 and preserve historical artifact/data after auditing every 235795 raw source record and 235343 frozen rows — corrected parser changes zero source outcomes, accepted identities or groups; implementation revision/source hash explicitly records the bug fix — cost if wrong: edge-input behavior differs by Git revision and downstream reproduction must use the recorded code revision.
Final: Ruling: require clipped logit range greater than 1e-8 for calibration — a constant or numerical-noise-only predictor cannot justify a fitted confidence curve — cost if wrong: a nearly constant but informative predictor may return unavailable calibration and must be assessed under a future protocol.
Final: fixed failed-run audit loss — all four FailureReportTests RED→GREEN, fresh locked suite 78/78, Node 12/12, git diff --check clean. First/second pilot failure reports, all ten failed configurations, worker exception details, parameters and resource context are preserved; existing outputs are not overwritten.
Final: Ruling: Production detection quality — retain research-only status and keep the normal launcher's learned model disabled because the benign-link failures and source bias are demonstrated — cost if wrong: broader data and external validation are still necessary for useful live warnings.
Final: Ruling: Queued jobs, cancellation, process-isolated inference, team authentication and UI redesign — the first approved plan delivers a single-host one-slot compatibility adapter; the parent design schedules these application capabilities later — cost if wrong: this milestone cannot yet serve a production team workflow.
Final: Ruling: Path/query/fragment spelling preservation — preserve source spelling as approved for this URL-string experiment; this host fix does not silently adopt full browser URL serialization — cost if wrong: some browser-equivalent path spellings remain distinct research strings.
Final: Ruling: Unknown-suffix full-host grouping — keep the explicitly approved fallback and flag unknown suffixes using the frozen snapshot — cost if wrong: related unknown-suffix hosts can remain in different groups and require a future grouping policy.
Final: Ruling: Existing API trimming and 2048-character validation — keep the Phase 0 request contract while the independent ML parser enforces its own support boundary — cost if wrong: surrounding whitespace removed at API intake is not available to the model.
Final: Ruling: Pickle authenticity — retain the documented trusted-local artifact boundary; hashes verify corruption rather than authenticate the producer — cost if wrong: loading an attacker-controlled replacement pickle can execute code despite consistent hashes.
Final: Ruling: Reviewer did not repeat acquisition, benchmark training or fresh installation — accept the original execution evidence, exact hashes, fresh-lock tests and independently repeated chosen fit recorded in this session; the final reviewer inspected those records — cost if wrong: historical benchmark reproduction has not been independently rerun by another researcher.
Final: Ruling: External/live/temporal validation, reviewed paired intake, harm/profile ML and the usability pilot — leave them as visible future milestones and make no corresponding performance claim in this first subsystem — cost if wrong: the main combined-evidence question and remaining year-long application work remain unfinished.
Final: Ruling: Empty ports, repeated user information and scoped IPv6 syntax — retain the existing offline acceptance where no consequential host-identity defect was demonstrated; submitted destinations are never fetched — cost if wrong: some accepted research strings may be rejected or interpreted differently by a browser.
Final: Ruling: Final integration choice — use the user's prior repository push request and the approved Task 8 integration/push instruction to fast-forward codex/sentinel and push the personal project after fresh verification — cost if wrong: the default project branch advances directly rather than waiting for a separate pull-request review.
