# Milestone 1 MVP Boundary

Milestone 1 is the first functional MVP that proves evidence-backed postmortem generation through the web Review Surface. It includes incident CRUD, artifact upload/paste, Postgres-backed canonical artifact text, async Analysis Runs with polling, the six-stage pipeline, strict structured LLM outputs, one default LLM provider, deterministic retrieval, citation verification, structured postmortem data, an Evidence Panel, review annotations, Markdown export, three file-based synthetic scenarios, evaluation runs, experiment metadata, and run-centric observability.

Milestone 2 contains the CLI wrapper, vector retrieval if evals justify it, external integrations, richer editing and provenance, SSE/live updates, cloud blob storage, multi-user workspace UX, secrets redaction, multiple templates, and queue backend replacement. These should not leak into Milestone 1 unless the scope is deliberately reopened.
