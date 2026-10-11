# Sentinel URL v3 frozen evaluation

Selected branch: char_tfidf. Thresholds were frozen on validation.
Artifact manifest SHA-256: 1ccaa15e08e6baae002d6cbe9505e4161ef44f2539a590feed8a2e7e9d124896
Protocol SHA-256: 3d87c3dd6263837c32744717fd4957579fb1d5eb8c2341dc126acfca0de99e13

primary: 166369 URLs, 78202 components. Precision 0.9318924617817607, recall 0.922338455117001, F1 0.9270908447288031, FPR 0.05761234295397032.
Legitimate queries: 13 false positives / 52 URLs; FPR 0.25.
Calibration available; Brier 0.051228514818420966, ECE 0.009168469508478883; temporal validation unavailable.
supplemental: 4348 URLs, 3265 components. Precision 0.8296, recall 0.8482617586912066, F1 0.8388270980788676, FPR 0.22385706778770362.
Legitimate queries: 27 false positives / 44 URLs; FPR 0.6136363636363636.
Calibration available; Brier 0.13689822630760215, ECE 0.07389694438090585; temporal validation unavailable.

Both learned branches, fixed rules and the format diagnostic are compared at 5%/1% validation budgets.
Uncertainty resamples whole connected components with 1,000 replicates, seed 42.

Historical URL annotations do not verify present-day sites.
Supplemental is group-held-out from a source also used in development; it is not source-independent.
Collection-month documentation is not a row date; temporal validation is unavailable.
Unknown campaigns and popular-domain sampling restrict generalization.
Small subgroups and constant bootstrap intervals do not establish certainty.
Prevalence scenarios assume stable rates; they are not deployment estimates.
URL-only results do not establish message-link fusion benefit.
Research candidate only; learned live warnings remain disabled.

Sources: PhreshPhish authors; Hannousse, Abdelhakim and Yahiouche, Salima, Web page phishing detection V3, CC BY 4.0.
https://data.mendeley.com/datasets/c2gw7fy2j4/3
