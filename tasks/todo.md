# Slice 12: Refuse confident postmortems when evidence is insufficient (#13)

## Status check
Branched from `feature/issue-12-evaluation-runs` (commit 90577f9 — slice 11
evaluation work, merged-equivalent; `main` wasn't fast-forwarded). That base
already ships the evaluation framework AND an `insufficient-evidence` scenario
stub (empty-hypotheses replay), plus eval checks that *tolerate* emptiness for
refusal scenarios. This slice adds the **product refusal behavior** and makes it
visible across service / API / UI / eval, with a positive refusal check.

## Objective
When evidence is insufficient, the system must say so — a structured refusal —
instead of presenting an unsupported narrative as a confident postmortem
(ADR 0032 trust bar; ADR 0015 honesty). The Review Surface must stay useful:
source evidence, the separation of knowns / unknowns / assumptions, and concrete
next validation steps.

## Key design decisions
- **Deterministic sufficiency on the Postmortem (ADR 0026-safe).** The drafting
  composer computes `evidence_sufficiency` = `insufficient` when **no hypothesis
  has supporting evidence** (`assumption == False` count is 0). This catches both
  the zero-hypothesis stub and any all-uncited run. `evidence_gaps` and
  `next_validation_steps` are generic procedural guidance about *evidence
  completeness* — not new factual incident claims — so a deterministic composer
  may emit them. Persisted on the `postmortems` row (one VARCHAR + two JSON cols).
- **Refusal is a product detection, not a scenario tag.** Eval keys
  `insufficient_evidence_expected` off the scenario tag, but the *product* path
  derives sufficiency from the run's own structured output, so seeding the stub
  (or any sparse incident) shows refusal with no eval involvement.
- **A positive refusal check (AC #4).** `check_insufficient_evidence_refusal`
  asserts refusal scenarios actually refused (`evidence_sufficiency==insufficient`)
  and that normal scenarios did *not* spuriously refuse. Drafting emits an
  `insufficient_evidence` Warning Code so eval warning counts reflect it.
- **Honest exports + UI.** Markdown export leads with an "insufficient evidence"
  notice and a gaps / next-evidence section; clean export still presents no
  confident sections. The Review Surface shows a refusal banner separating
  knowns / unknowns / assumptions / next steps while keeping the evidence panel.

## Plan

### Backend — product refusal
- [x] `models.py`: `Postmortem.evidence_sufficiency` + `evidence_gaps` +
  `next_validation_steps`.
- [x] `db.py`: `ensure_schema_compatibility` adds the three `postmortems` columns.
- [x] `drafting.py`: composer computes sufficiency / gaps / validation steps +
  refusal summary; context gains `present_source_types`.
- [x] `services/stages.py`: persist the fields; return `insufficient_evidence`
  warning when insufficient.
- [x] `services/analysis.py` + `schemas.py`: thread the three fields through.
- [x] `markdown_export.py`: insufficient-evidence notice + gaps / next-evidence.

### Backend — evaluation
- [x] `evaluation.py`: `RunOutputSnapshot.evidence_sufficiency` +
  `check_insufficient_evidence_refusal` in `DETERMINISTIC_CHECKS`.
- [x] `services/evaluation.py`: set `evidence_sufficiency` in `_distill`.

### Frontend
- [x] `lib/api.ts`: `Postmortem` gains the three fields.
- [x] Incident page `RunPostmortem`: refusal banner (what's missing / next
  evidence) when insufficient; evidence panel + Review Findings stay usable.

### Tests (service / API / UI / eval — AC #6)
- [x] `test_drafting.py`: composer refusal vs sufficient; gaps/steps; summary.
- [x] `test_stages_drafting.py`: cited run sufficient/no warning; empty-hypotheses
  run refuses + emits `insufficient_evidence`.
- [x] `test_services_scenarios.py`: seeding `insufficient-evidence` refuses.
- [x] `test_api_postmortem.py`: GET exposes sufficiency/gaps/steps; export shows
  the refusal notice + no confident root cause.
- [x] `test_evaluation*.py`: refusal check both directions; updated check-name set
  and the stub's `insufficient_evidence` warning count.
- [x] e2e: seed the insufficient scenario → refusal banner + next steps + evidence
  panel; no RCA hypotheses section.
- [x] Backend pytest **214 passed**; frontend typecheck + build clean; Playwright
  **5 passed**.

## Review

Slice 12 (#13) is implemented: the system now refuses a confident postmortem when
evidence is insufficient, and that refusal is visible and tested across the
service, API, Review Surface, and evaluation dashboard.

### What landed
- **Deterministic refusal on the Postmortem.** `DeterministicPostmortemComposer`
  sets `evidence_sufficiency = insufficient` when no hypothesis is evidence-backed
  (`assumption == False` count is 0 — covers the zero-hypothesis stub and any
  all-uncited run), and emits `evidence_gaps` + `next_validation_steps` (procedural
  guidance about evidence completeness, not new incident facts — ADR 0026-safe).
  Persisted on `postmortems` (one VARCHAR + two JSON cols; legacy ALTER added).
- **Non-fatal Warning Code.** Drafting returns `insufficient_evidence` so the
  refusal is visible on the stage event and aggregated by evaluation (ADR 0021).
- **Honest read/export.** `PostmortemRead` carries the three fields; Markdown
  export leads with an "insufficient evidence" notice and what's-missing /
  next-evidence sections; clean export still presents no confident root cause.
- **Review Surface stays useful (AC #5).** `RunPostmortem` shows a refusal banner
  separating what's missing and suggested next evidence; the evidence panel,
  timeline, and any assumption Review Findings remain below.
- **A positive eval refusal check (AC #4).** `check_insufficient_evidence_refusal`
  fails both ways — a refusal scenario must refuse, a normal scenario must not
  spuriously refuse — added to the deterministic floor; the stub's warning counts
  now include `insufficient_evidence`.

### Verification
- Backend `pytest`: **214 passed** (+9). Frontend `typecheck` + `build` clean.
- e2e `npx playwright test`: **5 passed** — new test seeds the insufficient
  scenario and asserts the refusal banner, next-evidence steps, an available
  evidence panel, and the *absence* of an RCA-hypotheses section. `_e2e.db`
  removed, servers torn down.

### Notes
- Branched from `feature/issue-12-evaluation-runs` (90577f9), not `main`: the
  merged-equivalent slice-11 work (incl. the `insufficient-evidence` stub) lives
  there; `main` was never fast-forwarded. Captured in `lessons.md`.
- Refusal is derived from the run's own output (not a scenario tag), so it works
  for any sparse product incident — the eval tag only drives the eval expectation.

---

# Branch review follow-up

## Objective
Review the generated final feature implementation with high precision, verify it against the project rules/ADRs/tests, and apply only necessary fixes.

## Plan
- [x] Inspect the full working-tree diff and identify behavior, schema, API, UI, evaluation, and test risks introduced on this branch.
- [x] Run targeted backend/frontend verification to reproduce any failures or confirm the claimed green state.
- [x] Implement minimal, elegant fixes for confirmed issues only.
- [x] Re-run the relevant tests/typechecks/e2e checks proving the fixes work.
- [x] Update this review section with findings, changes made, and verification results.

## Review Follow-up Results

Finding fixed:
- The deterministic evaluation checks treated an insufficient-evidence scenario
  as valid only when it produced exactly zero citations and zero hypotheses. That
  was too narrow: a valid refusal can still have verified timeline/partial
  evidence citations, or uncited assumption hypotheses, as long as it has no
  evidence-backed confident hypothesis. `check_citation_integrity`,
  `check_hypothesis_multiplicity`, and `check_insufficient_evidence_refusal` now
  encode that boundary.

Additional coverage:
- Added unit coverage for refusal scenarios with zero citations, verified
  citations, broken citations, uncited assumptions, and evidence-backed
  hypotheses.
- Added schema-compatibility coverage for upgrading pre-refusal `postmortems`
  tables with `evidence_sufficiency`, `evidence_gaps`, and
  `next_validation_steps`.

Verification:
- Targeted backend: `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_evaluation.py tests/test_evaluation_runner.py tests/test_api_evaluations.py tests/test_drafting.py tests/test_stages_drafting.py tests/test_api_postmortem.py tests/test_services_scenarios.py` -> 51 passed.
- Full backend: `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider` -> 215 passed, 1 existing `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning.
- Frontend: `npm run typecheck` -> passed.
- `git diff --check` -> no whitespace errors; Git reported CRLF conversion warnings only.
