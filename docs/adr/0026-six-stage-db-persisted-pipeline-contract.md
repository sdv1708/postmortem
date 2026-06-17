# Six-Stage DB-Persisted Pipeline Contract

> **Partially superseded by ADR 0033.** Stage two is now "extracting incident facts" and stage three is "analyzing causal hypotheses"; Impact Claims are produced in stage two and owned by the Analysis Run, not generated inside the RCA hypothesis stage. The six-stage ceiling and the DB-persisted stage-handoff contract below still hold.

The MVP Analysis Run pipeline has six status-page stages: normalizing evidence, extracting timeline candidates, generating RCA hypotheses, verifying citations, drafting postmortem, and flagging unsupported claims. Six stages is the status-page ceiling; impact analysis and remediation generation live inside the RCA hypothesis stage rather than becoming separate visible stages.

Stages one through three may introduce factual incident claims. Stages four through six may verify, annotate, or compose existing claims, but after citation verification no stage may introduce new factual claims about the incident. Each stage must persist its outputs to the database before the next stage starts, so intermediate state is inspectable by the status page, evaluation harness, and future resumability logic.
