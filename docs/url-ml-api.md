# Optional URL model API

**Research-only:** url-v1 failed staged benign documentation-link checks because legitimate source URLs cover only www HTTPS homepages with empty paths. Do not use its numerical output as live confidence. See the [final model card](../output/research/url-ml-v1/model-card.md). It remains disabled in the normal launcher.

For research testing, run the existing local app with its ML interpreter and a locally trusted artifact directory:

```powershell
.venv-ml\Scripts\python.exe -m sentinel.server --url-model models/url-ml/url-v1
```

Alternatively set `SENTINEL_URL_MODEL_PATH` to that directory. The legacy `--model` JSON option still refers to the separate paired-message Naive Bayes prototype.

When configured, `/api/health` adds `url_model` with state, model version and an unavailable reason. `/api/analyze` and saved case results add `url_assessment` containing state (`complete`, `not_assessed`, `unavailable`), decision (`phishing_flag`, `not_flagged` or null), model version, observed evidence, uncertainty, unavailable checks and recommended action. Probability is omitted when calibration is unavailable. A numerical probability, when present, applies to the historical benchmark distribution.

The new model assesses only the explicit `url` field. If a message contains links but `url` is absent, existing rules still analyse their usual first link and the URL model reports that no explicit URL was supplied. It never chooses a message link silently. Harm, profile and existing fraud-rule results remain separate. One inference at a time is accepted; a busy model returns retry guidance.

Analysing does not save content. Explicitly saved/exported cases retain the model version in their result, and deletion remains available. The default app needs no ML dependencies; an unavailable optional artifact does not prevent it from serving. Current web/extension rendering remains Phase 0; standalone prediction and this API expose the learned model in this milestone.
