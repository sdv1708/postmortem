# Handoff — next focus: token-usage cutdown

**Date:** 2026-06-30
**Repo:** `D:\postmortem` (sdv1708/postmortem)
**Branch:** `feature/incident-floor-evaluation` (PR [#56](https://github.com/sdv1708/postmortem/pull/56), open)
**Working tree:** clean as of the last commit `dc5d27a`.

> Goal for the next session: **reduce LLM token usage** across the analysis
> pipeline and the new evaluation judges, without weakening the deterministic
> trust floor or the multi-pass quality the project is built to demonstrate.

---

## 1. Where things stand (context, not to redo)

The just-completed thread was about the **`/evaluations` experience** and adding
**real-incident evaluation**. Details live in the artifacts — read these rather
than re-deriving:

- PR [#56](https://github.com/sdv1708/postmortem/pull/56) — full description of the change.
- Commits `216e655` (incident floor eval + dashboard revamp) and `dc5d27a`
  (reference-free incident judge). Use `git show <sha>` / `git log -p`.
- Methodology decided this session (not yet in an ADR — see open item §6):
  - **Demo scenarios** → graded against authored ground truth, multi-pass vs
    builder-only A/B, with the reference-based judge.
  - **Real incidents** → deterministic *floor* (ground-truth-free checks) plus a
    **reference-free** judge scored against the incident's own cited evidence
    (never a gold answer; measures groundedness/consistency/honesty, not
    correctness). See `GROUND_TRUTH_FREE_CHECKS` and `LLMIncidentJudge` in
    `backend/postmortem/evaluation.py`.

State of evals is **good**; do not reopen it unless token work requires touching it.

---

## 2. The actual task: token-usage cutdown — orientation

### Where tokens are spent
Every live model call goes through `LLMClient.complete(system, user)` in
`backend/postmortem/llm.py` (`OpenAICompatibleLLMClient`; provider-agnostic,
OpenAI-compatible). Call sites (the "Reasoning Roles" + judges):

- `backend/postmortem/rca.py` — hypothesis **builder** (largest context: evidence + retrieval).
- `backend/postmortem/falsification.py` — **falsifier**, one call *per hypothesis* (+ bounded expansion round). This is the multi-pass cost (8 calls vs 5 for builder-only on config-drift).
- `backend/postmortem/ranking.py` — advisory **ranker** (has a *deterministic* default ranker; LLM ranker optional).
- `backend/postmortem/verification.py` — claim-**support verifier**, per major claim.
- `backend/postmortem/incident_facts.py` — stage-2 facts extractor.
- `backend/postmortem/drafting.py` — postmortem composer (check whether this is template/deterministic vs LLM).
- `backend/postmortem/evaluation.py` — **judges** (`build_judge_prompt`, `build_incident_judge_prompt`). The incident judge feeds up to `_MAX_JUDGE_EVIDENCE = 40` cited snippets (`services/evaluation.py`) — a direct prompt-size lever.

### Existing control surface — and the big finding
`backend/postmortem/reasoning.py` already implements **`ReasoningBudget`**
(ADR 0043) with per-role ceilings. **But the token ceilings are currently OFF:**

```
max_retrieval_chunks_per_role = 200   # a lot of context per role
max_input_tokens_per_role     = 0     # 0 == unbounded (DISABLED)
max_output_tokens_per_role    = 0     # 0 == unbounded (DISABLED)
max_calls_per_role            = 12
```

So the plumbing to bound input/output tokens exists and is enforced when set
(see `reasoning.py` ~lines 260-310), but defaults make it a no-op. Turning these
on (with sensible values) and/or lowering the retrieval-chunk cap is likely the
highest-leverage, lowest-risk first move. The budget is stamped into Experiment
Metadata (`reasoning_budget`), so changes are observable per run.

### Other concrete levers to evaluate
- **Retrieval volume** (`retrieval.py`, `chunking.py`): 200 chunks/role is the
  upstream driver of input tokens. Tighter retrieval / smaller top-k / dedup.
- **Prompt assembly**: the builders concatenate evidence text; trim, summarize,
  or cite-by-reference instead of inlining full snippets.
- **Prompt caching**: no cache-control usage was found in the role modules.
  Static system prompts + repeated evidence are good caching candidates if the
  provider supports it.
- **Judge prompts**: cap/trim evidence fed to judges (`_MAX_JUDGE_EVIDENCE`),
  and consider skipping the judge on trivially-failing floor runs.
- **Falsifier fan-out**: one call per hypothesis dominates multi-pass cost;
  batching or capping hypotheses considered is a quality/cost tradeoff.

### Measurement (important caveat)
- Per-call usage is recorded on **`ModelCallRecord.usage`**; summed by
  `_usage_tokens` in `backend/postmortem/services/evaluation.py` and surfaced as
  `total_tokens` on eval runs and `RunStageEvent.usage`.
- **Demo scenarios run on offline replay → `total_tokens` is 0** (no live call).
  You cannot measure real token usage from the demo path. To get real numbers you
  must run against a **configured provider** (set `POSTMORTEM_LLM_API_KEY`) on a
  real incident, then read `ModelCallRecord.usage`. Build any token-cutdown
  measurement around real runs, not the replay fixtures.

---

## 3. Key files (quick map)
- Budgets/gates: `backend/postmortem/reasoning.py`
- LLM client: `backend/postmortem/llm.py`
- Roles: `rca.py`, `falsification.py`, `ranking.py`, `verification.py`, `incident_facts.py`, `drafting.py`
- Retrieval/chunking: `backend/postmortem/retrieval.py`, `chunking.py`
- Judges + rubrics: `backend/postmortem/evaluation.py`
- Eval service (usage summing, incident eval): `backend/postmortem/services/evaluation.py`
- Config (provider, keys): `backend/postmortem/config.py`
- Relevant ADRs: `docs/adr/0043-bounded-causal-analysis-budget-and-targeted-repair.md`, `0021` (observability/usage), `0025` (experiment metadata), `0038` (reasoning/retrieval provenance), `0044` (multi-pass vs baseline).

---

## 4. Build / test / run (from project memory)
- Backend tests: use **`backend/.venv`** python — `cd backend && .venv/Scripts/python.exe -m pytest -q`. Full suite is ~5.5 min, 423 passing on this branch.
- Frontend: `cd frontend && npx tsc --noEmit && npx next build`. (ESLint is not configured under Next 16; `next lint` is broken — rely on tsc+build.)
- Boot backend locally (no auth): `POSTMORTEM_DEV_BYPASS=true backend/.venv/Scripts/python.exe -m uvicorn postmortem.app:app --port <port>` (module is `postmortem.app:app`, NOT `postmortem.main`).
- To measure real tokens: also set `POSTMORTEM_LLM_API_KEY` (redacted; not in repo) so calls actually hit a provider.
- E2E (`frontend/e2e`) has a known dev_bypass principal quirk — see project memory; avoid depending on it for verification.

---

## 5. Conventions worth keeping
- Deterministic floor is the trust authority; **judges never decide citation
  validity or pass/fail** (ADR 0010). Any token cut must not move quality gating
  into the LLM.
- Honesty-in-UI guardrail: incident evals visibly mark the judge as
  *reference-free* and tokens as n/a on replay. Preserve that framing.
- Commit message footer used in this repo: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; PR bodies end with the Claude Code generated-by line.

---

## 6. Open follow-ups carried over (optional, not blocking token work)
1. **Human-finalized-conclusion judge** — the other label-free signal discussed:
   judge the AI's provisional draft against a reviewer-**finalized**
   `RootCauseConclusion` once one exists. Separate piece; not started.
2. **ADR for evaluation methodology** — document the demo=ground-truth-A/B vs
   incident=floor+reference-free split. Not started.

---

## 7. Suggested skills for the next session
- **`/diagnose`** — if chasing *where* tokens go, treat it as a measurable
  regression/profiling loop: reproduce a real run, measure `ModelCallRecord.usage`
  per role, change one lever, re-measure.
- **`Plan` agent / EnterPlanMode** — token cutdown spans several roles + budgets;
  get a plan approved before editing, given quality tradeoffs.
- **`/code-review`** (or `/review`) before opening/finishing a PR for the cuts.
- **`claude-api`** — only if the work touches provider-level features
  (prompt caching, max_tokens params, token counting). Note: provider here is
  **OpenAI-compatible**, not the Anthropic SDK, so most provider-specific Claude
  guidance won't apply directly.
- **`/run`** — to exercise a real run against a configured provider for actual
  token numbers (replay fixtures report 0).

---

## 8. Sensitive info
None included. `POSTMORTEM_LLM_API_KEY` and any provider credentials are **not**
in this document or the repo — set them via environment when measuring real runs.
