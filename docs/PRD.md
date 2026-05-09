# Postmortem Agent MVP PRD

## Problem Statement

Startup backend engineers, technical founders, and small engineering teams need to write incident postmortems from scattered production evidence: logs, stack traces, deployment notes, and human incident notes. Today that work is slow, memory-heavy, and often happens after the team has lost the context needed to reconstruct an accurate timeline.

The core failure mode is trust. A generated postmortem that sounds confident but cannot be traced back to source evidence is not useful to technical teams. The MVP must prove that the system is an evidence review system that happens to draft the postmortem, not a postmortem text generator.

## Solution

Build a web-first Postmortem Agent MVP that lets a single user create an Incident, upload or paste line-addressable Artifacts, start an asynchronous Analysis Run, watch a demo-worthy six-stage status page, and review a structured Postmortem whose Major Claims are cited back to exact Artifact lines.

The MVP will focus on uploaded or pasted evidence. External integrations are out of scope. The canonical demo path will use an ambiguous deploy-related API error spike because it best demonstrates multiple RCA Hypotheses, supporting and contradicting evidence, and refusal to overstate what the evidence proves.

The founder-demo bar is:

**A technical founder should leave believing this is not a postmortem text generator; it is an evidence review system that happens to draft the postmortem.**

To meet that bar, the demo must show:

- A founder can paste or upload incident evidence and start an async run.
- The status page makes the six-stage analysis legible without looking fake.
- The generated Postmortem contains multiple plausible RCA Hypotheses for the deploy ambiguity scenario.
- Every Major Claim is cited, partial/unsupported, or explicitly marked as an assumption.
- Clicking a citation highlights exact Artifact lines and the cited snippet matches exactly.
- The system shows contradicting evidence, not just supporting evidence.
- Unsupported claims are separated from the authoritative narrative.
- The eval page shows deterministic citation checks and LLM judge scores across scenario fixtures.
- The architecture story is defensible: service layer, exercised swappable interfaces, no premature pgvector, no provider-switching theater.
- When evidence is genuinely insufficient, the system says so instead of producing a confident-sounding Postmortem.

## User Stories

1. As a startup backend engineer, I want to create an Incident with metadata, so that the evidence and generated analysis have a clear container.
2. As a technical founder, I want to paste incident notes, so that I can start analysis even when evidence was collected informally.
3. As a backend engineer, I want to upload logs, stack traces, and deployment notes, so that the system can analyze multiple evidence sources together.
4. As a reviewer, I want each Artifact to be line-addressable, so that citations can point to exact source lines.
5. As a reviewer, I want Artifacts used by an Analysis Run to be immutable, so that citations remain trustworthy after the run finishes.
6. As a backend engineer, I want to delete or replace evidence before analysis starts, so that mistakes can be corrected before evidence becomes immutable.
7. As a user, I want to start an Analysis Run without blocking the UI, so that long-running analysis feels natural.
8. As a user, I want to see a human-readable Run Status, so that I know whether analysis is queued, running, succeeded, or failed.
9. As a user, I want to see the current Run Stage, so that the waiting period communicates real analysis progress.
10. As a technical founder, I want the status page to show evidence normalization, timeline extraction, RCA generation, citation verification, postmortem drafting, and unsupported-claim flagging, so that the product feels like a serious analysis pipeline.
11. As a reviewer, I want generated timeline events to include normalized timestamps and original timestamp text, so that chronological sorting remains auditable.
12. As a reviewer, I want inferred timestamps to be labeled with uncertainty, so that vague human notes do not appear more precise than they are.
13. As an engineer, I want the system to generate multiple RCA Hypotheses when evidence is ambiguous, so that it does not pretend to know the answer.
14. As a reviewer, I want each RCA Hypothesis to include supporting evidence, contradicting evidence, unknowns, and validation steps, so that I can judge it like an engineer would.
15. As a reviewer, I want impact claims to be evidence-backed, so that severity and customer impact are not invented.
16. As a reviewer, I want remediation items to be tied to the hypothesis context, so that action items are concrete rather than generic.
17. As a reviewer, I want every Major Claim to have EvidenceRefs or be explicitly marked as an assumption, so that unsupported claims cannot hide inside confident prose.
18. As a reviewer, I want uncited claims to be normalized to assumptions and counted, so that the system measures citation failures without crashing the run.
19. As a reviewer, I want Citation Integrity verification, so that every EvidenceRef points to existing Artifact lines and the snippet matches exactly.
20. As a reviewer, I want Claim Support verification, so that cited evidence is classified as SUPPORTED, PARTIAL, or UNSUPPORTED.
21. As a reviewer, I want unsupported claims to remain auditable but separated from the final narrative, so that generated mistakes are visible without being treated as fact.
22. As a reviewer, I want partial claims to show caution styling and rationale, so that borderline evidence is not overstated.
23. As a technical founder, I want citation clicks to focus an Evidence Panel instead of navigating away, so that generated claims and source lines remain visible together.
24. As a reviewer, I want cited snippets to exactly match the highlighted Artifact lines, so that I can trust the citation system.
25. As a user, I want a structured Postmortem as the product source of truth, so that the UI and evals can inspect claims, citations, and verifier statuses.
26. As a user, I want Markdown Export on request, so that I can share or archive a clean Postmortem.
27. As a reviewer, I want an audit export option, so that unsupported claims and assumptions can be included for review when needed.
28. As a reviewer, I want to accept or reject hypotheses, so that human judgment can be recorded without rewriting generated claims.
29. As a reviewer, I want to add Reviewer Notes, so that human context can be captured separately from generated claims.
30. As a product builder, I want no full inline editing in MVP, so that generated output, verifier status, and evaluation remain auditable.
31. As a user, I want a single-user gate, so that hosted or demo evidence is not exposed publicly.
32. As a user, I want no public sharing links, so that Sensitive Evidence remains protected in MVP.
33. As a demo operator, I want synthetic public demo data, so that real production logs are never needed for public demos.
34. As an evaluator, I want file-based Incident Scenarios, so that the dataset is reproducible and independent of product data.
35. As an evaluator, I want a canonical deploy ambiguity scenario, so that the primary demo showcases multi-hypothesis reasoning and citations.
36. As an evaluator, I want dependency failure and configuration drift scenario fixtures, so that prompts do not overfit to the deploy case.
37. As an evaluator, I want an insufficient-evidence scenario stub, so that refusal behavior can be tested.
38. As an evaluator, I want Ground-Truth Postmortems, so that generated outputs can be compared against human-authored expectations.
39. As an evaluator, I want deterministic citation checks, so that citation validity does not depend on an LLM judge.
40. As an evaluator, I want an LLM-as-judge framework, so that semantic quality can be scored with Judge Rubrics.
41. As an evaluator, I want Warning Codes to be enum values, so that warnings can be aggregated across runs and scenarios.
42. As an evaluator, I want Evaluation Runs to record deterministic checks, judge scores, and warning counts, so that pipeline changes are measurable.
43. As an engineer, I want Analysis Runs to record Experiment Metadata, so that prompt, model, retrieval, chunking, and verifier changes can be compared.
44. As an engineer, I want one configured default LLM provider behind an LLMClient, so that MVP work does not become provider-matrix work.
45. As an engineer, I want fake or replay LLM clients for tests, so that the pipeline can be tested without live model calls.
46. As an engineer, I want strict Structured Model Outputs, so that LLM output must validate before becoming pipeline state.
47. As an engineer, I want invalid JSON or schema-invalid model output to fail the stage, so that corrupt pipeline state is not persisted.
48. As an engineer, I want at most one retry for a failed stage, so that transient model/API failures can recover without building a full retry system.
49. As an engineer, I want previous Pipeline Stage Outputs to persist after failure, so that failed runs are inspectable.
50. As an engineer, I want stages to communicate through the database, so that intermediate state can drive status, evals, and future resumability.
51. As an engineer, I want no stage after citation verification to introduce new factual claims, so that the citation contract remains enforceable.
52. As an engineer, I want source-type-aware line-window chunking with 15% overlap, so that boundary events are less likely to be missed.
53. As an engineer, I want EvidenceRefs to point to Artifact line ranges rather than Chunk IDs, so that citations remain stable when chunking changes.
54. As an engineer, I want deterministic retrieval before vector retrieval, so that citation correctness is proven before adding pgvector.
55. As an engineer, I want RetrievalStrategy to be swappable, so that pgvector can be added later if evals justify it.
56. As an engineer, I want canonical Artifact text stored in Postgres, so that citation verification uses the same transactional source of truth as the app.
57. As an engineer, I want Artifact Storage as a boundary, so that cloud blob storage can be introduced later.
58. As an engineer, I want relational EvidenceRefs, so that citation panel lookups, eval aggregation, and referential integrity are straightforward.
59. As an engineer, I want explicit structured tables for Timeline Events, Hypotheses, Action Items, and Postmortems, so that the schema reflects the domain.
60. As an engineer, I want a generic claims table deferred until duplication proves it useful, so that the first schema does not over-generalize.
61. As an engineer, I want workspace foreign keys as a single default Workspace stub, so that future tenancy has a boundary without MVP workspace UX.
62. As an engineer, I want resource-oriented APIs plus Command Endpoints, so that normal retrieval and side-effecting actions are clearly separated.
63. As a future CLI user, I want CLI workflows to call the same service layer as the web UI, so that Milestone 2 does not duplicate product logic.
64. As a frontend user, I want the Incident page to be the workflow hub, so that evidence, runs, and postmortem review feel connected.
65. As a frontend user, I want TanStack Query polling for run status, so that the MVP avoids SSE complexity while still showing progress.
66. As a frontend user, I do not want token-streamed postmortem text, so that no unverified prose appears before citation verification is complete.
67. As an operator, I want Run Stage Events to be queryable, so that the status page and eval harness can inspect structured progress.
68. As an operator, I want full prompts and raw model responses in run-keyed logs only, so that events stay queryable and logs stay debuggable.
69. As an operator, I want prompts/raw responses to be easy to redact or disable later, so that the MVP does not block future privacy hardening.
70. As a technical founder, I want the system to admit insufficient evidence, so that I trust its confident claims more when they do appear.

## Implementation Decisions

### Product Surface

- The MVP is web UI first. CLI is deferred to Milestone 2 as a thin wrapper over the same service layer.
- The frontend stack is Next.js, TypeScript, Tailwind, shadcn/ui, and TanStack Query.
- The Review Surface is the primary user experience: users review generated Postmortems and trace Major Claims back to source evidence.
- Citation clicks focus an Evidence Panel with highlighted lines rather than navigating away from the Postmortem.
- The status page is part of the founder demo surface, not just backend feedback.
- Polling is the MVP status-update mechanism. SSE/live updates are deferred.
- Token streaming is out of scope because visible prose should not appear before citations are verified.

### Backend and Service Architecture

- FastAPI, Pydantic, SQLAlchemy, and Postgres are the preferred MVP backend stack.
- Routes and the future CLI call into a shared service layer rather than duplicating orchestration logic.
- Analysis Runs are asynchronous at the product/API level: clients create a run, poll Run Status, and fetch results later.
- Python `asyncio` is not implied by the async product contract. Worker execution may be synchronous internally.
- The MVP may use an in-process background executor, but the API/domain model should already behave like durable async runs.
- A stage may retry at most once after failure.
- Previous persisted stage outputs remain inspectable after a failed run.

### Eight Kept Interfaces

The MVP keeps explicit interfaces only where the boundary is exercised by the MVP pipeline or near-term experiments:

1. `AnalysisService`
2. `LLMClient`
3. `ChunkingStrategy`
4. `RetrievalStrategy`
5. `ClaimVerifier`
6. `PostmortemRenderer`
7. `RunExecutor`
8. `EvaluationRunner`

Swappability must be demonstrated through fakes, replay implementations, or alternate implementations in tests. Embedding model, vector store, and orchestration-framework abstractions are deferred until those concerns enter the working product path.

### Six Pipeline Stages

The MVP status page has exactly six stages:

1. **Normalizing evidence**
   - Parses source types.
   - Extracts timestamps where present.
   - Line-indexes Artifacts.
   - Produces canonicalized Artifacts.

2. **Extracting timeline candidates**
   - Identifies time-anchored events with citations.
   - Produces `TimelineEvent[]`.

3. **Generating RCA hypotheses**
   - Produces ranked RCA Hypotheses with supporting evidence, contradicting evidence, and unknowns.
   - Owns impact analysis as `ImpactClaim[]`.
   - Owns remediation generation as `RemediationItem[]`.
   - Produces `Hypothesis[]`, `ImpactClaim[]`, and `RemediationItem[]`.

4. **Verifying citations**
   - Checks every EvidenceRef from stages 2 and 3.
   - Tags each claim/citation as SUPPORTED, PARTIAL, or UNSUPPORTED.
   - Emits verification results and Warning Codes.
   - Does not generate new claims.

5. **Drafting postmortem**
   - Composes the document from verified structured outputs.
   - May render Markdown.
   - Does not introduce new factual claims.

6. **Flagging unsupported claims**
   - Annotates unsupported or missing-citation output.
   - Marks missing-support Major Claims as assumptions.
   - Emits evaluation warnings.
   - Produces the final Postmortem state.

Stages 1-3 may introduce factual incident claims. Stages 4-6 may audit, annotate, or compose existing claims, but after stage 4 no stage may introduce a new factual claim about the Incident.

Each stage persists its output to the database before the next stage starts. Stages communicate through persisted Pipeline Stage Outputs, not in-memory handoff.

### Citation Contract

- A working citation includes `artifact_id`, `source_name`, `line_start`, `line_end`, `snippet`, `confidence_score`, and verifier status.
- A citation is working only if it jumps to immutable Artifact lines and the displayed snippet exactly matches the stored lines.
- EvidenceRefs point to Artifact line ranges, not Chunk IDs.
- Artifact bodies become immutable once included in an Analysis Run.
- Every Major Claim requires EvidenceRefs or `assumption=true`.
- If an LLM emits a Major Claim with neither EvidenceRefs nor an assumption marker, the system normalizes it to `assumption=true`, logs a warning, and counts an `uncited_claim` metric.
- Uncited claims do not fail the run and do not trigger retry.
- Unsupported claims remain auditable as Review Findings but are not presented as authoritative narrative.

### Verification

- Verification is split into two passes:
  - `CitationIntegrityVerifier`: deterministic checks for Artifact existence, line range existence, and exact snippet match.
  - `ClaimSupportVerifier`: semantic judgment of whether cited evidence supports the Major Claim.
- Claim Support statuses are SUPPORTED, PARTIAL, and UNSUPPORTED.
- LLM judges are not the source of truth for citation validity.

### Output Model

- Structured Postmortem data is the source of truth.
- Markdown is rendered on request as an export artifact and is not parsed back into product truth.
- Full inline editing of generated claims is out of scope for MVP.
- Users may accept/reject hypotheses and add Reviewer Notes.
- Review/audit exports may include unsupported claims and assumptions; clean exports should not present unsupported claims as final facts.

### Scenarios and Dataset

The dataset architecture uses file-based fixtures:

- `scenario.yaml`
- `evidence/`
- `ground_truth_postmortem.md`

The three scenario families supported from day one are:

1. **Deploy API error spike**
   - Canonical MVP demo scenario.
   - End-to-end in the Review Surface.
   - Demonstrates deploy ambiguity, multiple hypotheses, supporting and contradicting evidence, and citation traceability.

2. **Dependency failure with ambiguity**
   - Upstream API or DB outage.
   - Tests evidence-from-context where logs are noisy and human notes are critical.
   - Evidence files and Ground-Truth Postmortem exist, but it is not the primary polished demo path.

3. **Configuration drift slow-burn**
   - No clear trigger.
   - Tests timeline construction from scattered signals.
   - Evidence files and Ground-Truth Postmortem exist, but it is not the primary polished demo path.

The evaluation suite should also include at least one Insufficient Evidence Scenario stub where evidence is too sparse, too contradictory, or lacks time anchors. This tests refusal behavior even if it is not part of the polished MVP demo path.

### Retrieval and Chunking

- No pgvector dependency is required for the first MVP path.
- Deterministic retrieval is used first through a `RetrievalStrategy` interface.
- Candidate retrieval may use keyword, time-window, and source-type strategies.
- pgvector/vector retrieval is deferred until evaluations show deterministic retrieval is insufficient.
- Chunking is source-type-aware line-window chunking with 15% overlap.
- Logs use timestamp-aware windows.
- Stack traces stay together when possible.
- Human notes preserve paragraph or heading boundaries.
- Deploy notes generally stay as small release-entry chunks.
- Chunking strategy is versioned in Experiment Metadata.

### Model Provider and Prompting

- The MVP uses one configured default LLM provider behind `LLMClient`.
- There is no provider picker in the UI.
- Fake or replay LLM clients support tests.
- Analysis Runs and Evaluation Runs record provider, model name, and Prompt Version.
- LLM judge configuration may diverge from generation configuration later, but both use explicit metadata.
- Claim-generating and verifier stages require strict JSON schemas.
- Invalid JSON or schema-invalid Structured Model Output fails the stage.
- Schema-valid output with missing claim support fields is normalized and measured.

### Observability and Experiment Tracking

- Every log line includes `run_id`.
- Run Stage Events store structured summary fields:
  - stage
  - status
  - timestamps
  - duration
  - model/token usage when available
  - Warning Codes
- Full prompts, raw LLM responses, stack traces, and detailed debugging context belong in logs keyed by `run_id`.
- Warning Codes are enum values, not free text. Examples include `uncited_claim`, `verifier_disagreement`, and `chunk_count_anomaly`.
- Experiment Metadata is stored on Analysis Runs and Evaluation Runs:
  - pipeline version
  - Prompt Version
  - model/provider
  - Retrieval Strategy
  - Chunking Strategy
  - verifier version
  - scenario id
  - deterministic check results
  - judge rubric scores
  - Warning Code counts
- MVP experiment tracking is not a user-facing A/B platform.

### API Shape

The API uses resource-oriented endpoints plus explicit Command Endpoints for side effects.

Resource-oriented examples:

- Create and fetch Incidents.
- Upload/paste and fetch Artifacts.
- Fetch Analysis Runs.
- Fetch Run Stage Events.
- Fetch Postmortems.

Command examples:

- Start an Analysis Run.
- Record hypothesis review.
- Add Reviewer Notes.
- Render Markdown Export.

Starting analysis is a command because it creates a long-running run with side effects.

### Frontend Workflow

The Incident is the workflow hub:

- Incident list.
- Incident creation.
- Incident overview.
- Evidence management.
- Run status.
- Postmortem review.
- Internal evaluation dashboard.

The evaluation dashboard is internal/dev-oriented and may be gated or hidden from normal navigation.

### Schema Surface

The minimum MVP database schema surface is:

- `workspaces`
- `incidents`
- `artifacts`
- `artifact_lines` or canonical artifact text with line-index support
- `analysis_runs`
- `run_stage_events`
- `postmortems`
- `timeline_events`
- `hypotheses`
- `impact_claims`
- `action_items`
- `evidence_refs`
- `reviewer_notes`
- `evaluation_runs`
- `evaluation_results`

Schema decisions:

- `evidence_refs` are relational, not JSON-only.
- Explicit domain tables are preferred for structured outputs.
- A generic `claims` table is deferred until duplication proves it useful.
- A single default Workspace stub may exist through foreign keys, but there is no workspace switching, workspace-aware auth, or workspace management UI in MVP.
- JSON snapshots may exist for raw model output and verifier rationales, but they are not the citation source of truth.

### Storage

- Canonical line-addressable Artifact text is stored in Postgres for MVP.
- Blob/filesystem/cloud storage is deferred but represented through an Artifact Storage boundary.
- Evidence corrections after analysis create a new Artifact and new Analysis Run rather than mutating used Artifacts.

### Security and Privacy

- MVP evidence is Sensitive Evidence by default.
- Hosted/demo deployments require a Single-User Gate.
- There are no public sharing links.
- External integrations are out of scope.
- Evidence is sent only to the configured LLM provider.
- The UI should make the external model boundary clear.
- Public demos use synthetic data.
- Enterprise compliance, secrets redaction, and arbitrary-production-log readiness are not claimed in MVP.

## Testing Decisions

- Tests should focus on external behavior and domain contracts rather than implementation details.
- The highest-priority test category is citation trust: line existence, exact snippet match, immutable Artifact behavior, and EvidenceRef referential integrity.
- `CitationIntegrityVerifier` gets deterministic unit tests with positive, missing-artifact, missing-line, and mismatched-snippet cases.
- `ClaimSupportVerifier` gets tests with fake/replay LLM clients and rubric fixtures.
- `AnalysisService` gets integration-style tests that create an Incident, attach Artifacts, start an Analysis Run, and inspect persisted stage outputs.
- `RunExecutor` gets tests for stage ordering, one retry, failure persistence, and non-fatal Warning Codes.
- `ChunkingStrategy` gets source-type fixture tests, including the 15% overlap rule and stack-trace preservation.
- `RetrievalStrategy` gets deterministic fixture tests for keyword, time-window, and source-type retrieval.
- `PostmortemRenderer` gets tests proving Markdown Export is rendered from structured Postmortem data and does not introduce new factual claims.
- `EvaluationRunner` gets tests for deterministic checks, LLM judge rubric wiring, Warning Code aggregation, and scenario loading.
- API tests should verify resource endpoints and Command Endpoints from a client perspective.
- Frontend tests should cover the review workflow: status polling, citation click to Evidence Panel, unsupported-claim separation, and Markdown Export command.
- Scenario fixture tests should validate that each Scenario Manifest references existing evidence files and Ground-Truth Postmortems.
- Evaluation tests should include the canonical deploy scenario, dependency ambiguity, configuration drift, and an Insufficient Evidence Scenario stub.

## Out of Scope

- CLI workflows, except as a Milestone 2 wrapper over the service layer.
- pgvector/vector retrieval unless deterministic retrieval fails eval cases and the scope is reopened.
- External integrations such as GitHub, Slack, Sentry, Datadog, Grafana, PagerDuty, Linear, or Jira.
- Production remediation or autonomous infrastructure changes.
- Full observability platform or dashboards beyond run-centric logs/events needed for status and evals.
- Enterprise RBAC.
- Workspace switching, workspace management UI, or workspace-aware auth.
- Public sharing links.
- Full inline editing of generated claims.
- Rich collaborative document editing.
- SSE/live updates.
- Token streaming for generated postmortem text.
- Cloud blob storage as primary Artifact storage.
- Secrets redaction.
- Multiple user-facing postmortem templates.
- Provider switching UI.
- Full queue backend replacement unless needed for deployment.
- Enterprise compliance claims.

## Further Notes

Canonical decisions from the grilling session:

- Web UI is the primary MVP; CLI is Milestone 2.
- Async means API/product lifecycle with status polling, not necessarily Python `asyncio`.
- The status page is demo-critical.
- The MVP does not stream LLM output.
- The canonical demo scenario is an ambiguous deploy-related API error spike.
- The dataset uses file-based scenario fixtures.
- pgvector is deferred.
- Swappability is kept only for exercised MVP boundaries.
- Deterministic eval checks are the trust floor.
- LLM-as-judge exists from the start for semantic scoring, not citation validity.
- One default LLM provider is used behind `LLMClient`.
- Structured Postmortem data is source of truth; Markdown is rendered on request.
- Major Claims require EvidenceRefs or assumption markers.
- Uncited Major Claims are normalized to assumptions and counted as metrics.
- Citation integrity and claim support are separate verifier passes.
- Unsupported claims remain auditable but not authoritative.
- Review annotations are in scope; full inline editing is out.
- Single-user gate is the MVP auth posture.
- Used Artifacts are immutable.
- Timestamps normalize to UTC while preserving original text.
- Canonical Artifact text is stored in Postgres, with a future Artifact Storage boundary.
- Run Stage Events are queryable; raw prompts/responses belong in logs.
- Warning Codes are enums.
- APIs are resource-oriented with explicit Command Endpoints.
- Frontend workflow is Incident-centered.
- EvidenceRefs are relational.
- Workspace is a stub, not an MVP product feature.
- Experiment tracking is run/eval metadata, not an A/B platform.
- The six-stage pipeline is the status-page ceiling.
- Stages communicate through persisted database state.
- Source-type-aware line-window chunking uses 15% overlap.
- Strict JSON schemas are required for LLM outputs.
- Failed stages get at most one retry.
- Sensitive evidence is treated carefully, but enterprise compliance is not claimed.
