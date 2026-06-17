# Automated Output Is a Provisional Postmortem Until a Human Finalizes

This decision makes the lifecycle state of an automated Postmortem explicit: every Analysis Run produces a **Provisional Postmortem**, never a finalized Root Cause Conclusion. It is the next slice of the bounded multi-pass causal-analysis work (PRD #26, issue #29, user stories 26-28) and builds on ADR 0026 (six-stage DB-persisted pipeline), ADR 0032 (insufficient-evidence refusal), and ADR 0033 (run-level incident facts). It changes no stage count and adds no model call — it is a labeling and persisted-state decision.

## A Postmortem carries a conclusion status, defaulting to provisional

The `postmortems` table gains a `conclusion_status` column (`provisional` | `finalized`), defaulting to `provisional`. The drafting stage (stage 5) always writes `provisional`: an automated run completes without waiting for human input (ADR 0026), so it cannot have a human-finalized conclusion. The `finalized` value is reserved for a later human-finalization slice (PRD #26 stories 30-43); automated runs never set it. Persisting the status as product data — rather than deriving "provisional" implicitly from "no conclusion exists" — makes the provisional state explicit and distinguishable from a future finalized conclusion, and gives the later finalization command a column to transition.

Existing development databases gain the column through the established idempotent compatibility path (`ensure_schema_compatibility`), defaulting existing automated drafts to `provisional`, which is correct: none of them has a human conclusion.

## Provisional status is visible everywhere the postmortem is rendered

A provisional draft must never be mistaken for a human conclusion, so the label **"Draft: Root cause not finalized"** appears in every rendering:

- The **Review Surface** shows a `Draft: Root cause not finalized` badge beside the postmortem heading and a banner explaining that no root cause has been established and that only a human reviewer finalizes a Root Cause Conclusion.
- **Clean and audit Markdown exports** both stamp the label into the document heading (so it survives a copied fragment), add an explanatory blockquote, and record a `**Status:** provisional` metadata line. The label is keyed off `conclusion_status`, not run success, so a future finalized export drops the banner automatically.

## Provisional labeling is orthogonal to evidence sufficiency

Provisional status and the insufficient-evidence refusal (ADR 0032) are independent axes and compose: a refused run is still a provisional draft pending a human conclusion, and a fully evidence-backed run is also provisional until finalized. The renderer and Review Surface show both signals when both apply, without conflating them.

## Deterministic composition still asserts no root cause

The deterministic composer (ADR 0012) already declines to name a leading hypothesis or assert a root cause; this slice keeps that property and adds tests that a provisional export states "no root cause has been established" rather than converting the top-ranked hypothesis into authoritative wording. Drafting remains a stage-5 audit/compose step that introduces no new factual incident claims (ADR 0026).

## What this slice does not yet do

This slice does not add the human finalization command, the Root Cause Conclusion entity, Causal Factors, Conclusion Discrepancies, or Superseding Conclusions — those are later slices of PRD #26. It only establishes the provisional state and its labeling, so the eventual finalization path has an explicit state to transition away from.
