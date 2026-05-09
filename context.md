# CONTEXT.md — Postmortem Agent Domain Language

## What this system does
Takes evidence from a production incident and generates a structured postmortem.
The core output is a document a human engineer would be proud to have written —
accurate, evidence-backed, honest about uncertainty.

## Core domain concepts

### Incident
A production event with a defined start time, detection time, and resolution time.
Has a severity level and one or more affected services. The incident is the
container for everything else.

### Evidence
Raw material from the incident. Can be logs, stack traces, deployment notes,
or human-written incident notes. Evidence is untrusted — it may be incomplete,
noisy, or contradictory. The system never invents evidence.

### Artifact
A single uploaded or pasted piece of evidence. Has a source type, a source name,
and a line-addressable body. An artifact is the atomic unit of evidence storage.
Once included in an Analysis Run, an artifact's body is immutable.

### Artifact Storage
The persistence boundary for canonical artifact text and future external blob locations.

### Chunk
A slice of an artifact, sized for retrieval. Chunks preserve line numbers and
timestamps from the original artifact so citations can point back to exact lines.
MVP chunks use source-type-aware line windows with 15% overlap.

### Retrieval Strategy
The swappable approach used to select candidate chunks for a pipeline stage, such as keyword, time-window, source-type, or vector retrieval.

### Claim
An assertion the system makes about the incident — "the outage started at 14:32",
"the deploy at 14:28 triggered the error spike". Every claim must be either
supported by evidence or explicitly marked as an assumption.

### Major Claim
An incident-specific generated assertion that affects incident understanding, confidence, or follow-up work.

### EvidenceRef
The citation object attached to a claim. Contains: artifact_id, source_name,
line_start, line_end, snippet, confidence_score, and verifier status. If a claim has no EvidenceRef,
it is an assumption and must be tagged as such. A working citation must jump to immutable artifact lines and its snippet must exactly match the cited lines.

### Timeline
An ordered sequence of incident events extracted from evidence. Each event has
a normalized timestamp when available, original timestamp text, description, type, and one or more EvidenceRefs. Confidence scores
reflect how certain the system is about the timestamp and the event interpretation.

### Inferred Timestamp
A timestamp derived from relative or ambiguous evidence rather than directly parsed from a cited artifact line.

### RCA Hypothesis
A ranked candidate root cause. The system generates multiple hypotheses when
evidence is ambiguous — it does not pretend to know the answer when it doesn't.
Each hypothesis has supporting evidence, contradicting evidence, unknowns, and
suggested validation steps.

### Postmortem
The final structured incident analysis. Sections: summary, timeline, impact analysis,
root cause hypotheses, remediation items, lessons learned. Every major claim
in the postmortem links to an EvidenceRef or is explicitly marked as an assumption.

### Markdown Export
A user-requested rendering of a structured Postmortem into Markdown for sharing, copying, or archiving.

### Review Finding
A claim or verifier result that needs human attention before it should be treated as part of the final incident narrative.

### Reviewer Note
A human-authored note attached during postmortem review, separate from generated claims and their evidence requirements.

### Workspace
The ownership boundary for incidents, artifacts, analysis runs, and generated postmortems.
In the MVP this is a single default Workspace stub, not a user-facing tenancy feature.

### Single-User Gate
A minimal access boundary for the MVP that allows one authorized user into the application without team RBAC.

### Sensitive Evidence
User-provided incident material that may contain operational details, customer impact, secrets, or proprietary system behavior.

### Command Endpoint
An API endpoint that starts work or records a user decision, such as creating an Analysis Run, reviewing a hypothesis, or exporting Markdown.

### Review Surface
The human-facing experience where an engineer reviews a generated postmortem and traces its claims back to source evidence.

### Evidence Panel
The review UI region that displays line-addressable artifact text and highlights cited evidence without taking the user away from the postmortem.

### Analysis Run
A single execution of the pipeline against an incident's evidence. Has a run ID,
start time, pipeline config used, and produces all the structured outputs above.
Run IDs propagate through every log line so outputs are auditable.

### Run Status
The externally visible lifecycle state of an Analysis Run: queued, running, succeeded, or failed.

### Stage Retry
A bounded re-attempt of a failed Run Stage; the MVP allows at most one retry per stage.

### Run Stage
A human-readable phase of an Analysis Run shown in the Review Surface, such as normalizing evidence, extracting timeline candidates, verifying citations, or drafting the postmortem.

### Run Stage Event
A persisted structured summary of a Run Stage transition or outcome, including status, timestamps, duration, usage, and warning codes.

### Pipeline Stage Output
The persisted database state produced by a Run Stage before the next stage starts.

### Warning Code
A controlled enum value emitted by pipeline stages and evaluations to make warnings aggregateable across runs and scenarios.

### Pipeline
The ordered sequence of stages that transforms evidence into a postmortem.
Current stages: normalize evidence → extract timeline candidates → generate RCA hypotheses → verify citations → draft postmortem → flag unsupported claims. Six stages is the MVP status-page ceiling.

### Verifier
The component that checks whether a claim is actually supported by the evidence
it cites. Returns SUPPORTED, PARTIAL, or UNSUPPORTED. Unsupported claims are
flagged, not deleted.

### Citation Integrity Verifier
The deterministic verifier that checks whether an EvidenceRef points to existing artifact lines and whether its snippet exactly matches those lines.

### Claim Support Verifier
The semantic verifier that judges whether cited evidence supports, partially supports, or does not support a Major Claim.

### Incident Scenario
A synthetic but realistic incident case used to demonstrate, evaluate, and regression-test the analysis pipeline.

### Canonical Demo Scenario
The primary Incident Scenario shipped end-to-end in the MVP demo path: an ambiguous deploy-related API error spike.

### Milestone 1
The first functional MVP that proves evidence-backed postmortem generation through the web Review Surface.

### Milestone 2
The follow-up milestone for CLI workflows, richer retrieval, integrations, editing, cloud storage, and multi-user capabilities after the MVP proof works.

### Ground-Truth Postmortem
A human-authored expected postmortem for an Incident Scenario, used as evaluation reference material rather than generated product output.

### Insufficient Evidence Scenario
An evaluation scenario stub where evidence is too sparse, contradictory, or lacking time anchors for the system to produce a confident postmortem.

### Evaluation Run
A repeatable execution of checks against an Analysis Run or Incident Scenario to measure citation integrity, output completeness, hypothesis behavior, and semantic quality.

### Experiment Metadata
The versioned configuration recorded with Analysis Runs and Evaluation Runs so pipeline, prompt, model, retrieval, chunking, and verifier choices can be compared.

### Judge Rubric
A structured semantic scoring guide used by an LLM judge to evaluate generated postmortems against Ground-Truth Postmortems and scenario expectations.

### Uncited Claim
A Major Claim emitted without EvidenceRefs or an assumption marker, normalized to an assumption and counted as an evaluation metric.

### Scenario Manifest
A structured file that describes an Incident Scenario's metadata, evidence artifacts, ambiguity notes, expected hypothesis families, and evaluation tags.

### Swappable Component
A pipeline component with an explicit interface because the MVP uses, tests, or expects near-term experiments for alternate implementations.

### Prompt Version
The identifier for the prompt template and instructions used by an Analysis Run or Evaluation Run.

### Structured Model Output
LLM output that must conform to a stage-specific JSON schema before it can become pipeline state.

## Key distinctions

**Evidence vs Claim:** Evidence is raw source material. A claim is something
the system asserts based on evidence. Never conflate them.

**Artifact Replacement vs Artifact Mutation:** Evidence corrections are represented by creating a new Artifact, not by mutating an Artifact that has been used by an Analysis Run.

**Canonical Artifact Text vs Blob Object:** The MVP stores canonical line-addressable artifact text in Postgres. Blob or cloud object storage is a future Artifact Storage implementation for larger files or cloud deployment.

**Normalized Timestamp vs Original Timestamp Text:** Timeline events use normalized UTC timestamps for ordering when available, but preserve original timestamp text for auditability. Inferred Timestamps must be labeled with uncertainty.

**Hypothesis vs Root Cause:** The system generates hypotheses, not root causes.
A root cause is what a human engineer concludes after reviewing the hypotheses.
The system does not declare root causes.

**Assumption vs Supported Claim:** An assumption is a claim the system makes
without evidence support. It must be labeled. A supported claim has at least
one EvidenceRef with confidence > threshold.

**Major Claim vs Generic Text:** Major Claims require EvidenceRefs or an assumption marker. Section headings, UI labels, procedural wording, and generic explanatory text are not Major Claims.

**Verifier Status vs Confidence Score:** Verifier status is the categorical support judgment: SUPPORTED, PARTIAL, or UNSUPPORTED. Confidence score is a numeric signal used to explain strength, rank citations, and help reviewers triage borderline claims.

**Citation Integrity vs Claim Support:** Citation integrity is deterministic evidence address validation. Claim support is semantic judgment about whether the cited evidence actually supports the claim.

**Chunking vs Retrieval:** Chunking is how artifacts are split for storage.
Retrieval is how chunks are fetched for a specific query. They are separate
concerns with separate interfaces.

**Chunk Reference vs EvidenceRef:** Chunks are retrieval aids and may change when the Chunking Strategy changes. EvidenceRefs point to durable artifact line ranges, not chunk IDs.

**Simple Retrieval vs Vector Retrieval:** The MVP path uses simple deterministic retrieval first. Vector retrieval is a later Retrieval Strategy added when evaluation shows that keyword, time-window, and source-type retrieval are insufficient.

**Review Surface vs CLI:** The MVP Review Surface is web UI first because clickable claim-to-evidence review is the product proof point. A CLI is a future core workflow, not part of the first functional MVP.

**Postmortem Review vs Evidence Navigation:** Citation clicks should focus an Evidence Panel in the postmortem review workflow rather than navigating away from the generated postmortem.

**Asynchronous Analysis Run vs Python async:** An asynchronous Analysis Run is a product/API lifecycle where clients create a run and observe status/results later. It does not imply Python `asyncio`; worker execution can be synchronous internally.

**Run Status vs Internal Step:** Run Status is the human-visible lifecycle of an Analysis Run. Internal pipeline steps may be more granular, but the Review Surface should present progress using names engineers can understand.

**Run Stage vs Streamed Output:** A Run Stage communicates verified progress through the analysis pipeline. The MVP does not stream draft postmortem text because visible output should not appear before citations are verified.

**Run Stage Event vs Log Line:** Run Stage Events are queryable product and evaluation telemetry. Full prompts, raw LLM responses, stack traces, and detailed debugging context belong in logs keyed by run_id.

**Claim-Generating Stage vs Audit Stage:** Normalizing evidence, extracting timeline candidates, and generating RCA hypotheses may introduce factual incident claims. Verifying citations, drafting the postmortem, and flagging unsupported claims may audit, annotate, or compose existing claims, but must not introduce new factual incident claims.

**Stage Handoff vs In-Memory Handoff:** Run Stages communicate through persisted Pipeline Stage Outputs in the database, not only through in-memory objects. The next stage starts from persisted state.

**Canonical Demo Scenario vs Evaluation Scenario:** The Canonical Demo Scenario is implemented end-to-end in the MVP Review Surface. Additional Evaluation Scenarios may have evidence files and Ground-Truth Postmortems without being polished demo paths.

**Evidence Review System vs Text Generator:** The product should behave like an evidence review system that drafts postmortems. When evidence is genuinely insufficient, it should say so rather than producing confident unsupported narrative.

**Milestone 1 vs Milestone 2:** Milestone 1 proves the web-first, citation-backed postmortem workflow. CLI, vector retrieval, external integrations, rich editing, cloud blob storage, SSE, secrets redaction, and multi-user workspace UX belong to Milestone 2 unless explicitly pulled forward.

**Scenario Fixture vs Product Data:** Scenario fixtures live as files for demos and evaluation. Product data is created through the application and stored separately, even when seeded from a scenario fixture.

**Swappability vs Abstraction:** Swappability is proven by exercised interfaces and alternate implementations in tests. The MVP does not add abstraction layers for components that are not used, tested, or near-term experiment points.

**Deterministic Check vs LLM Judge:** Deterministic checks are the trust floor for citation integrity, required sections, timeline ordering, and explicit support status. LLM judges may score semantic quality using Judge Rubrics, but they are not the authority for whether a citation is valid.

**Experiment Tracking vs A/B Platform:** MVP experiment tracking is run and evaluation metadata for comparing configurations. It is not a user-facing A/B testing platform.

**Uncited Claim vs Failed Run:** An Uncited Claim does not fail an Analysis Run or trigger an automatic retry. It is normalized to an assumption, logged as a warning, and surfaced in Evaluation Runs as a metric.

**Stage Failure vs Warning:** Stage failures stop the Analysis Run after at most one Stage Retry and preserve prior Pipeline Stage Outputs. Warnings such as uncited claims remain non-fatal and are surfaced through Warning Codes.

**Default LLM Provider vs Provider Choice:** The MVP has one configured default LLM provider behind an LLMClient interface. Provider choice is not a user-facing MVP feature.

**Structured Model Output vs Free-Form Prose:** Claim-generating and verifier stages use strict JSON schemas. Free-form prose from the LLM is not pipeline truth.

**Structured Postmortem vs Markdown Export:** The structured Postmortem is the source of truth for UI, evaluation, and citation integrity. Markdown Export is rendered from structured data when requested and is not parsed back into truth.

**Unsupported Claim vs Final Narrative:** Unsupported claims remain auditable as Review Findings, but they are not presented as fact in the main postmortem narrative.

**Reviewer Note vs Edited Claim:** A Reviewer Note records human review context without changing generated structured claims. Full inline editing of generated claims is outside the MVP.

**Single-User Gate vs RBAC:** The MVP uses a Single-User Gate rather than role-based permissions. Workspace ownership exists as a data boundary for future tenancy, not as a user-facing team feature.

**Sensitive-by-Default vs Enterprise Compliance:** MVP evidence is treated as Sensitive Evidence and protected by a Single-User Gate, no public sharing links, and synthetic public demo data. The MVP does not claim enterprise compliance or arbitrary-production-log readiness.

**Workspace Stub vs Workspace Product:** The MVP may use workspace foreign keys for future compatibility, but it does not include workspace switching, workspace-scoped auth, or workspace management UI.

**Relational EvidenceRef vs JSON Citation:** EvidenceRefs are stored relationally for citation panel lookups, evaluation aggregation, and referential integrity. JSON snapshots may exist for raw model output, but they are not the citation source of truth.

**Resource Endpoint vs Command Endpoint:** Incidents, artifacts, analysis runs, and postmortems are fetched through resource-oriented APIs. Actions with side effects use explicit Command Endpoints.
