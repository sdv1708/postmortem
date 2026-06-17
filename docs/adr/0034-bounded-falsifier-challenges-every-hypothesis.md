# Bounded Falsifier Challenges Every Initial RCA Hypothesis

This decision extends the Causal Analysis Stage (stage 3, "Analyzing causal hypotheses") with a bounded **falsifier** Reasoning Role. It builds on ADR 0033 (run-level incident facts, renamed stages) and is the second slice of the bounded multi-pass causal-analysis work (PRD #26, issue #28, user stories 3-13, 24, 57-58, 74-79, 88-89). It preserves the six visible status-page stages and the rule that every stage persists its outputs to the database before the next stage starts; the falsifier is a persisted **substep** of stage 3, not a seventh visible stage.

## Every initial hypothesis is challenged before stage 3 can succeed

After the builder generates and persists the initial RCA Hypotheses, the falsifier challenges each one. A **Hypothesis Challenge** is a persisted falsification review that identifies what weakens a hypothesis without accepting or rejecting it: an advisory **severity**, cited **Counterclaims**, **Evidence Gaps**, and **Falsification Tests**. Exactly one challenge is persisted per hypothesis (a 1:1 relationship), and complete challenge coverage is mandatory — if the falsifier cannot produce a schema-valid challenge for any hypothesis, the stage fails after its single retry (ADR 0029) rather than presenting unchallenged hypotheses as multi-pass output. No Provisional Postmortem is produced after a causal-analysis failure, and the builder's already-persisted output remains inspectable for diagnosis.

A run with no hypotheses (the offline configuration, or an insufficient-evidence scenario) produces no challenges and still completes its six stages: the falsifier is never invoked when there is nothing to challenge.

## Counterclaims are Major Claims; gaps and tests are procedural

A **Counterclaim** is a factual statement that weakens the hypothesis, so it follows the same Major-Claim contract as a hypothesis or impact claim (ADR 0013): its citations resolve from immutable artifact lines (ADR 0024), never from model text, or it is normalized to an explicit assumption and flagged `uncited_claim`. Counterclaim citations are a fifth `EvidenceRef` owner (`counterclaim_id`) and are audited at the Final Citation Audit (stage 4) alongside every other citation, so a challenge cannot smuggle in unchecked incident facts. **Evidence Gaps** and **Falsification Tests** are procedural guidance — they name missing information and proposed investigations — so they assert no new incident fact and carry no citations.

**Challenge Severity** advises causal-role suitability: `critical` (if valid, the hypothesis cannot serve as the Failure Mechanism), `material` (reduces plausibility or limits it to a contributing role), or `minor` (a qualification that does not change the causal role). Severity is an advisory signal for the later human conclusion, not a runtime success criterion.

## The falsifier is a separate Reasoning Role behind a swappable boundary

Falsification runs through an injectable `Falsifier` with its own strict structured-output contract (`HypothesisChallengeOutput`), prompt, and version — a Reasoning Role distinct from the builder and the incident-facts extractor, even when all three are backed by the same configured model. The default `LLMFalsifier` makes one model call per hypothesis and validates the output against the schema before it becomes pipeline state; there is no offline shortcut, because a hypothesis cannot be honestly challenged without a model. The falsifier consumes a persisted, structured Role Handoff — the hypothesis title, summary, and cited snippets — and the full immutable run-artifact set, never another role's hidden chain-of-thought or chat history. Because it receives **all** run artifacts rather than only the builder's retrieval subset, it can cite counterevidence the builder overlooked.

The scenario demo path injects a `ScenarioReplayFalsifier` driven by a bundled, per-hypothesis `replay/falsification.json`, so the canonical demo and its tests exercise the complete challenge path deterministically and offline. The scenario loader requires one bundled challenge per replay hypothesis, so a fixture cannot ship incomplete coverage.

## Existing databases gain the counterclaim owner without weakening invariants

The `evidence_refs` exactly-one-owner invariant grows from four owners to five. Existing databases gain the `counterclaim_id` column, and the owner constraint is recreated to include it: SQLite drops and recreates the owner triggers (a `CREATE TRIGGER IF NOT EXISTS` would otherwise keep a stale four-owner check), and PostgreSQL drops and re-adds the named CHECK constraint. Existing rows, which populate only the original four owners, continue to satisfy the constraint because the new owner is null. The new `hypothesis_challenges` and `counterclaims` tables are created by `create_all`; clearing and regenerating hypotheses on a stage retry cascades their challenges and counterclaims away, so the substep is idempotent.

## What this slice does not yet do

This slice does not introduce Proposed RCA Hypotheses (falsifier-proposed alternatives), the Advisory Hypothesis Ranking, the full Reasoning Budget and Targeted Repair machinery, or Model Call Records. Those are later slices of PRD #26. Challenge severity is persisted and surfaced but does not yet drive a ranking, and the single bounded falsification round here is limited to challenging the initial hypotheses.
