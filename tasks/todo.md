# Slice 6: Generate and review ambiguous RCA hypotheses from cited evidence

## Objective

Implement GitHub issue #7 (blocked-by #6, merged → unblocked). Stage 3
(`generating_rca_hypotheses`) becomes real: an `LLMClient` turns the run's
normalized evidence + timeline into multiple ranked RCA Hypotheses, each with
supporting evidence, contradicting evidence, unknowns, validation steps, impact
claims, and remediation items. These persist in explicit structured tables with
relational EvidenceRefs and render in the Review Surface where a human can
accept/reject hypotheses without rewriting generated claims.

This is the first slice with an LLM in the pipeline. Tests use fake/replay
clients; real runs use one configured generation provider.

## Relevant ADRs / PRD

- 0011 one default LLM provider behind `LLMClient`; fakes/replay for tests.
- 0028 strict structured JSON output; invalid JSON / schema-invalid fails the stage.
- 0013 every Major Claim carries EvidenceRefs or `assumption=true`; an uncited
  Major Claim is normalized to assumption, logs a warning, counts `uncited_claim`
  (does NOT fail/retry the run).
- 0024 explicit structured tables (hypotheses, impact_claims, action_items) +
  relational EvidenceRefs reused across owners.
- 0029 stage fails → one retry → fail run; prior persisted outputs stay intact.
- 0016 review = accept/reject + notes, no full inline editing of claims.
- 0022 resource APIs + explicit command endpoints (start run, record review).
- 0009 `LLMClient` is a kept interface; swappability shown via fakes in tests.
- PRD stage 3: produces `Hypothesis[]`, `ImpactClaim[]`, `RemediationItem[]`
  (ranked; supporting + contradicting evidence + unknowns + validation steps).

## Plan

### Backend
- [x] `llm.py`: `LLMClient` Protocol (`complete(system, user) -> LLMResponse`),
  `LLMResponse(text, usage)`, `FakeLLMClient` (canned/replay for tests),
  `OpenAICompatibleLLMClient` (provider-agnostic, stdlib urllib; base_url + key +
  model from settings), `OfflineLLMClient`, `build_llm_client(settings)`.
- [x] `config.py`: settings for llm base_url/api_key/model (defaults); offline
  default documented (empty-hypotheses) so runs without a key still succeed.
- [x] `rca.py`: strict Pydantic output contract (`RcaGenerationOutput` →
  hypotheses w/ supporting/contradicting refs, unknowns, validation_steps,
  impact_claims, remediation_items) + prompt builder from evidence/timeline.
- [x] `models.py`: `Hypothesis`, `ImpactClaim`, `ActionItem`; extend `EvidenceRef`
  with nullable owner FKs (hypothesis_id, impact_claim_id, action_item_id) + `role`
  (supporting/contradicting). `assumption` + `review_status` on Hypothesis.
- [x] `services/stages.py`: real `_generate_rca` stage — call LLM, parse+validate
  (raise on invalid → stage fail), resolve EvidenceRef snippets from actual
  artifact lines, normalize uncited Major Claims to assumptions (`uncited_claim`),
  persist; idempotent across retry (clear prior hypotheses first).
- [x] `services/analysis.py`: thread `llm_client`; `list_hypotheses`,
  `review_hypothesis`; read-shapers for the new schemas.
- [x] `schemas.py`: `HypothesisRead` (+ impact_claims, action_items, split
  evidence), `HypothesisReviewCreate`.
- [x] `api/analysis_runs.py`: `GET .../{run_id}/hypotheses`,
  `POST .../{run_id}/hypotheses/{hypothesis_id}/review`; thread client into the
  background executor via settings.

### Frontend
- [x] `lib/api.ts`: Hypothesis/ImpactClaim/ActionItem types; `listRunHypotheses`,
  `reviewHypothesis`.
- [x] Incident page: ranked hypotheses under a succeeded run — supporting/
  contradicting evidence, unknowns, validation steps, impact claims, remediation
  items, assumption badges, accept/reject controls.

### Tests
- [x] Ambiguous fixture evidence + seeded FakeLLMClient → multiple hypotheses.
- [x] Schema-invalid model output fails the stage; chunks+timeline persist, no
  hypotheses, run failed (no corruption).
- [x] Uncited Major Claim normalized to assumption + `uncited_claim` warning.
- [x] Accept/reject updates review_status without altering generated claims.
- [x] `LLMClient` swappability (fake/replay) + API endpoint tests.
- [x] Backend pytest (103 passed) + frontend typecheck/build pass; e2e unchanged.

## Notes

- EvidenceRef table already anticipated reuse (nullable timeline_event_id). Add
  sibling nullable owner FKs + `role`; tables are created via `create_all`.
- Stage 3 needs an LLM; AnalysisService default uses an offline fake (no
  hypotheses) so deterministic timeline tests stay green. Real runs inject the
  configured client through the background route.

## Review

Stage 3 (`generating_rca_hypotheses`) is now real and end-to-end.

### What landed
- **Provider-agnostic LLM boundary** (`llm.py`). Per the user's call, the real
  client is `OpenAICompatibleLLMClient` (stdlib urllib, `/chat/completions`,
  `response_format: json_object`), switchable by base_url + api_key + model alone —
  not an Anthropic-specific client as the original plan sketched. `FakeLLMClient`
  (list or callable) drives all tests; `OfflineLLMClient` returns empty hypotheses
  so keyless runs still complete six stages. `build_llm_client` picks provider vs
  offline from settings.
- **Strict output contract** (`rca.py`, `PROMPT_VERSION="rca-1"`). Model output is
  validated with `RcaGenerationOutput.model_validate_json`; a `ValidationError`
  becomes a `ValueError` that fails the stage (ADR 0028) before anything persists.
- **Structured tables + relational citations** (`models.py`). `Hypothesis`,
  `ImpactClaim`, `ActionItem`; `EvidenceRef` gained nullable owner FKs +
  `role`. Snippets are resolved from the stored artifact lines, never the model.
- **Citation contract** (ADR 0013). Uncited hypotheses/impact claims → `assumption`
  + deduped `uncited_claim` warning on the stage event; does not fail the run.
  Out-of-range / foreign-artifact citations are dropped.
- **Idempotent retry** (ADR 0029): `_clear_hypotheses` runs first, so a
  failed-then-retried stage never duplicates; chunks + timeline are untouched.
- **Review Surface**: read endpoints + accept/reject command; the incident page
  renders ranked hypotheses with split evidence, claims, remediation, and badges.
  Review flips `review_status` only (ADR 0016).

### Verification
- Backend: 103 passed (18 new across `test_stages_rca.py`,
  `test_services_hypotheses.py`, `test_api_hypotheses.py`). Covers all six
  acceptance criteria including the two required proofs (ambiguous → multiple
  hypotheses; schema-invalid fails the stage without corrupting prior outputs).
- Frontend: `tsc --noEmit` clean; `next build` succeeds. e2e unchanged (offline
  path shows "No RCA hypotheses"; the spec asserts only the kept "Postmortem"
  heading).

### Deviations from the original plan
- Provider client is OpenAI-compatible/model-agnostic (user decision), not
  `AnthropicLLMClient`.
- Background settings are resolved inside `execute_analysis_run_background`
  (defaulting to `Settings.from_env()`) rather than threaded through the scheduler,
  to keep the existing scheduler-override test's 3-arg signature intact.
- `ImpactClaim` and `ActionItem` both carry a `hypothesis_id` (user decision:
  per-hypothesis ownership for both).

## Review Fix Plan

Apply only the concrete review findings. No pipeline redesign.

- [x] Add a minimal schema-compatibility upgrade for issue-6-era databases so
  the existing `evidence_refs` table receives the new nullable owner columns and
  `role` column before ORM queries run. Add a regression that starts from the old
  table shape.
- [x] Thread the app's configured LLM settings into the default background task
  so queued-run metadata and execution always describe the same provider/model.
  Preserve the existing scheduler override test hook.
- [x] Make RCA Pydantic output models reject unknown keys (`extra="forbid"`) so
  typo fields fail the stage per ADR 0028.
- [x] Reject foreign-artifact and out-of-range model citations instead of
  silently dropping them, so invalid refs fail stage 3 and prior stage outputs
  remain inspectable.
- [x] Make Review Surface citation rows focus the cited artifact and highlight
  its exact line range in the existing Evidence panel.
- [x] Record provider identity alongside model name in run experiment metadata,
  without introducing a provider picker or provider-matrix abstraction.
- [x] Sanitize provider exceptions persisted in Run Stage Events; keep raw
  provider response bodies out of structured event state.
- [x] Add focused regressions for each fix, run targeted backend tests, full
  backend pytest, frontend typecheck/build, and the existing end-to-end suite.

## Review Fix Verification

- Focused backend regression suite: 36 passed.
- Full backend suite: 109 passed.
- Frontend: `npm run typecheck` and `npm run build` passed.
- Browser regression: `npm run e2e` passed (2 tests), including timeline
  citation click -> exact line highlight.
- Hygiene: `git diff --check` passed; local e2e services and generated output
  were removed after the run.

## Deferred Backlog

- [ ] After all planned slices are complete, define and implement incident-level
  removal from the workspace dashboard. Decide explicitly between archiving
  analyzed incidents and hard-deleting the full incident aggregate. Individual
  evidence locked into an analysis run must remain protected.
- [ ] Add a dedicated prompt-quality phase after the MVP slices. Improve RCA
  depth beyond schema compliance: require evidence-backed causal chains,
  separate customer impact from inferred mechanism, produce executable
  validation checks, propose concrete remediation, identify contradicting
  evidence, and compare competing hypotheses. Evaluate changes against the
  synthetic incident fixtures before changing the default prompt version.

## Review Follow-Up Batch

- [x] Make the issue-6 `evidence_refs` column upgrade tolerate concurrent
  startups without swallowing non-duplicate database failures.
- [x] Reject non-HTTP(S) configured LLM base URLs before constructing requests
  with bearer authorization headers.
- [x] Enforce `EvidenceRef` ownership and role invariants at the database layer
  for fresh schemas and upgraded SQLite/Postgres databases.
- [x] Surface hypothesis accept/reject failures inline in the Review Surface
  without changing the existing success-only cache update.
- [ ] Run focused regressions while review findings arrive, then run the full
  backend suite and hygiene checks once the batch is complete.

## Application Logging Plan

Add useful pipeline visibility without logging secrets or raw incident evidence
by default.

- [ ] Add structured application logs for analysis-run queue/start/finish,
  stage attempt/success/failure, artifact/chunk counts, timeline candidate
  counts, RCA provider/model invocation, validated RCA output counts, and
  hypothesis review decisions.
- [ ] Keep API keys, bearer headers, raw provider envelopes, full prompts, raw
  evidence bodies, and citation snippets out of default logs.
- [ ] Decide whether local development also needs an explicit opt-in payload
  logging mode for raw prompts and model completions. If added, default it off
  and document the data-exposure risk.
- [ ] Add focused logging regressions and run backend validation.
