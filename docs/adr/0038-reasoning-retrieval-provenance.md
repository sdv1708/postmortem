# Reasoning and Retrieval Provenance

This decision makes the bounded Causal Analysis Stage (stage 3) diagnosable. Each Reasoning Role invocation persists a **Model Call Record**, and each role retrieval persists a **Retrieval Trace**, exposed through a restricted run-diagnostics resource and view. It is the next slice of the bounded multi-pass causal-analysis work (PRD #26, issue #32, user stories 57, 69-73, 75-79, 88-89) and builds on the builder, falsifier, alternative-expansion, and ranker substeps (ADRs 0033-0037). It adds no visible Run Stage — provenance is metadata about the existing six stages.

## Provenance is captured at the role boundary, not inside each role

The roles (builder, falsifier, support verifier, ranker, plus the stage-2 incident-fact extractor) already talk to the configured model through the `LLMClient` boundary (ADR 0011). Rather than thread provenance plumbing through every role, the stage wraps the configured client in a **`RecordingLLMClient`** decorator and constructs the default roles with it. Every completion funnels through the wrapper transparently; it buffers each call's reproducibility metadata — **prompt and response hashes plus token usage, never their text** — which the stage drains at each role boundary to write a Model Call Record. A role backed by a deterministic implementation (the MVP advisory ranker) or an injected test fake makes no model call, so its drain is empty and the record falls back to the role's own version as model identity with null usage and hashes. The record still documents that the substep ran, with which prompt/schema versions, and what it returned.

## Records store references and hashes, never Sensitive Evidence

A Model Call Record holds role/substep identity, prompt and schema versions, model identity, token usage, prompt/response hashes, the linked Retrieval Trace, and the validated structured output. A Retrieval Trace holds role/substep identity, the retrieval query, the strategy version, and **ordered Chunk references** — chunk id, owning artifact, source order, and line span — never chunk or Artifact text. Complete prompts, raw responses, hidden chain-of-thought, and duplicated evidence stay out of product tables and remain only in restricted run-keyed debug logs (ADR 0021, CONTEXT "Model Call Record vs Debug Log"). The citation snippet is still the EvidenceRef's job — the citation source of truth (ADR 0024) — and is deliberately not duplicated into provenance.

The structured output stored on a Model Call Record is a **sanitized outcome skeleton, not the raw validated object**. A model can quote an Artifact line verbatim into a free-text field — a hypothesis summary, a counterclaim statement, a support rationale, a ranking rationale — so persisting the raw output would smuggle Sensitive Evidence into the provenance table and diagnostics API even though the prompt and response are only hashed. The recorder therefore keeps only the validated output's diagnostic shape: citations as **references** (artifact id + line range, never snippet text), plus counts, severities, support statuses, and ranking order. The free text itself already lives in the product tables the normal Review Surface renders (`hypotheses`, `counterclaims`, `ranking_rationale`), so nothing diagnostic is lost and no Artifact text is duplicated. A regression test asserts that a marker repeated from an Artifact into a model's free-text fields never reaches a Model Call Record or the diagnostics response.

## Retrieved-but-uncited evidence distinguishes retrieval omission from model omission

A Retrieval Trace records every chunk a role received, flagging which the role actually cited. The builder's trace covers the chunks its `RetrievalStrategy` selected; the falsifier's covers **all** immutable run artifacts, because Falsification Retrieval spans the whole evidence set (ADR 0034, PRD user story 13). Keeping the uncited remainder is what makes the two failure modes separable: a relevant chunk **absent** from a role's trace is a *retrieval omission*, while a chunk **present but uncited** is a *model omission* — the evidence was in front of the model and ignored (PRD user story 70). Linking each Model Call Record to its Retrieval Trace lets a diagnostician tell a retrieval failure from a reasoning failure (PRD user story 69).

### Synthesis roles trace their handoff inputs, not chunk retrieval

PRD user story 69 asks for input provenance for *every* Reasoning Role, but only the builder and falsifier perform document retrieval. The support verifier and ranker are synthesis roles that consume persisted Role Handoffs (ADR 0037, PRD user story 75), so their "input trace" is shaped to what they actually receive:

- **Support verifier**: it judges a hypothesis's *verified supporting* citations, so its trace records the chunks those citations resolve to (marked cited, since they are the evidence it weighed). An empty support trace therefore means no verified evidence reached the judgment — an input omission — as opposed to a judgment that saw evidence and returned `unsupported`.
- **Ranker**: it consumes the `RankingCandidate` handoff — every initial and proposed hypothesis's post-challenge facts — and performs no chunk retrieval, so it has **no** Retrieval Trace by design. Its inputs are fully diagnosable from its own structured output (the ordered candidate ids) together with the persisted hypotheses and their challenges those ids reference. Inventing a chunk-shaped trace for a role that never touches chunks would be dishonest provenance; this is the deliberately narrowed scope for the ranker.

## A separate, restricted resource leaves the Review Surface unchanged

Diagnostics are served from a dedicated `GET /analysis-runs/{run_id}/diagnostics` resource behind the same single-user gate as every run resource (ADR 0017), and rendered in a collapsed, lazily loaded panel on the run card. The normal claim-to-evidence review workflow is untouched; opening the panel shows component versions, token usage, hashes, ordered retrieved chunk references, and structured outcomes so the product can visibly show its work without exposing debug logs (PRD user stories 88-89).

## Idempotency and storage

Provenance rows are owned by the Analysis Run and cascade-deleted with it. A claim-generating stage clears only its own roles' Model Call Records and Retrieval Traces before regenerating, so the single stage retry (ADR 0029) never leaves duplicates. The two tables are new, so existing SQLite/Postgres databases gain them through `create_all` with no column migration; no existing table changes shape.

## What this slice does not yet do

It does not add full Reasoning Budgets, Targeted Repair, or the Builder-Only Baseline comparison (later slices of PRD #26). Provenance is observability: it records what each role did and saw, but does not itself gate run success — Runtime Reasoning Gates and budgets remain the mechanisms that fail a stage.
