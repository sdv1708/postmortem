# Postmortem (ground truth): Latency spike from a drifted cache configuration

> Human-authored reference for evaluation (ADR 0006 / 0010), not generated output.

## Summary
On 2026-04-02, product-listing p99 latency reached ~5s between 22:13 and 22:30
UTC. An automated config sync (revision r512) flipped response_cache_enabled to
false at 22:10; database read QPS tripled to ~9.6k and latency recovered within
two minutes of an operator re-enabling the cache at 22:28.

## Impact
- Severity sev3; ~17 minutes of degraded product-listing latency.

## Timeline
- 22:10 — config sync r512 disables response caching.
- 22:12–22:13 — database read QPS triples; product-listing p99 hits 5s.
- 22:28 — operator re-enables the cache.
- 22:30 — latency returns to baseline.

## Root cause (honest assessment)
A configuration drift is the well-supported cause: the cache-disable change
immediately preceded the QPS spike, and re-enabling the cache resolved the
incident. An unrelated organic traffic surge is only partially supported — read
QPS rose, but edge request volume was not directly measured and the cache flip is
the more direct explanation. A code regression is unsupported: no application
deploy accompanied the change.

## Remediation
- Gate production config changes behind review and add config drift detection.
- Alert on cache hit-ratio collapse, not just downstream latency.
- Separate staging-only config edits from the production sync path.

## Lessons learned
- Config changes are deploys: they need the same review and observability.
- Correlated recovery on a single revert is strong evidence for the trigger.
