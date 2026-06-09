# Postmortem (ground truth): Checkout failures from a degraded payments provider

> Human-authored reference for evaluation (ADR 0006 / 0010), not generated output.

## Summary
On 2026-03-12, checkout returned 502 errors to roughly 31% of requests between
09:06 and 09:16 UTC. The payments provider began returning 504s on charge.create
at 09:05; our circuit breaker opened at 09:07 and traffic recovered as the
provider's circuit closed at 09:16, matching their status-page incident window.

## Impact
- Severity sev2; ~10 minutes of elevated checkout failures across all regions.

## Timeline
- 09:04 — provider posts elevated error rates on the charge API.
- 09:05 — provider charge.create latency climbs; 504s begin.
- 09:06–09:07 — checkout 502s spike to 31%; our circuit breaker opens.
- 09:14–09:16 — provider recovers; checkout error rate returns to baseline.

## Root cause (honest assessment)
The upstream payments provider degradation is the well-supported trigger: the
provider's 504s and status-page incident precede and bound our 502 spike, and
recovery tracked the provider rather than any change on our side. A contributing
factor is the lack of retry/backoff on charge.create, which turned a transient
provider blip into user-visible failures — supporting, but not the root cause. A
local deploy regression is unsupported: no deploy occurred in the window.

## Remediation
- Add idempotent retries with jittered backoff and a fallback on charge.create.
- Alert on provider circuit-breaker state transitions.
- Track third-party status feeds alongside our own error rates.

## Lessons learned
- A dependency outage and a resilience gap can both be true; keep them distinct.
- Recovery that tracks an upstream provider is strong evidence for causation.
