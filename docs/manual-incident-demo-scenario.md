# Manual Incident Demo Scenario

This document gives you a realistic from-scratch incident to enter through the
Postmortem Agent UI. It is designed for demos where you want the app to look
credible: multiple evidence types, plausible timestamps, contradictory signals,
an ambiguous root cause, and a review workflow with citations.

## Goal

Create an incident manually, paste in the evidence artifacts under
`docs/demo-evidence/checkout-timeout/`, start an analysis run, and review the
generated timeline, hypotheses, citations, and postmortem.

The scenario intentionally has two plausible causes:

- a checkout-api deploy changed payment authorization behavior;
- the PayLink provider had subset latency for this merchant path.

The credible conclusion should be nuanced: the provider latency was likely the
external trigger, while the checkout deploy amplified it by making payment auth
synchronous and adding retries.

## Prerequisites

1. Backend is running against Neon or local Postgres.
2. Frontend is running and can reach the backend.
3. Your frontend token matches `POSTMORTEM_API_TOKEN`.
4. For live RCA generation, set `POSTMORTEM_LLM_API_KEY`.

If no LLM key is configured, the app can still store evidence and extract a
timeline, but RCA hypotheses will be empty because the backend uses the offline
LLM client.

## Start The App

Backend:

```powershell
cd D:\postmortem\backend
.\.venv\Scripts\uvicorn.exe postmortem.app:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd D:\postmortem\frontend
npm run dev
```

Open:

```text
http://localhost:3000/incidents
```

## Create The Incident

Click **New incident** and use these fields:

```text
Title: Checkout timeout spike during payment authorization
Severity: sev2
Summary: Customers experienced checkout timeouts after the checkout-api canary introduced synchronous payment authorization and retries during a PayLink latency window.
```

The current UI captures the incident headline, severity, and summary first. The
timeline comes from the evidence artifacts you add next.

## Add Evidence Artifacts

Use the Evidence panel to add each artifact below. Copy the full file body from
the matching path.

| Source type | Source name | File |
| --- | --- | --- |
| `incident_notes` | `incident-notes.md` | `docs/demo-evidence/checkout-timeout/incident-notes.md` |
| `logs` | `api-gateway.log` | `docs/demo-evidence/checkout-timeout/api-gateway.log` |
| `logs` | `payment-authorizer.log` | `docs/demo-evidence/checkout-timeout/payment-authorizer.log` |
| `deployment_notes` | `deploy-notes.md` | `docs/demo-evidence/checkout-timeout/deploy-notes.md` |
| `logs` | `db-metrics.log` | `docs/demo-evidence/checkout-timeout/db-metrics.log` |
| `other` | `provider-status.md` | `docs/demo-evidence/checkout-timeout/provider-status.md` |
| `incident_notes` | `slack-triage.md` | `docs/demo-evidence/checkout-timeout/slack-triage.md` |

The logs include exact ISO timestamps so the timeline stage has real anchors.
The deployment notes and Slack transcript give the RCA stage enough context to
avoid a one-note answer.

## Start Analysis

In the Analysis section, click **Start analysis run**.

Expected stage behavior:

- `normalizing_evidence`: creates source-aware chunks.
- `extracting_timeline_candidates`: extracts timestamped events.
- `generating_rca_hypotheses`: calls the configured LLM and validates strict JSON.
- `verifying_citations`: checks every citation resolves to exact artifact lines.
- `drafting_postmortem`: writes the structured postmortem.
- `flagging_unsupported_claims`: classifies claim support.

Wait until the run status is `succeeded`.

## What To Look For

Timeline should include events around:

- 14:04 canary increased to 25 percent.
- 14:06 support complaints or provider timeout begins.
- 14:11 error budget alert.
- 14:21 rollback starts.
- 14:27 latency improves.
- 14:35 recovery.

Good RCA hypotheses should mention some combination of:

- checkout-api synchronous payment authorization increased customer-visible latency;
- retry policy `max_attempts=3` amplified PayLink latency;
- PayLink subset merchant latency was an external trigger;
- database contention is less likely because DB metrics stayed normal.

Credible contradicting evidence:

- PayLink public status stayed green.
- No DB migration shipped.
- DB lock waits and commit latency stayed normal.

## Reviewer Workflow

After the run succeeds:

1. Open each hypothesis.
2. Click citation links and confirm the evidence viewer jumps to exact lines.
3. Add this Reviewer Note to the strongest hypothesis:

```text
This matches the mitigation: rollback reduced p95 latency quickly, but PayLink subset latency likely triggered the original timeout window. Follow-up should confirm merchant-specific provider metrics and whether retry amplification affected customer-visible failure rate.
```

4. Accept the best-supported hypothesis.
5. Leave weaker hypotheses as proposed, or reject only if citations clearly do
   not support them.
6. Export the clean postmortem.
7. Export the audit postmortem and confirm warnings/review findings remain visible.

## Demo Script

Use this narrative when walking someone through the app:

```text
I am creating an incident from raw production evidence rather than starting from
a prewritten postmortem. I add gateway logs, payment-authorizer logs, deployment
notes, database metrics, provider status notes, and Slack triage notes. The
system locks those artifacts into the analysis run, extracts the timeline,
generates competing root-cause hypotheses, and verifies that every citation
points back to exact immutable evidence lines.

The important part is that the model is not trusted blindly. It can propose
hypotheses, but citations are mechanically verified and unsupported claims are
flagged for review.
```

## Expected Final Read

The most defensible final explanation is:

```text
The checkout timeout spike was most likely caused by the checkout-api canary
making payment authorization synchronous and retrying up to three times during a
PayLink subset latency window. PayLink latency appears to be the external
trigger, but the deploy amplified the provider slowness into customer-visible
checkout timeouts. Database contention is unlikely based on normal lock waits,
connection counts, and commit latency.
```

That explanation is intentionally not overconfident. It separates trigger,
amplifier, and ruled-down alternatives, which makes the demo look like a real
incident review instead of a synthetic happy path.
