# Postmortem (ground truth): Ambiguous deploy-related API error spike

> Human-authored reference for the canonical demo scenario. This is evaluation
> material (ADR 0006 / 0010), not generated product output. It states what a
> careful engineer would conclude after reviewing the same evidence.

## Summary
On 2026-05-09, the api-gateway HTTP 500 rate spiked from baseline to 22% on
checkout and cart endpoints between 14:32 and 14:41, roughly two minutes after
the v184 rollout completed at 14:28. The primary database connection pool
saturated at its 40-connection limit with multi-second acquisition waits. An
operator raised the pool limit to 80 at 14:40 and error rates returned to
baseline by 14:45.

## Severity & impact
- Severity: sev2.
- ~13 minutes of elevated errors, peaking at 22% of requests on checkout/cart.

## Timeline
- 14:28 — v184 rollout reaches the api-gateway fleet (canary skipped).
- 14:31 — connection acquisition waits climb to ~1.2s; pending acquisitions grow.
- 14:32 — HTTP 500 rate begins climbing.
- 14:33 — cache node cache-2 evicts under memory pressure; 500 rate hits 22%.
- 14:40 — operator resizes the pool from 40 to 80 connections.
- 14:41–14:45 — error rate falls and returns to the 0.2% baseline.

## Root cause (honest assessment)
The evidence is genuinely ambiguous and does not isolate a single root cause.
Two hypotheses are well supported and one is unsupported:

1. **Deploy v184 pool-acquisition refactor (most likely).** The refactor shipped
   minutes before saturation, and ORM/pool-acquisition changes are a plausible
   regression path. Caveat: max_connections was unchanged and no migration shipped.
2. **Pool capacity limit (plausible, correlation only).** The pool saturated at
   40 and the resize to 80 resolved the incident — but resolution does not prove
   the trigger, and capacity alone does not explain the timing relative to v184.
3. **Upstream dependency degradation (not supported).** Suspected but unevidenced;
   no upstream incident was found, though not every dependency was checked.

A code diff of v183..v184 connection pool acquisition plus a before/after load
comparison is needed to choose between (1) and (2).

## Remediation
- Roll back to v183 and re-test the pool acquisition refactor behind a canary.
- Size pool max_connections from measured concurrency and alert on pending waits.
- Restore canary gating so a full rollout cannot skip staged validation.

## Lessons learned
- A change that resolves an incident is not proof of the original trigger.
- Concurrent signals (deploy + cache eviction + pool saturation) must be kept as
  competing hypotheses until one is confirmed.
