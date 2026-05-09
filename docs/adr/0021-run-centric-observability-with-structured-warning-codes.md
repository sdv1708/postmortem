# Run-Centric Observability With Structured Warning Codes

MVP observability will center on Analysis Runs. Each run should emit structured Run Stage Events with stage name, status, timestamps, duration, model or token usage when available, and controlled Warning Codes such as `uncited_claim`, `verifier_disagreement`, or `chunk_count_anomaly`.

Run Stage Events remain queryable for the status page and evaluation harness. Full LLM prompts, raw responses, stack traces, and detailed debugging context belong in logs keyed by run_id, not in the structured event table.
