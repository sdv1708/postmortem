# Expected reasoning — the depth bar for `search-pool-cascade`

This is the standard a **good** run must meet on this scenario. Use it to judge the
agent's output and to tune the role prompts when the output is "too basic." The
machine-checkable version of these expectations lives in
[`scenario/scenario.yaml`](scenario/scenario.yaml) under `causal_evaluation`; this
file is the human-readable rationale behind it.

## The one idea this scenario tests: layered causation

A shallow run finds *a* cause and stops. A deep run separates three layers and says
how it knows each one:

| Layer | This incident | Why it matters |
|---|---|---|
| **Failure mechanism** | The fixed 20-connection pool exhausted; held connections → timeouts → 503s | This is what actually broke. Fixing only the trigger leaves it fragile. |
| **Trigger** | `faceted_search_v2` flag (14:02) added an unindexed `brand.keyword` aggregation, holding each connection ~8x longer | The thing that *started* it. Correlated recovery on flag-disable is the strongest single signal. |
| **Amplifying conditions** | No-backoff retry storm (3.1x) + flash-sale traffic (~3x) | Made it worse/faster, but neither alone exhausts the pool. |

If a run collapses these into a single "root cause" (e.g. "the feature flag caused
the outage") it is **too basic** — that is the failure this scenario is designed to
expose.

## What a good run must do

1. **Reconstruct a precise timeline** anchored to evidence lines, and use ordering as
   an argument (the flag flips at 14:02, *after* the 14:00 deploy; 503s persist
   *through* the rollback).
2. **Assign causal roles**, not just a ranked list: exactly one failure mechanism
   (`pool-exhaustion`), one trigger (`facet-query-flag`), and the amplifiers
   (`retry-storm`, `traffic-surge`).
3. **Reject the three red herrings with specific counter-evidence**, not by ignoring
   them:
   - *Deploy regression* → flag shipped OFF ([deploy-log.md:5](scenario/evidence/deploy-log.md)); flag enabled by a separate job 2 min later ([feature-flags-audit.md:2](scenario/evidence/feature-flags-audit.md)); rollback didn't help ([oncall-slack.md:3](scenario/evidence/oncall-slack.md)).
   - *Traffic surge alone* → higher-traffic prior sale ran clean ([traffic-metrics.log:5](scenario/evidence/traffic-metrics.log)).
   - *Elasticsearch fault* → cluster green, normal CPU ([dependency-health.md:2](scenario/evidence/dependency-health.md)).
4. **Ground every claim** in exact `source_name` + line range. No line = it must be
   marked an assumption, not stated as fact.
5. **State the evidence gaps honestly** (pool size inferred, no hold-time metric, the
   rollout-guardrail cause unknown) instead of papering over them with confidence.
6. **Propose remediation per layer** — trigger (index the field, gate/stage the
   flag), mechanism (right-size + bulkhead + acquisition timeout), amplifiers
   (backoff + circuit breaker), process (fix the rollout guardrail). Remediation that
   only addresses the flag is shallow.

## Shallow vs deep (what to tune toward)

**Too basic (reject):**
> "The outage was caused by the feature flag `faceted_search_v2`. Disabling it fixed
> it. Recommendation: be careful with feature flags."

Single cause, no mechanism, no rejected alternatives, no evidence gaps, generic fix.

**Deep (target):**
> "Failure mechanism: 20-connection pool exhaustion (search-api.log:5). Trigger: the
> flag's unindexed facet aggregation holding connections ~8x longer
> (feature-flags-audit.md:4–5, es-slow-query.log:1–4); confirmed by recovery on
> flag-disable (search-api.log:8–10). Amplifiers: retry storm (search-api.log:6) and
> flash-sale traffic (traffic-metrics.log:2), though the prior week's larger sale
> (traffic-metrics.log:5) shows traffic alone is insufficient. Deploy and ES-fault
> hypotheses rejected (deploy-log.md:5, dependency-health.md:2–3). Gaps: pool size
> inferred, no hold-time metric. Fix each layer: index the facet, bulkhead the pool,
> add backoff/circuit-breaker, and repair the rollout guardrail."

## Grading checklist

- [ ] Distinguishes mechanism / trigger / amplifiers (not one flat "root cause").
- [ ] Exactly one failure mechanism named.
- [ ] All three red herrings surfaced **and** rejected with cited counter-evidence.
- [ ] Every factual claim cites a real evidence line; assumptions labelled.
- [ ] Names the three evidence gaps.
- [ ] Remediation addresses every causal layer, each tied to evidence.
- [ ] Makes none of the `unacceptable_overclaims` in the manifest.

## Where to tune if runs fall short

The depth comes from the role prompts, not new code. If output is shallow, adjust:
- **`backend/postmortem/rca.py`** — the builder system prompt: demand explicit
  causal-role assignment and per-layer remediation, not a flat ranked list.
- **`backend/postmortem/falsification.py`** — push the falsifier to attack the
  *strongest* hypothesis and to surface rejected alternatives with counter-evidence.
- **`backend/postmortem/incident_facts.py`** — keep impact claims concrete and cited.
- **`backend/postmortem/drafting.py`** — ensure the composed postmortem carries the
  mechanism/trigger/amplifier structure through to the document.

Re-run this scenario after each prompt change and compare against
[`scenario/ground_truth_postmortem.md`](scenario/ground_truth_postmortem.md) and the
golden outputs in [`scenario/replay/`](scenario/replay).
