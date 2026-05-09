# Sensitive by Default Without Enterprise Compliance Claims

The MVP treats uploaded and pasted incident evidence as Sensitive Evidence. Hosted or demo deployments require a Single-User Gate, no public sharing links, synthetic data for public demos, and a clear boundary that evidence is sent only to the configured LLM provider.

The MVP does not claim enterprise compliance, secrets redaction, or readiness for arbitrary production logs in a company environment. Logs may include prompts and raw model responses for debugging, but the architecture should leave room to disable or redact them later.
