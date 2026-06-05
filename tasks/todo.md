# Senior Review: Local Changes Against Domain Standards

## Review Plan

- [x] Read project brief, context, and the ADRs most relevant to the changed files.
- [x] Inventory the local diff and identify the behavioral surfaces touched.
- [x] Review backend schema, verification, and pipeline logic for security, data integrity, and ADR alignment.
- [x] Review API schema and frontend rendering for evidence-handling and UX correctness.
- [x] Review tests and run targeted verification where practical.
- [x] Add a concise review section with findings, residual risks, and verification results.

## Senior Review Results

Fix plan:
- [x] Make stage 6 semantic support use only verified supporting citations.
- [x] Record the actual injected claim-support verifier version in run metadata.
- [x] Add focused regressions for broken citations and swapped verifier metadata.
- [x] Run targeted backend verification.

Findings:
- [x] Stage 6 can mark a claim as supported using citations whose integrity stage already marked them broken. `_classify_claim` sends every non-contradicting `EvidenceRef.snippet` to the semantic verifier without checking `ref.verifier_status == "verified"`, while the UI routes authoritative vs review findings solely by `support_status`. A claim with `snippet_mismatch`, `artifact_missing`, or `line_range_invalid` can therefore still show as supported/authoritative. This cuts against CONTEXT's working-citation contract and ADR 0014's deterministic trust floor.
- [x] `AnalysisService` accepts a swappable `claim_support_verifier`, but run metadata always records `citation-integrity-1+claim-support-1`, even when the injected verifier has a different `version`. That weakens ADR 0025 experiment tracking and the client brief's A/B-able tradeoff requirement.

Positive checks:
- The claim-support verifier is schema-validated with `extra="forbid"` and fails the stage on invalid/non-JSON output.
- Stage 6 annotates existing hypotheses and impact claims in place; it does not introduce new factual claims.
- Unsupported and partial claims remain non-fatal warning-code outcomes.
- The API surfaces support status/rationale on hypotheses and impact claims, and the frontend separates unsupported top-level hypotheses into Review Findings.

Verification:
- `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_claim_support.py` passed: 8 passed.
- Broader targeted backend tests were blocked before assertions by pytest temp-directory permission errors (`PermissionError: [WinError 5] Access is denied` under both the default Windows temp root and explicit repo basetemp attempts). The blocked tests all failed during fixture setup (`tmp_path`), not from code assertions.
- After applying fixes, the targeted backend suite passed outside the sandbox:
  `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_claim_support.py tests/test_stages_flagging.py tests/test_stages_citations.py tests/test_api_hypotheses.py tests/test_db_compatibility.py` -> 29 passed.
- `git diff --check` passed; only line-ending warnings were reported.

# Slice 8: Separate unsupported and assumed claims from the authoritative narrative

## Objective

Implement GitHub issue #9 (blocked-by #8, merged → unblocked). Ship the second
verification pass from ADR 0014: a **semantic ClaimSupportVerifier** that judges whether
the cited evidence actually supports each Major Claim — SUPPORTED / PARTIAL / UNSUPPORTED —
and make **stage 6 (`flagging_unsupported_claims`)** real. The Review Surface separates
unsupported/assumed claims into auditable "Review Findings" rather than presenting them as
authoritative fact, so the product stays honest when evidence is partial or missing.

Stage 4 stays the deterministic integrity pass (#8); stage 5 (drafting) remains a no-op
until #10. Uncited Major Claims are already normalized to assumptions in the RCA stage
(`uncited_claim`); this slice classifies the *cited* claims and surfaces the distinction.

## Relevant ADRs / PRD

- 0014 split verification into citation **integrity** (deterministic, done) and claim
  **support** (semantic, LLM). This slice ships the support pass.
- 0015 / 0032 / CONTEXT "evidence review system, not text generator": unsupported claims
  remain auditable Review Findings, not authoritative narrative; flagged, not deleted.
- 0026 stage 6 may only annotate existing claims — it introduces no new factual claims.
- 0013 uncited Major Claims → assumptions + `uncited_claim` (already in stage 3).
- 0028 strict structured output for the support judgment; 0029 non-fatal: unsupported /
  uncited claims never fail the run or trigger a retry.
- 0009 / 0011 the claim-support verifier is a swappable boundary using one configured LLM;
  tests inject fakes/replays. 0025 record the verifier version in experiment metadata.

## Plan

### Backend
- [x] `verification.py`: `ClaimSupportStatus` enum, `ClaimToVerify`/`ClaimSupportJudgment`
  dataclasses, `ClaimSupportVerifier` Protocol, strict `ClaimSupportOutput` +
  `build_claim_support_prompt`, `LLMClaimSupportVerifier`, `CLAIM_SUPPORT_VERIFIER_VERSION`.
- [x] `models.py`: `support_status` (default `unevaluated`) + `support_rationale` on
  `Hypothesis` and `ImpactClaim` (the Major Claims). `ActionItem` unchanged.
- [x] `db.py`: generalize `ensure_schema_compatibility` to upgrade multiple tables; add the
  two support columns to `hypotheses` and `impact_claims` for issue-7-era databases.
- [x] `services/stages.py`: route `flagging_unsupported_claims` → `_flag_unsupported_claims`;
  classify each hypothesis + impact claim (uncited → UNSUPPORTED with no model call); emit
  `unsupported_claim` / `partial_claim_support` warnings; idempotent across retry. Inject the
  verifier (default `LLMClaimSupportVerifier(self._llm)`).
- [x] `services/analysis.py`: thread `claim_support_verifier`; stamp combined
  `verifier_version`; thread support fields through the read-shapers.
- [x] `schemas.py`: `ClaimSupportStatus` Literal + `support_status`/`support_rationale` on
  `HypothesisRead` and `ImpactClaimRead`.

### Frontend
- [x] `lib/api.ts`: `ClaimSupportStatus` type + support fields on `Hypothesis`/`ImpactClaim`.
- [x] Incident page: partition hypotheses into the authoritative list (supported + partial)
  vs a separate muted **"Review findings · unsupported"** section with a disclaimer; add a
  `ClaimSupportBadge` and a `SupportRationale` caution line on hypotheses + impact claims.

### Tests
- [x] `test_claim_support.py`: `LLMClaimSupportVerifier` + `FakeLLMClient` replay →
  supported / partial / unsupported; schema-invalid, non-JSON, extra-field all raise.
- [x] `test_stages_flagging.py`: full pipeline + injected `FakeClaimSupportVerifier`
  (swappable boundary) → support persists with rationale + correct warning codes; uncited
  hypothesis → UNSUPPORTED with no model call; run succeeds without retry; idempotent retry.
- [x] `test_api_hypotheses.py`: support fields present; a partial/unsupported judge surfaces
  through the API.
- [x] `test_db_compatibility.py`: issue-7 upgrade adds support columns to both claim tables.
- [x] Updated the prior-slice full-pipeline tests (`test_stages_rca`, `test_stages_citations`,
  `test_services_hypotheses`) to inject the fake verifier now that stage 6 runs; combined
  `verifier_version` assertion. Shared `tests/_fakes.py::FakeClaimSupportVerifier`.
- [x] Backend pytest (140 passed) + frontend typecheck/build + e2e (2 passed).

## Review

Stage 6 (`flagging_unsupported_claims`) is now real. The pipeline judges whether cited
evidence supports each Major Claim and the Review Surface keeps unsupported material
auditable but out of the authoritative narrative.

### What landed
- **Swappable semantic verifier** (`verification.py`). `LLMClaimSupportVerifier` builds a
  strict prompt, calls the one configured LLM (ADR 0011), and validates the verdict against
  `ClaimSupportOutput` (`extra="forbid"`, ADR 0028) — schema-invalid/non-JSON raises so an
  unverifiable verdict never persists. It judges the stored citation snippets (the source of
  truth, ADR 0024), never model-invented text. The `ClaimSupportVerifier` Protocol mirrors
  the `CitationVerifier` boundary so tests swap in a fake (ADR 0009).
- **Support on Major Claims** (`models.py`, `db.py`). `support_status` (default
  `unevaluated`) + `support_rationale` on `Hypothesis` and `ImpactClaim`; the
  schema-compatibility helper was generalized to upgrade multiple tables idempotently.
- **Stage 6 work** (`services/stages.py`). `_flag_unsupported_claims` classifies each
  hypothesis (title + summary) and impact claim (description). An uncited claim is an
  assumption → recorded UNSUPPORTED without calling the model; cited claims go to the
  verifier. Weak claims raise `unsupported_claim` / `partial_claim_support` Warning Codes,
  but the run still succeeds with no retry (ADR 0015 / 0029). Only annotates — no new claims
  (ADR 0026) — and is idempotent across the single retry (overwrites in place).
- **Experiment metadata** records both passes: `verifier_version =
  citation-integrity-1+claim-support-1` (ADR 0025).
- **Review Surface**: supported + partially-supported hypotheses render under the
  authoritative "RCA hypotheses" list; unsupported ones drop into a muted "Review findings ·
  unsupported" section with a disclaimer. Each Major Claim shows a support badge (emerald /
  amber / rose) and partial/unsupported claims show the verifier's rationale as caution text.

### Verification
- Backend: **140 passed** (+13). New `test_claim_support.py` (8) and
  `test_stages_flagging.py` (3) cover supported / partial / unsupported / uncited
  normalization, the swappable boundary, the non-fatal contract, and idempotent retry. API +
  db-compatibility tests extended.
- Cross-stage impact handled honestly: stage 6 now consumes claim-support calls, so the
  prior-slice full-pipeline tests inject `FakeClaimSupportVerifier` (shared `tests/_fakes.py`)
  so their runs genuinely succeed rather than silently failing at stage 6.
- Frontend: `npm run typecheck` and `npm run build` clean.
- e2e: `npx playwright test` **2 passed** — offline demo path yields no hypotheses, so stage
  6 is a clean no-op and the existing citation flow is intact. Servers torn down, `_e2e.db`
  removed.

### Deviations from the plan
- None of substance. Claim support runs in stage 6 (not stage 4) per the ADR 0026 stage
  names; the Review-Findings grouping is derived from `support_status` in the UI rather than
  a new DB entity (Simplicity first).

## Deferred Backlog

- [ ] After all planned slices are complete, define and implement incident-level
  removal from the workspace dashboard. Decide explicitly between archiving analyzed
  incidents and hard-deleting the full incident aggregate. Individual evidence locked
  into an analysis run must remain protected.
- [ ] Add a dedicated prompt-quality phase after the MVP slices. Improve RCA depth
  beyond schema compliance: require evidence-backed causal chains, separate customer
  impact from inferred mechanism, produce executable validation checks, propose concrete
  remediation, identify contradicting evidence, and compare competing hypotheses.
  Evaluate changes against the synthetic incident fixtures before changing the default
  prompt version. The same evaluation should cover claim-support prompt quality.

## Application Logging Plan

Add useful pipeline visibility without logging secrets or raw incident evidence by
default. (Carried forward; not part of slice #8.)

- [ ] Add structured application logs for analysis-run queue/start/finish, stage
  attempt/success/failure, artifact/chunk counts, timeline candidate counts, RCA
  provider/model invocation, validated RCA output counts, citation-integrity outcomes,
  claim-support outcomes, and hypothesis review decisions.
- [ ] Keep API keys, bearer headers, raw provider envelopes, full prompts, raw evidence
  bodies, and citation snippets out of default logs.
- [ ] Decide whether local development also needs an explicit opt-in payload logging mode
  for raw prompts and model completions. If added, default it off and document the
  data-exposure risk.
- [ ] Add focused logging regressions and run backend validation.
