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

### Impact Claim
An incident-level assertion about observed user or system consequences that remains independent of any RCA Hypothesis.

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

### Root Cause Conclusion
The human reviewer's structured causal account of the incident, composed from one or more accepted RCA Hypotheses without forcing a single winning hypothesis.

### Postmortem Review
The human lifecycle that begins after an Analysis Run completes and ends when a reviewer finalizes or deliberately leaves unresolved the Root Cause Conclusion.

### Hypothesis Review Decision
A human reviewer's decision to retain or reject an RCA Hypothesis as credible without declaring it to be the Root Cause Conclusion.

### Hypothesis Challenge
A persisted falsification review of an RCA Hypothesis that identifies weaknesses, counterevidence, alternatives, missing evidence, and validation tests without accepting or rejecting it.

### Counterclaim
A factual statement in a Hypothesis Challenge that weakens an RCA Hypothesis and therefore requires verified evidence or an assumption marker.

### Evidence Gap
A procedural statement identifying evidence needed to evaluate an RCA Hypothesis without asserting a new incident fact.

### Falsification Test
A proposed investigation that could confirm or refute an RCA Hypothesis without itself asserting an incident fact.

### Remediation Proposal
A system-generated candidate follow-up attached to an RCA Hypothesis that is not a committed action until a human accepts, rejects, or defers it during Postmortem Review.

### Challenge Severity
The advisory impact of a Hypothesis Challenge on causal use: Critical blocks use as the Failure Mechanism if valid, Material reduces plausibility or limits causal role, and Minor adds qualification without changing causal role.

### Proposed RCA Hypothesis
An alternative hypothesis introduced during falsification that must complete the standard citation, support, challenge, ranking, and human review path before use.

### Falsification Round
The single bounded review pass that challenges initial RCA Hypotheses, may add Proposed RCA Hypotheses, challenges those additions once, and then ends with an Advisory Hypothesis Ranking.

### Causal Analysis Stage
The Run Stage that performs hypothesis generation, one Falsification Round, alternative verification, and final Advisory Hypothesis Ranking as persisted substeps.

### Incident Fact Extraction Stage
The Run Stage that produces cited Timeline Events and run-level Impact Claims before causal interpretation begins.

### Causal Analysis Orchestrator
The framework-neutral component that executes the bounded Causal Analysis Stage using the product's persisted domain outputs and run telemetry.

### Reasoning Role
A narrow model responsibility with its own prompt, structured output contract, version, and injectable interface, independent of whether another role uses the same underlying model.

### Role Handoff
The persisted structured inputs passed between Reasoning Roles, excluding hidden chain-of-thought, chat history, and unstructured private rationale.

### Falsification Retrieval
A fresh search across all artifacts in an Analysis Run used to find counterevidence and overlooked context beyond the builder's cited subset.

### Retrieval Trace
The persisted role-specific retrieval query, strategy version, ordered Chunk references, and substep identity, including retrieved results that were not cited.

### Model Call Record
The persisted metadata for a Reasoning Role invocation: prompt and schema versions, model identity, Retrieval Trace, token usage, hashes, and structured output without duplicated evidence text.

### Advisory Hypothesis Ranking
A post-challenge system ordering of RCA Hypotheses by relative plausibility, shown with a rationale and unresolved critical challenges while retaining the original generation order for audit.

### Plausibility Assessment
An ordinal, evidence-explained assessment of an RCA Hypothesis across support strength, counterevidence, explanatory coverage, evidence gaps, and assumption dependence.

### Hypothesis Budget
The bounded causal-analysis cardinality of at most five initial RCA Hypotheses, two Proposed RCA Hypotheses, and seven hypotheses in the final advisory list.

### Reasoning Budget
The recorded per-role and stage limits for retrieval, model input, model output, and calls, with capacity reserved for one targeted repair attempt.

### Targeted Repair
The single bounded re-invocation of a failed Reasoning Role using its validation errors without rerunning successful roles or skipping required coverage.

### Runtime Reasoning Gate
A deterministic contract check for schema validity, complete challenge and ranking coverage, evidence requirements, uniqueness, dimensioned rationale, configured limits, and citation integrity.

### Causal Factor
An accepted contributor referenced by a Root Cause Conclusion in a defined role such as Trigger, Failure Mechanism, or Amplifying Condition.

### Human Assumption
A reviewer-authored, explicitly labeled belief recorded when a potential Causal Factor lacks sufficient verified evidence and therefore cannot be presented as established fact.

### Partial-Support Acknowledgment
A reviewer's persisted explanation of what is supported, what remains uncertain, and why a partially supported RCA Hypothesis is still included as a Causal Factor.

### Critical-Challenge Override
A reviewer's persisted acknowledgment and evidence-based rationale for using a critically challenged RCA Hypothesis as the Failure Mechanism while preserving the unresolved challenge and non-definitive wording.

### Conclusion Provenance
The authenticated principal, display identity when available, timestamp, and source Analysis Run recorded for a Root Cause Conclusion.

### Conclusion Discrepancy
A human-authored, append-only flag that identifies a problem with an immutable Root Cause Conclusion without editing, replacing, or deleting it.

### Disputed Conclusion
An immutable Root Cause Conclusion with an open Conclusion Discrepancy that is preserved for audit but is not presented as authoritative.

### Superseding Conclusion
A new immutable Root Cause Conclusion linked to a Disputed Conclusion and its discrepancy that becomes authoritative without modifying either historical record.

### Failure Mechanism
The required Causal Factor that explains how the incident's harmful behavior occurred.

### Trigger
An optional Causal Factor that initiated the Failure Mechanism.

### Amplifying Condition
An optional Causal Factor that increased the likelihood, duration, or impact of the Failure Mechanism.

### Postmortem
The final structured incident analysis. Sections: summary, timeline, impact analysis,
root cause hypotheses, remediation items, lessons learned. Every major claim
in the postmortem links to an EvidenceRef or is explicitly marked as an assumption.

### Provisional Postmortem
An Analysis Run's non-conclusive draft that presents hypotheses, evidence, challenges, and uncertainty while explicitly stating that the Root Cause Conclusion is not finalized.

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
Current stages: normalize evidence → extract incident facts → analyze causal hypotheses → verify citations → draft postmortem → flag unsupported claims. Six stages is the MVP status-page ceiling.

### Verifier
The component that checks whether a claim is actually supported by the evidence
it cites. Returns SUPPORTED, PARTIAL, or UNSUPPORTED. Unsupported claims are
flagged, not deleted.

### Citation Integrity Verifier
The deterministic verifier that checks whether an EvidenceRef points to existing artifact lines and whether its snippet exactly matches those lines.

### Incremental Citation Check
A deterministic citation-integrity check performed immediately after a claim-producing substep so later reasoning does not consume broken references.

### Final Citation Audit
The complete citation-integrity pass that rechecks all run EvidenceRefs and records aggregate stage outcomes after claim generation ends.

### Claim Support Verifier
The semantic verifier that judges whether cited evidence supports, partially supports, or does not support a Major Claim.

### Provisional Support Judgment
A semantic support classification produced before Advisory Hypothesis Ranking so ranking accounts for whether verified citations actually support each claim.

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

### Builder-Only Baseline
The comparison configuration that generates RCA Hypotheses without a Falsification Round and is evaluated on the same scenarios, models, and retrieval constraints.

### Experiment Metadata
The versioned configuration recorded with Analysis Runs and Evaluation Runs so pipeline, prompt, model, retrieval, chunking, and verifier choices can be compared.

### Judge Rubric
A structured semantic scoring guide used by an LLM judge to evaluate generated postmortems against Ground-Truth Postmortems and scenario expectations.

### Uncited Claim
A Major Claim emitted without EvidenceRefs or an assumption marker, normalized to an assumption and counted as an evaluation metric.

### Scenario Manifest
A structured file that describes an Incident Scenario's metadata, evidence artifacts, ambiguity notes, expected hypothesis families, and evaluation tags.

### Causal Evaluation Expectations
Structured Scenario Manifest data describing expected causal factor families and roles, known counterevidence, plausible rejected alternatives, critical evidence gaps, refusal behavior, and unacceptable overclaims.

### Swappable Component
A pipeline component with an explicit interface because the MVP uses, tests, or expects near-term experiments for alternate implementations.

### Prompt Version
The identifier for the prompt template and instructions used by an Analysis Run or Evaluation Run.

### Structured Model Output
LLM output that must conform to a stage-specific JSON schema before it can become pipeline state.

## Key distinctions

**Evidence vs Claim:** Evidence is raw source material. A claim is something
the system asserts based on evidence. Never conflate them.

**Impact Claim vs RCA Hypothesis:** An Impact Claim describes observed consequences once per Analysis Run; it is not owned by or duplicated across competing causal hypotheses.

**Incident Facts vs Causal Analysis:** Timeline Events and Impact Claims describe what happened; RCA Hypotheses and Hypothesis Challenges interpret why it happened.

**Artifact Replacement vs Artifact Mutation:** Evidence corrections are represented by creating a new Artifact, not by mutating an Artifact that has been used by an Analysis Run.

**Canonical Artifact Text vs Blob Object:** The MVP stores canonical line-addressable artifact text in Postgres. Blob or cloud object storage is a future Artifact Storage implementation for larger files or cloud deployment.

**Normalized Timestamp vs Original Timestamp Text:** Timeline events use normalized UTC timestamps for ordering when available, but preserve original timestamp text for auditability. Inferred Timestamps must be labeled with uncertainty.

**Hypothesis vs Root Cause:** The system generates hypotheses, not root causes.
A root cause is what a human engineer concludes after reviewing the hypotheses.
The system does not declare root causes.

**RCA Hypothesis vs Root Cause Conclusion:** An RCA Hypothesis is a system-generated candidate for review; a Root Cause Conclusion is an explicit human decision and is never inferred from model ranking or synthesis.

**Hypothesis Review Decision vs Root Cause Conclusion:** Accepting an RCA Hypothesis retains it as credible; only a separate human finalization action creates the Root Cause Conclusion.

**Analysis Run vs Postmortem Review:** An Analysis Run completes without waiting for human input; Postmortem Review consumes its persisted outputs afterward and owns Root Cause Conclusion Finalization.

**Provisional Postmortem vs Finalized Postmortem:** A Provisional Postmortem never states that a root cause was established and is labeled "Draft: Root cause not finalized"; only a human-finalized Postmortem contains a Root Cause Conclusion.

**Advisory Hypothesis Ranking vs Root Cause Conclusion:** A ranking recommends which RCA Hypotheses are most plausible; only a human may decide which become Causal Factors.

**Plausibility Assessment vs Probability:** Plausibility is expressed through ordinal comparison and evidence-based rationale, never as an unsupported probability or percentage.

**Hypothesis Multiplicity vs Hypothesis Budget:** Ambiguous evidence should produce competing hypotheses within the budget, while insufficient evidence may produce none and a simple strongly supported incident may produce one.

**Reasoning Budget vs Targeted Repair:** Normal role calls cannot consume the capacity reserved for one Targeted Repair; if repair fails or the total budget is exhausted, the Causal Analysis Stage fails explicitly.

**Runtime Reasoning Gate vs Semantic Evaluation:** Runtime gates repair mechanically invalid outputs; scenario evaluations measure analytical depth and usefulness without controlling run success.

**Advisory Rank vs Critical Challenge:** An RCA Hypothesis may remain first in the Advisory Hypothesis Ranking while critically challenged, but every rendering labels it "Leading but critically challenged."

**RCA Hypothesis vs Causal Factor:** An RCA Hypothesis is a candidate explanation; it becomes a Causal Factor only when a human includes it in the Root Cause Conclusion with an explicit causal role.

**Proposed RCA Hypothesis vs Trusted Output:** A falsifier-proposed alternative is not trusted synthesis input until it has passed the same verification and review path as an initially generated RCA Hypothesis.

**Counterclaim vs Evidence Gap vs Falsification Test:** Counterclaims are Major Claims and follow the evidence contract; Evidence Gaps and Falsification Tests are procedural guidance and do not require citations.

**Remediation Proposal vs Committed Action:** Generated remediation remains advisory until a human links an accepted proposal to a finalized Causal Factor or documented Evidence Gap.

**Causal Falsification vs Remediation Review:** The Falsification Round challenges causal explanations only; remediation quality is reviewed separately after humans establish the relevant Causal Factors or Evidence Gaps.

**Challenge Severity vs Human Decision:** Challenge Severity advises causal-role suitability; a reviewer may override it only with a persisted rationale.

**Critical Challenge vs Finalization:** A critically challenged RCA Hypothesis may become the Failure Mechanism only through a Critical-Challenge Override; otherwise the Root Cause Conclusion remains unresolved.

**Bounded Falsification vs Agent Loop:** Falsification permits one alternative-expansion round and no recursive proposal loop; remaining possibilities are recorded as open questions.

**Run Stage vs Causal Analysis Substep:** The Review Surface shows one Causal Analysis Stage; builder, falsifier, alternative verification, and ranking remain separately persisted and auditable substeps rather than additional visible stages.

**Product State vs Orchestrator State:** Analysis Runs, hypotheses, challenges, rankings, and human decisions remain canonical product data; an orchestration framework may later execute the flow but must not become their source of truth.

**Reasoning Role vs Independent Model:** Builder, falsifier, ranker, and support verifier are separate Reasoning Roles, but they are not described as independent models unless configured with distinct model instances.

**Role Handoff vs Hidden Reasoning:** Downstream roles consume persisted hypotheses, citations, incident facts, and evidence rather than another role's hidden reasoning or conversation state.

**Builder Evidence vs Falsification Retrieval:** The falsifier reviews the builder's citations but also performs an independent retrieval across all immutable run artifacts.

**Retrieval Trace vs EvidenceRef:** A Retrieval Trace explains what evidence a Reasoning Role received; an EvidenceRef identifies the exact immutable lines used to support or contradict a claim.

**Model Call Record vs Debug Log:** Product data keeps reproducibility metadata and structured outputs; complete prompts and raw responses containing Sensitive Evidence appear only in explicitly enabled restricted debug logs.

**Completed Builder vs Failed Falsification:** Builder output remains inspectable when falsification exhausts its retry, but the Causal Analysis Stage and Analysis Run fail and no Provisional Postmortem is produced.

**Complete vs Partial Challenge Coverage:** Every RCA Hypothesis must receive a schema-valid Hypothesis Challenge before Advisory Hypothesis Ranking; one unrecoverable challenge failure fails the Causal Analysis Stage.

**Failure Mechanism vs Trigger vs Amplifying Condition:** Every Root Cause Conclusion has exactly one Failure Mechanism; Triggers and Amplifying Conditions are optional and repeatable, and absent or unknown roles are recorded explicitly rather than invented.

**Causal Factor vs Human Assumption:** A Causal Factor references an accepted RCA Hypothesis with verified citations and supported or partial claim support; an unevidenced reviewer belief remains a Human Assumption or the conclusion stays unresolved.

**Supported vs Partially Supported Causal Factor:** A partially supported Causal Factor requires a Partial-Support Acknowledgment and retains its uncertainty wherever the finalized conclusion is rendered.

**Assumption vs Supported Claim:** An assumption is a claim the system makes
without evidence support. It must be labeled. A supported claim has at least
one EvidenceRef with confidence > threshold.

**Major Claim vs Generic Text:** Major Claims require EvidenceRefs or an assumption marker. Section headings, UI labels, procedural wording, and generic explanatory text are not Major Claims.

**Verifier Status vs Confidence Score:** Verifier status is the categorical support judgment: SUPPORTED, PARTIAL, or UNSUPPORTED. Confidence score is a numeric signal used to explain strength, rank citations, and help reviewers triage borderline claims.

**Citation Integrity vs Claim Support:** Citation integrity is deterministic evidence address validation. Claim support is semantic judgment about whether the cited evidence actually supports the claim.

**Incremental Citation Check vs Final Citation Audit:** Incremental checks protect downstream reasoning after each claim-producing substep; the Final Citation Audit remains the visible, complete verification stage.

**Provisional Support Judgment vs Final Unsupported-Claim Audit:** Provisional judgments inform causal ranking; the final audit re-evaluates and surfaces every unsupported or partially supported Major Claim before completion.

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

**Ground-Truth Postmortem vs Causal Evaluation Expectations:** Prose ground truth supplies semantic context, while structured expectations enable deterministic checks without requiring exact generated wording.

**Evidence Review System vs Text Generator:** The product should behave like an evidence review system that drafts postmortems. When evidence is genuinely insufficient, it should say so rather than producing confident unsupported narrative.

**Milestone 1 vs Milestone 2:** Milestone 1 proves the web-first, citation-backed postmortem workflow. CLI, vector retrieval, external integrations, rich editing, cloud blob storage, SSE, secrets redaction, and multi-user workspace UX belong to Milestone 2 unless explicitly pulled forward.

**Scenario Fixture vs Product Data:** Scenario fixtures live as files for demos and evaluation. Product data is created through the application and stored separately, even when seeded from a scenario fixture.

**Swappability vs Abstraction:** Swappability is proven by exercised interfaces and alternate implementations in tests. The MVP does not add abstraction layers for components that are not used, tested, or near-term experiment points.

**Deterministic Check vs LLM Judge:** Deterministic checks are the trust floor for citation integrity, required sections, timeline ordering, and explicit support status. LLM judges may score semantic quality using Judge Rubrics, but they are not the authority for whether a citation is valid.

**Multi-Pass Evaluation vs Builder-Only Baseline:** The bounded causal-analysis flow must demonstrate better reasoning quality than the baseline under recorded token and latency constraints rather than merely producing more text.

**Experiment Tracking vs A/B Platform:** MVP experiment tracking is run and evaluation metadata for comparing configurations. It is not a user-facing A/B testing platform.

**Uncited Claim vs Failed Run:** An Uncited Claim does not fail an Analysis Run or trigger an automatic retry. It is normalized to an assumption, logged as a warning, and surfaced in Evaluation Runs as a metric.

**Stage Failure vs Warning:** Stage failures stop the Analysis Run after at most one Stage Retry and preserve prior Pipeline Stage Outputs. Warnings such as uncited claims remain non-fatal and are surfaced through Warning Codes.

**Default LLM Provider vs Provider Choice:** The MVP has one configured default LLM provider behind an LLMClient interface. Provider choice is not a user-facing MVP feature.

**Structured Model Output vs Free-Form Prose:** Claim-generating and verifier stages use strict JSON schemas. Free-form prose from the LLM is not pipeline truth.

**Structured Postmortem vs Markdown Export:** The structured Postmortem is the source of truth for UI, evaluation, and citation integrity. Markdown Export is rendered from structured data when requested and is not parsed back into truth.

**Unsupported Claim vs Final Narrative:** Unsupported claims remain auditable as Review Findings, but they are not presented as fact in the main postmortem narrative.

**Reviewer Note vs Edited Claim:** A Reviewer Note records human review context without changing generated structured claims. Full inline editing of generated claims is outside the MVP.

**Single-User Gate vs RBAC:** The MVP uses a Single-User Gate rather than role-based permissions. Workspace ownership exists as a data boundary for future tenancy, not as a user-facing team feature.

**Conclusion Provenance vs Approval Workflow:** The MVP records who finalized each Root Cause Conclusion but does not introduce roles, approval chains, or multi-reviewer authorization.

**Root Cause Conclusion vs Conclusion Discrepancy:** A finalized Root Cause Conclusion is immutable; later disagreement is preserved as a separate Conclusion Discrepancy rather than a revision or replacement.

**Disputed Conclusion vs Unresolved Review:** Raising a Conclusion Discrepancy makes the conclusion disputed and returns the incident to unresolved Postmortem Review without altering the original conclusion.

**Superseding Conclusion vs Revision:** A Superseding Conclusion is a new append-only human judgment linked to the disputed predecessor, not an edit or revision of that predecessor.

**New Evidence vs Reinterpretation:** A Superseding Conclusion based on newly added Evidence requires a new Analysis Run; one based only on reinterpretation may reference the original immutable run.

**Sensitive-by-Default vs Enterprise Compliance:** MVP evidence is treated as Sensitive Evidence and protected by a Single-User Gate, no public sharing links, and synthetic public demo data. The MVP does not claim enterprise compliance or arbitrary-production-log readiness.

**Workspace Stub vs Workspace Product:** The MVP may use workspace foreign keys for future compatibility, but it does not include workspace switching, workspace-scoped auth, or workspace management UI.

**Relational EvidenceRef vs JSON Citation:** EvidenceRefs are stored relationally for citation panel lookups, evaluation aggregation, and referential integrity. JSON snapshots may exist for raw model output, but they are not the citation source of truth.

**Resource Endpoint vs Command Endpoint:** Incidents, artifacts, analysis runs, and postmortems are fetched through resource-oriented APIs. Actions with side effects use explicit Command Endpoints.
