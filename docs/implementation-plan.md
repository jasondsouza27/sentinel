# Sentinel Phase 0 implementation plan

This is the historical prototype plan. The user subsequently selected a year-long scope with balanced ML research and application development. See the proposed [year-long design](superpowers/specs/2026-10-05-sentinel-year-long-design.md) and [first ML subsystem specification](superpowers/specs/2026-10-05-sentinel-ml-foundation-design.md); those drafts do not mean the new components are implemented.

This plan implements the user-approved general safety assistant. The workspace was empty at the start, so the project uses Python's standard library for the API, storage, analysis, training, and evaluation. A static web client and a Chrome extension share the API.

1. Define and test analysis of submitted messages, URLs, context, and supplied profile facts. Preserve separate fraud, harmful-content, and profile assessments. Never turn absent reputation data into a safe verdict.
2. Add optional local case storage, feedback, deletion, and JSON report export. Test persistence and deletion.
3. Add a paired-data research pipeline for message-only, URL-only, and combined classifiers, with domain and near-duplicate grouping, held-out metrics, and a deployable model file. Test leakage prevention and model serialization.
4. Expose a local API and web UI. Add an explicit-click Chrome extension that submits selected text or a link to the same API. Test API behavior and inspect browser use.
5. Prepare a revised editable college presentation and document dataset, evaluation, and pilot procedures. Verify all deliverables without claiming unrun studies or unavailable datasets.

The release is an operational prototype. Training data collection, measured research results, and a voluntary user pilot remain future activities until carried out by the team.
