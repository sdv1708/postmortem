# Postmortem (ground truth): Search 503s during a flash sale from connection-pool exhaustion

> Human-authored reference for evaluation and tuning, not generated output.

## Summary
On 2026-05-14, search returned 503s for ~45 minutes during a flash sale (peak 41%
error rate). At 14:02 an automated rollout enabled the `faceted_search_v2` flag,
which added an **unindexed `brand.keyword` aggregation to every search query**,
holding each database connection roughly 8x longer. The fixed 20-connection pool
saturated under flash-sale concurrency and a no-backoff retry storm. Disabling the
flag at 14:41 drained the pool and search recovered by 14:48.

## Impact
- Severity sev2; ~45 minutes of degraded/failed search during a revenue event.
- Peak 41% of search requests returned 503; p95 latency ~220ms → ~900ms.

## Timeline
- 14:00 — deploy v4.7.1 starts (ships facet code with the flag OFF).
- 14:02 — automated rollout enables `faceted_search_v2` at 100% (staged steps skipped).
- 14:03 — unindexed facet aggregations begin (2–4s each); p95 latency climbs.
- 14:05–14:20 — pool saturates (active=20/20, waiting up to 240); retries reach 3.1x.
- 14:16 — deploy rollback attempted; 503s continue (deploy is not the trigger).
- 14:41 — operator disables the flag; pool drains.
- 14:48 — full recovery.

## Root cause (layered — mechanism, trigger, amplifiers)
- **Failure mechanism:** exhaustion of the fixed 20-connection database pool; once
  every connection was held by a slow query, new searches timed out and 503'd.
- **Trigger:** the `faceted_search_v2` flag (enabled 14:02) added an unindexed
  `brand.keyword` aggregation, making each query hold a connection ~8x longer. The
  correlated recovery on flag-disable is strong evidence for this trigger.
- **Amplifying conditions:** (1) a no-backoff client retry storm (3.1x) multiplied
  effective load; (2) flash-sale traffic (~3x baseline) raised concurrency.

## Alternatives considered and rejected
- **Deploy regression:** the deploy shipped the flag OFF, the flag flipped 2 minutes
  later via a separate job, and a rollback did not stop the 503s.
- **Traffic surge alone:** a higher-traffic sale the prior week (3200 rps) ran with
  zero errors, so traffic is an amplifier, not the cause.
- **Elasticsearch/hardware fault:** the cluster stayed green with normal CPU/heap
  and no restarts throughout.

## Evidence gaps (stated honestly)
- The pool maximum is inferred from `active=20/20`, not read from configuration.
- No per-query connection-hold-time metric directly quantifies the ~8x claim.
- The misconfigured rollout guardrail that skipped the staged 5%/25% steps is noted
  but its own cause is not captured.

## Remediation (targeting each causal layer)
- **Trigger:** index the `brand.keyword` facet (eager_global_ordinals) and gate any
  flag that changes the query path behind a load test; enforce staged rollout.
- **Mechanism:** right-size and bulkhead the connection pool with a short
  acquisition timeout so a slow path degrades gracefully instead of exhausting it.
- **Amplifiers:** add exponential backoff with jitter and a circuit breaker so
  retries shed load; add load-shedding for search during sale events.
- **Process:** fix the rollout guardrail so 100% flips cannot skip staged steps;
  correlate flag changes (not just deploys) on the incident dashboard.

## Lessons learned
- Feature flags that change the query path are deploys and need the same review,
  staging, and observability.
- Distinguish the mechanism from its trigger and amplifiers: fixing only the trigger
  (the flag) leaves the pool fragile for the next slow query path.
- A correlated single-lever recovery (flag off → recovery) is strong evidence for
  the trigger, but not for the full mechanism.
