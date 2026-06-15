# PRD: Bounded Multi-Pass Causal Analysis and Human Root Cause Conclusions

## Problem Statement

Engineers reviewing an incident need more than a plausible AI-generated explanation. The current product can generate ranked, evidence-backed RCA Hypotheses, verify citations, and produce a structured Postmortem, but one model pass can still be analytically shallow. It may overlook counterevidence, collapse multiple causal factors into one apparent winner, or present ranking as stronger than the evidence warrants.

The product also lacks a precise human-in-the-loop path from generated hypotheses to a Root Cause Conclusion. Accepting an RCA Hypothesis is not the same as concluding what caused the incident, especially when a Trigger, Failure Mechanism, and one or more Amplifying Conditions all contributed.

Users need a bounded, auditable causal-analysis process that challenges candidate explanations, makes uncertainty visible, and leaves final causal authority with a human reviewer. The process must preserve exact evidence traceability, complete within predictable token and latency budgets, and avoid free-form agent loops.

## Solution

Extend the existing six-stage, database-persisted Analysis Run with a bounded multi-pass Causal Analysis Stage. The stage will extract incident facts separately from causal interpretation, generate initial RCA Hypotheses, challenge every hypothesis through a falsification role, permit one bounded alternative-expansion round, verify citations and semantic support before ranking, and produce one ordinal Advisory Hypothesis Ranking.

The system will never declare a root cause. After the automated Analysis Run completes, a human conducts Postmortem Review. The reviewer may retain or reject hypotheses and may finalize an evidence-governed Root Cause Conclusion containing exactly one Failure Mechanism plus optional repeatable Triggers and Amplifying Conditions. Finalized conclusions are immutable. Later disagreement is recorded through append-only Conclusion Discrepancies, and an undisputed Superseding Conclusion may become authoritative without changing historical judgments.

The implementation will remain framework-neutral and use the existing persisted orchestration. LangGraph or another orchestration framework may be considered later only if dynamic branching, parallel graph execution, or mid-stage pause/resume becomes necessary.

## User Stories

1. As an incident reviewer, I want incident facts separated from causal interpretations, so that observed impact is not conflated with an explanation of why it happened.
2. As an incident reviewer, I want Impact Claims generated once per Analysis Run, so that competing RCA Hypotheses do not duplicate or contradict the impact section.
3. As an incident reviewer, I want multiple RCA Hypotheses when evidence is ambiguous, so that the system does not force a single explanation.
4. As an incident reviewer, I want a simple incident to permit one RCA Hypothesis, so that the system does not invent alternatives for appearance.
5. As an incident reviewer, I want insufficient evidence to permit zero RCA Hypotheses, so that the system can refuse honestly.
6. As an incident reviewer, I want every RCA Hypothesis challenged, so that overlooked weaknesses are visible before I review it.
7. As an incident reviewer, I want each Hypothesis Challenge to identify counterevidence, so that I can see what weakens a candidate explanation.
8. As an incident reviewer, I want each Hypothesis Challenge to identify Evidence Gaps, so that I know what information is still missing.
9. As an incident reviewer, I want each Hypothesis Challenge to propose Falsification Tests, so that I know how to confirm or refute the explanation.
10. As an incident reviewer, I want challenge severity tied to causal impact, so that critical concerns are distinguishable from minor qualifications.
11. As an incident reviewer, I want factual Counterclaims to cite verified Evidence, so that the falsifier cannot introduce unchecked incident claims.
12. As an incident reviewer, I want uncited Counterclaims labeled as assumptions, so that uncertainty is explicit.
13. As an incident reviewer, I want the falsifier to search all run Artifacts, so that it can discover evidence omitted by the builder.
14. As an incident reviewer, I want the falsifier to propose a missed alternative explanation, so that builder blind spots are not discarded.
15. As an incident reviewer, I want proposed alternatives to pass the same evidence and review path as initial hypotheses, so that they are not trusted prematurely.
16. As an incident reviewer, I want falsification limited to one expansion round, so that analysis cannot enter an unbounded agent loop.
17. As an incident reviewer, I want a final Advisory Hypothesis Ranking after falsification, so that the most plausible candidates are easy to review.
18. As an incident reviewer, I want ranking to be ordinal rather than percentage-based, so that the product does not claim unsupported statistical precision.
19. As an incident reviewer, I want ranking rationale based on evidence strength, counterevidence, explanatory coverage, gaps, and assumptions, so that ordering is explainable.
20. As an incident reviewer, I want the original builder order retained for audit, so that I can see how falsification changed the recommendation.
21. As an incident reviewer, I want unresolved critical challenges shown beside the advisory rank, so that a leading candidate never appears unqualified.
22. As an incident reviewer, I want a first-ranked critically challenged hypothesis labeled clearly, so that ranking is not mistaken for confidence.
23. As an incident reviewer, I want semantic support considered before ranking, so that a valid citation that does not support its claim cannot inflate plausibility.
24. As an incident reviewer, I want citation integrity checked after each claim-producing substep, so that later reasoning does not consume broken references.
25. As an incident reviewer, I want a complete Final Citation Audit, so that all run citations are rechecked at a visible trust checkpoint.
26. As an incident reviewer, I want the Analysis Run to finish before human review begins, so that automated runs and evaluations never wait indefinitely for input.
27. As an incident reviewer, I want the generated document labeled as a Provisional Postmortem, so that it cannot be mistaken for a human conclusion.
28. As an incident reviewer, I want provisional exports labeled "Draft: Root cause not finalized," so that shared drafts retain their review status.
29. As an incident reviewer, I want accepting a hypothesis to mean retaining it as credible, so that acceptance does not silently declare a root cause.
30. As an incident reviewer, I want a separate finalization action, so that Root Cause Conclusion authority is explicit.
31. As an incident reviewer, I want a Root Cause Conclusion to combine multiple accepted hypotheses, so that multi-factor incidents are represented honestly.
32. As an incident reviewer, I want every conclusion to contain exactly one Failure Mechanism, so that it explains how harmful behavior occurred.
33. As an incident reviewer, I want optional repeatable Triggers, so that multiple initiating events can be represented.
34. As an incident reviewer, I want optional repeatable Amplifying Conditions, so that contributing conditions can be represented without being called the mechanism.
35. As an incident reviewer, I want absent or unknown causal roles recorded explicitly, so that the product does not invent complexity.
36. As an incident reviewer, I want every Causal Factor linked to an accepted RCA Hypothesis, so that final conclusions preserve generated provenance.
37. As an incident reviewer, I want every Causal Factor backed by verified citations, so that human finalization cannot bypass the trust floor.
38. As an incident reviewer, I want unsupported beliefs recorded as Human Assumptions, so that they cannot appear as established facts.
39. As an incident reviewer, I want a Partial-Support Acknowledgment when using a partially supported factor, so that uncertainty remains visible.
40. As an incident reviewer, I want critically challenged Failure Mechanisms to require an explicit override, so that severe concerns cannot be dismissed silently.
41. As an incident reviewer, I want critical challenges preserved in the finalized Postmortem, so that finalization does not erase uncertainty.
42. As an incident reviewer, I want finalization provenance recorded, so that I know who made the human judgment and from which Analysis Run.
43. As an incident reviewer, I want finalized Root Cause Conclusions to be immutable, so that historical human judgments remain auditable.
44. As an incident reviewer, I want to raise a Conclusion Discrepancy, so that later disagreement can be recorded without editing history.
45. As an incident reviewer, I want a disputed conclusion removed from authoritative presentation, so that known discrepancies are not shown as current fact.
46. As an incident reviewer, I want the incident returned to unresolved review after a discrepancy, so that corrective review is explicit.
47. As an incident reviewer, I want to create an immutable Superseding Conclusion, so that an incident can regain an authoritative conclusion.
48. As an incident reviewer, I want a Superseding Conclusion linked to its predecessor and discrepancy, so that the conclusion chain is auditable.
49. As an incident reviewer, I want new Evidence to require a new Analysis Run, so that updated conclusions use analysis that includes that Evidence.
50. As an incident reviewer, I want reinterpretation of an existing run to permit a Superseding Conclusion, so that a new run is not required when Evidence is unchanged.
51. As an incident reviewer, I want generated remediation treated as Remediation Proposals, so that weak hypotheses do not create committed work.
52. As an incident reviewer, I want to accept, reject, or defer Remediation Proposals after causal review, so that follow-up work remains human-owned.
53. As an incident reviewer, I want accepted remediation linked to a Causal Factor or Evidence Gap, so that its purpose is explicit.
54. As a product user, I want the status page to remain at six visible stages, so that the workflow stays legible.
55. As a product user, I want stage 2 labeled "Extracting incident facts," so that timeline and impact extraction are described accurately.
56. As a product user, I want stage 3 labeled "Analyzing causal hypotheses," so that generation, challenge, and ranking appear as one coherent phase.
57. As an operator, I want builder, falsifier, alternative verification, support judgment, and ranking persisted as substeps, so that stage 3 remains inspectable.
58. As an operator, I want every Reasoning Role to use strict Structured Model Output, so that invalid output cannot become product state.
59. As an operator, I want one targeted repair attempt for a mechanically invalid role output, so that recoverable failures do not rerun successful work.
60. As an operator, I want Runtime Reasoning Gates to check complete challenge coverage, citation requirements, uniqueness, ranking coverage, and limits, so that repair is deterministic.
61. As an operator, I want stage 3 to fail if one hypothesis cannot be challenged after repair, so that ranking coverage is comparable.
62. As an operator, I want stage 3 to fail if falsification cannot complete, so that unchallenged hypotheses are never presented as multi-pass output.
63. As an operator, I want builder output preserved after falsification failure, so that failed runs remain diagnosable.
64. As an operator, I want no Provisional Postmortem after causal-analysis failure, so that incomplete reasoning cannot look successful.
65. As an operator, I want at most five initial hypotheses and two proposed alternatives, so that review and token costs stay bounded.
66. As an operator, I want role-specific retrieval, input, output, call, and total stage budgets, so that run cost is predictable.
67. As an operator, I want budget reserved for targeted repair, so that normal calls cannot consume the recovery allowance.
68. As an operator, I want explicit budget-exhaustion errors, so that required challenge coverage is never silently skipped.
69. As an operator, I want Retrieval Traces for every Reasoning Role, so that retrieval failures can be distinguished from reasoning failures.
70. As an operator, I want uncited retrieved chunks retained in provenance, so that ignored evidence can be diagnosed.
71. As an operator, I want Model Call Records without duplicated evidence text, so that reproducibility does not unnecessarily expand Sensitive Evidence storage.
72. As an operator, I want prompt versions, schema versions, model identity, token usage, hashes, and structured outputs recorded, so that experiments are comparable.
73. As an operator, I want full prompts and raw responses available only in explicitly enabled restricted logs, so that Sensitive Evidence is not duplicated by default.
74. As an engineer, I want builder, falsifier, ranker, and support verifier behind separate interfaces, so that each Reasoning Role can be tested and replaced independently.
75. As an engineer, I want Reasoning Roles to communicate through persisted structured handoffs, so that hidden chain-of-thought is never a dependency.
76. As an engineer, I want the same configured model to be usable across roles, so that MVP cost and configuration remain simple.
77. As an engineer, I want role metadata to avoid claiming independent models when one model is reused, so that product language remains honest.
78. As an engineer, I want orchestration state to remain product-owned, so that a future framework migration does not replace canonical domain records.
79. As an engineer, I want the existing custom orchestrator retained, so that the feature does not introduce duplicate persistence and retry systems.
80. As an evaluator, I want a builder-only baseline, so that multi-pass value is measured rather than assumed.
81. As an evaluator, I want both configurations run against the same scenarios, models, and retrieval constraints, so that comparisons are fair.
82. As an evaluator, I want structured expected causal roles, so that evaluation does not depend on exact wording.
83. As an evaluator, I want known counterevidence and plausible rejected alternatives recorded in scenarios, so that falsification quality is testable.
84. As an evaluator, I want unacceptable overclaims recorded in scenarios, so that confident but shallow output is penalized.
85. As an evaluator, I want deterministic checks for refusal, challenge coverage, citations, and causal-role constraints, so that the trust floor is mechanical.
86. As an evaluator, I want semantic scoring for explanatory quality, so that analytically shallow but schema-valid results are measured.
87. As an evaluator, I want token and latency metrics recorded beside quality results, so that improvement is not achieved through unbounded cost.
88. As a technical founder, I want the Review Surface to show why one hypothesis ranks above another, so that the product visibly shows its work.
89. As a technical founder, I want contradicting evidence and critical challenges visible without opening debug logs, so that the reasoning process is defensible in a demo.
90. As a technical founder, I want human finalization clearly separated from AI recommendation, so that the product demonstrates responsible HITL authority.

## Implementation Decisions

- Keep the existing framework-neutral, database-persisted orchestration. Do not add LangGraph, Google ADK, or another agent runtime for this version.
- Preserve six visible Run Stages. Rename stage 2 to **Extracting incident facts** and stage 3 to **Analyzing causal hypotheses**.
- Build a deep `CausalAnalysisOrchestrator` module with a small interface that executes the bounded builder, falsifier, alternative-expansion, provisional support, and ranking workflow while persisting each substep.
- Build separate injectable Reasoning Role interfaces for hypothesis building, falsification, advisory ranking, and semantic support verification. Roles may share one configured model but must have independent prompts, schemas, and versions.
- Use persisted structured Role Handoffs. Do not pass hidden chain-of-thought, unstructured chat history, or private model rationale between roles.
- Move Impact Claims from hypothesis ownership to Analysis Run ownership. Stage 2 produces cited Timeline Events and run-level Impact Claims before causal analysis.
- Limit the builder to five initial RCA Hypotheses, the falsifier to two Proposed RCA Hypotheses total, and the final advisory list to seven hypotheses.
- Permit one Falsification Round only. Initial hypotheses are challenged, up to two alternatives may be introduced, those alternatives are verified and challenged once, and ranking then becomes final for the run.
- Persist a Hypothesis Challenge per hypothesis. Its contract includes challenged claim, severity, cited Counterclaims or assumption markers, Evidence Gaps, Falsification Tests, and optional Proposed RCA Hypotheses.
- Define Challenge Severity as:
  - `critical`: if valid, the hypothesis cannot serve as the Failure Mechanism.
  - `material`: reduces plausibility or limits the hypothesis to Trigger or Amplifying Condition.
  - `minor`: adds qualification without changing causal-role suitability.
- Perform Falsification Retrieval across all immutable Artifacts in the Analysis Run, not only builder-selected citations.
- Persist Retrieval Traces containing role and substep identity, retrieval query, strategy version, and ordered Chunk references, including retrieved chunks that were not cited.
- Persist Model Call Records containing prompt version, schema version, model identity, Retrieval Trace, token usage, hashes, and validated structured output. Do not duplicate Artifact text in these records.
- Continue treating EvidenceRefs as the source of truth for cited Artifact line ranges.
- Run Incremental Citation Checks immediately after incident fact extraction, initial hypothesis generation, Counterclaim generation, and Proposed RCA Hypothesis generation.
- Keep stage 4 as the Final Citation Audit that rechecks all EvidenceRefs and records aggregate outcomes.
- Produce Provisional Support Judgments before final ranking. Stage 6 remains the complete unsupported-claim audit.
- Advisory ranking is ordinal. Do not produce causal probability percentages.
- Rank across supporting evidence strength, counterevidence severity, explanatory coverage, unresolved Evidence Gaps, and assumption dependence.
- Persist original builder order separately from the final Advisory Hypothesis Ranking.
- Permit a critically challenged hypothesis to remain first, but label it **Leading but critically challenged** everywhere it is rendered.
- Complete challenge coverage is mandatory. If any hypothesis lacks a valid challenge after one Targeted Repair, fail the Causal Analysis Stage.
- Falsification completion is mandatory. Do not degrade to builder-only output within a multi-pass run.
- Preserve successful prior substep outputs after stage failure for inspection, but produce no Provisional Postmortem.
- Configure Reasoning Budgets for maximum retrieved chunks, input tokens, output tokens, calls, and total stage usage. Reserve capacity for one Targeted Repair per failed role.
- Trigger Targeted Repair only from deterministic Runtime Reasoning Gate failures: schema invalidity, missing challenge or ranking coverage, uncited Counterclaims, duplicate or near-duplicate hypotheses, missing dimensioned rationale, configured limit violations, or citation integrity failures.
- If repair fails or the stage budget is exhausted, fail stage 3 with a specific machine-readable error code.
- Keep semantic quality grading outside runtime success. Use Evaluation Runs to detect shallow but schema-valid reasoning.
- Let the automated Analysis Run complete without waiting for human input. Postmortem Review is a separate lifecycle.
- The automated draft is a Provisional Postmortem and must never state that a root cause was established. UI and exports label it **Draft: Root cause not finalized**.
- Keep Hypothesis Review Decisions distinct from causal conclusion. Accepting a hypothesis means retaining it as credible; it does not finalize a root cause.
- Add a human-only command to finalize a Root Cause Conclusion from one or more accepted RCA Hypotheses.
- A Root Cause Conclusion contains exactly one Failure Mechanism and zero or more Triggers and Amplifying Conditions. Unknown or absent roles are explicit.
- Every Causal Factor references an accepted hypothesis with verified citations and `supported` or `partial` semantic support.
- A partially supported Causal Factor requires a persisted Partial-Support Acknowledgment that is rendered with the conclusion.
- A critically challenged Failure Mechanism requires a persisted Critical-Challenge Override addressing every unresolved critical challenge. The finalized wording remains non-definitive.
- Unevidenced reviewer beliefs are stored as Human Assumptions and cannot render as established Causal Factors.
- Persist Conclusion Provenance: authenticated principal identifier, display name when available, finalization timestamp, and source Analysis Run.
- Root Cause Conclusions are immutable. They are never edited, replaced in place, or deleted.
- Add append-only Conclusion Discrepancies. An open discrepancy makes the linked conclusion disputed and returns the incident to unresolved Postmortem Review.
- Disputed conclusions remain visible in audit history but are not presented as authoritative in the Review Surface or clean exports.
- Permit a new immutable Superseding Conclusion linked to the disputed conclusion and discrepancy. Only an undisputed successor is authoritative.
- A Superseding Conclusion based on new Evidence requires a new Analysis Run. Reinterpretation of unchanged Evidence may reference the original run.
- Treat generated action items as Remediation Proposals. Human reviewers accept, reject, or defer them after causal review and link accepted proposals to a Causal Factor or Evidence Gap.
- Keep falsification scoped to causal reasoning. Remediation quality review does not run inside the Falsification Round.
- Add resource reads for Hypothesis Challenges, Retrieval Traces, Advisory Hypothesis Ranking, Root Cause Conclusions, discrepancies, and Remediation Proposals.
- Add explicit Command Endpoints for hypothesis review, conclusion finalization, discrepancy creation, superseding conclusion finalization, and remediation decisions.
- Enforce relational ownership and cardinality at the database layer where supported, including exactly one Failure Mechanism per finalized conclusion and append-only conclusion history.
- Add compatibility handling for existing SQLite development databases without weakening production relational invariants.
- Update the Review Surface to show the advisory order, ranking rationale, challenge severity, Counterclaims, Evidence Gaps, Falsification Tests, original generation order in audit context, and exact EvidenceRef navigation.
- Update the Review Surface with separate hypothesis-retention controls and Root Cause Conclusion finalization controls.
- Update clean and audit Markdown rendering for provisional, finalized, disputed, and superseding conclusion states.
- Add structured Causal Evaluation Expectations to Scenario Manifests: expected factor families and roles, known counterevidence, plausible rejected alternatives, critical Evidence Gaps, expected refusal, and unacceptable overclaims.
- Compare the bounded multi-pass configuration against a Builder-Only Baseline using the same scenario, model, prompt family, and retrieval constraints.
- Record quality, token usage, call counts, and latency for both configurations.
- Supersede or amend the existing pipeline ADR when implementation begins because Impact Claims move to stage 2 and stage 3 gains persisted causal-analysis substeps while retaining the six-stage ceiling.

## Testing Decisions

- Good tests assert externally visible domain behavior and persisted contracts, not prompt wording, private helper calls, or orchestration implementation details.
- Test the `CausalAnalysisOrchestrator` as a deep module with deterministic fake Reasoning Roles. Cover ordering, one expansion round, hypothesis limits, complete challenge coverage, targeted repair, budget exhaustion, failure preservation, and no provisional draft after failure.
- Test each Reasoning Role contract with strict schema fixtures. Cover valid output, extra fields, missing fields, malformed citations, duplicate hypotheses, missing ranking candidates, and missing dimensional rationale.
- Test Falsification Retrieval and Retrieval Traces with deterministic fixtures. Verify that the falsifier can receive evidence absent from builder citations and that ordered retrieved Chunk references are persisted.
- Test Incremental Citation Checks and the Final Citation Audit with existing citation-verifier patterns. Verify that broken citations cannot influence later ranking.
- Test Provisional Support Judgments with deterministic claim-support fakes. Verify that unsupported or partial support affects ranking inputs and remains consistent with the final unsupported-claim audit.
- Test Impact Claim migration as run-level behavior. Verify that impact appears once per run and remains independent of hypothesis count and review decisions.
- Test the human review/conclusion service as a deep module. Cover exactly one Failure Mechanism, optional repeated Triggers and Amplifying Conditions, accepted-hypothesis requirements, support requirements, partial acknowledgments, critical overrides, Human Assumptions, and provenance.
- Test append-only conclusion behavior. Verify that finalized conclusions cannot be updated or deleted through service or API commands.
- Test Conclusion Discrepancies. Verify that flagging preserves the conclusion, marks it disputed, removes authoritative presentation, and returns review to unresolved.
- Test Superseding Conclusions. Verify predecessor/discrepancy links, authority transfer, same-run reinterpretation, and new-run requirements when new Evidence is used.
- Test Remediation Proposal decisions independently from causal falsification. Verify accept, reject, defer, and linkage to Causal Factors or Evidence Gaps.
- Extend API tests using the repository's existing resource and Command Endpoint patterns. Test success, validation failures, cross-run ownership violations, immutable-history violations, and nearby mutation error responses.
- Extend frontend integration tests around the existing incident Review Surface. Test advisory ranking, visible critical challenges, citation navigation, distinct retain/reject and finalization actions, provisional labeling, discrepancy state, and superseding conclusion rendering.
- Extend Markdown renderer tests. Verify that provisional exports never state a Root Cause Conclusion, finalized exports preserve qualifications, disputed conclusions are not authoritative, and audit exports retain historical conclusions and discrepancies.
- Extend scenario loader tests for structured Causal Evaluation Expectations and fail fast on unknown families, invalid roles, missing evidence references, or contradictory expectations.
- Extend deterministic evaluation checks for challenge coverage, alternative consideration, unsupported causal claims, refusal, causal-role cardinality, critical Evidence Gaps, and unacceptable overclaims.
- Extend semantic judge inputs to evaluate explanatory coverage and falsification quality without granting the judge citation-validity authority.
- Add paired evaluation tests for multi-pass and Builder-Only Baseline configurations. Assert recorded token, latency, and quality metrics rather than exact natural-language wording.
- Reuse current prior art: stage retry/failure tests, strict RCA schema tests, citation-integrity tests, claim-support fakes, scenario replay fixtures, evaluation checks, API command tests, Markdown clean/audit tests, and Playwright Review Surface tests.
- Full backend regression, frontend typecheck, and targeted Playwright review-flow tests are required before completion.

## Out of Scope

- LangGraph, Google ADK, or another orchestration framework migration.
- Free-form agent chat or recursive agent loops.
- More than one falsification expansion round.
- More than five initial hypotheses, two proposed alternatives, or seven final candidates.
- Probability percentages for causal likelihood.
- Autonomous Root Cause Conclusion finalization.
- Treating the top-ranked RCA Hypothesis as the root cause.
- Editing or deleting finalized Root Cause Conclusions.
- General document revision history beyond append-only discrepancies and Superseding Conclusions.
- Multi-user RBAC, approval chains, or mandatory second-reviewer workflows.
- User-facing model/provider selection.
- Different models per Reasoning Role as an MVP requirement.
- Vector retrieval unless evaluation demonstrates that deterministic retrieval is insufficient.
- Falsifier review of remediation quality.
- Autonomous acceptance or execution of remediation.
- Full inline editing of generated claims.
- Public sharing links.
- Storing complete prompts, raw responses, or duplicated Evidence text in product tables.
- Replacing the six-stage status-page model.
- Mid-run human pauses.
- Streaming draft text or chain-of-thought.
- Enterprise compliance claims or secrets-redaction guarantees.

## Further Notes

- Customer-facing language should remain: the product generates evidence-backed postmortems and shows its work. Do not market implementation roles as "multi-agent AI."
- The system produces RCA Hypotheses and an Advisory Hypothesis Ranking. Only a human creates a Root Cause Conclusion.
- A ranking is a review aid, not causal authority.
- Runtime checks can prove structural validity and evidence discipline, but cannot prove deep reasoning quality. Scenario evaluation remains essential.
- Existing pipeline persistence, retries, Warning Codes, EvidenceRefs, Review Surface patterns, and deterministic scenario replay should be extended rather than replaced.
- The implementation should begin with an ADR that supersedes the affected parts of the current six-stage pipeline decision while preserving the six visible stages and database-persisted handoffs.
