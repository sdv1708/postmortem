# Run-Level Incident Facts and Renamed Fact/Causal Stages

This decision supersedes the affected parts of ADR 0026. It preserves the six visible status-page stages and the rule that every stage persists its outputs to the database before the next stage starts; it changes where Impact Claims are produced and owned, and it renames two stages to describe that change honestly. It is the first slice of the bounded multi-pass causal-analysis work (PRD #26, issue #27, user stories 1-2 and 54-56).

## Incident facts are separated from causal interpretation

Impact Claims are incident facts — observed user or system consequences — not interpretations of why an incident happened. They are now produced and owned at the **Analysis Run** level, exactly once per run, and are independent of how many RCA Hypotheses the causal stage later generates. Previously an Impact Claim hung off a single Hypothesis, which conflated observed impact with one competing explanation and duplicated or contradicted impact across hypotheses. The structured Postmortem read model, the run API, the Review Surface, and the clean and audit Markdown exports all present impact once.

Impact Claims remain Major Claims: each is backed by verified EvidenceRefs pointing at immutable artifact lines, or is normalized to an assumption and flagged. Citations resolve from stored artifact lines, never from model text. The EvidenceRef ownership contract is unchanged — `impact_claim_id` is still one of the four exclusive owners — so existing citation-integrity and claim-support verification apply without modification.

## Stage two produces incident facts; stage three analyzes causes

The second visible stage is renamed from "extracting timeline candidates" to **Extracting incident facts**: it produces cited Timeline Events (deterministically, as before) and run-level Impact Claims before any causal interpretation begins. The third stage is renamed from "generating RCA hypotheses" to **Analyzing causal hypotheses**. The RCA stage no longer emits Impact Claims; it generates and ranks Hypotheses and their remediation items. Six stages remain the status-page ceiling, and the stage identifiers used by the API, executor, and evaluation harness are renamed to match the visible labels so they cannot drift.

## Incident facts are a separate Reasoning Role behind a swappable boundary

Run-level impact extraction runs through an injectable `IncidentFactExtractor` with its own strict structured-output contract (`IncidentFactsOutput`), prompt, and version — a Reasoning Role distinct from RCA generation, even though both may use the same configured model. The default LLM-backed extractor validates model output against the schema before it becomes pipeline state; the offline client returns an empty object, which both the incident-facts and RCA contracts accept as "nothing extracted" so a run still completes its six stages without a configured provider.

## Existing databases are upgraded without losing impact data

Existing `impact_claims` rows are re-owned from their hypothesis to the run: `run_id` is backfilled from the former hypothesis. SQLite rebuilds the table because it cannot drop a `NOT NULL` column; PostgreSQL adds the column, backfills, enforces `NOT NULL`, and drops the old one. Claim ids are preserved so existing EvidenceRefs remain valid, and the EvidenceRef ownership and role constraints are not weakened.

The SQLite rebuild builds a temporary table and renames it into place rather than renaming the referenced table aside. Renaming the referenced `impact_claims` table would make SQLite rewrite `evidence_refs.impact_claim_id` to point at the renamed-aside table, which is then dropped — leaving a dangling foreign key. Renaming only the new (unreferenced) table leaves existing citation references intact, so they keep resolving to the rebuilt table and `PRAGMA foreign_key_check` stays clean.

Persisted Run Stage identifiers are also migrated: existing `run_stage_events` rows carrying the old `extracting_timeline_candidates` and `generating_rca_hypotheses` values are renamed to the new identifiers, so an upgraded database's historical runs still satisfy the renamed-stage API response contract instead of failing validation on read.
