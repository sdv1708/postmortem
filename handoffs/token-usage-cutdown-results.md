# Token-usage cutdown — results & changes

**Date:** 2026-06-30
**Branch:** `main` (uncommitted at time of writing)
**Scope decided:** safe levers only — no change to which evidence is selected; the
deterministic trust floor remains the authority (ADR 0010).

---

## TL;DR

The only lever that **actually reduced tokens** on the measured workload was a
**prompt reorder that enables OpenAI prefix caching** (Phase 2). Output caps
(Phase 1) and judge trims (Phase 3) are correct, low-risk hygiene but realize
little on this model/incident — they are cost/runaway **guardrails**, not active
reduction. This was a measurement-driven conclusion, not an assumption.

---

## How it was measured

Real run against the configured provider (`gpt-4o-mini`), one **config-drift
incident** (the handoff's multi-pass benchmark), reading per-role
`ModelCallRecord.usage` via run diagnostics. Demo/replay reports 0 tokens, so a
live provider run is required. Harness: `scratchpad/baseline_tokens.py`
(in-process; fresh sqlite, `expire_on_commit=False`, full six-stage pipeline with
the real client — no fakes).

> **Caveat — runs are not token-for-token comparable.** Model nondeterminism
> changes the hypothesis count, which changes how many falsifier and
> support-verifier calls happen, which changes run totals. Compare **structural**
> quantities (`cached_tokens`, per-call output vs cap), not grand totals.

### Spend profile (baseline, before changes)

| role | calls | input | cached | output | total |
|---|---:|---:|---:|---:|---:|
| incident_facts | 1 | 1,094 | 0 | 223 | 1,317 |
| builder | 1 | 1,213 | 0 | 535 | 1,748 |
| falsifier | 2 | 2,914 | 0 | 495 | 3,409 |
| ranker | 1 | 0 | 0 | 0 | 0 (deterministic) |
| **TOTAL** | **5** | **5,221** | **0** | **1,253** | **6,474** |

- **Input ≈ 81% of tokens, output ≈ 19%.**
- Falsifier dominates input: it re-sends the full evidence once per hypothesis.
- `cached_tokens = 0` everywhere — caching supported by the provider but not firing.

---

## The savings (measured)

### Prefix caching now engages (the real win)

Root cause of `cached_tokens = 0`: the falsifier prompt led with the **variable**
per-hypothesis text, so its repeated calls shared no cacheable prefix. After
reordering to **stable-content-first** (system + full evidence + timeline), then
the per-hypothesis challenge:

| run | falsifier calls | falsifier `cached_tokens` |
|---|---:|---:|
| before | 2 | **0** |
| after | 3 | **2,304** |

OpenAI bills cached prefix tokens at ~50% off, so ~2,304 cached ≈ **~1,150
token-equivalents saved on that run**, and the saving **grows with multi-pass
depth** (every hypothesis after the first reuses the evidence prefix). This is the
headline result. Builder and incident_facts were already evidence-first, so they
cache across *repeated* runs of the same incident (e.g. the multi-pass vs
builder-only A/B, which runs one incident twice).

### Output caps — guardrail, not reduction

Per-role `max_tokens` is now sent to the provider. Measured outputs sit **under**
the caps on this model (builder peaked 759 vs cap 1,280; falsifier ≤290 vs 448),
so realized output savings ≈ 0. Value is **bounded worst-case cost** and never
runaway generation — not a cut on typical runs.

### Judge trims — only matter on the eval path / large incidents

Evidence fed to the judge capped 40 → 24, and the judge is **skipped entirely when
the deterministic floor already fails** the run (no point grading a rejected run;
ADR 0010 — judges never gate pass/fail). Saves a whole judge call on failing runs;
no effect on the analysis-run measurement above.

---

## Code changes

| File | Change |
|---|---|
| `backend/postmortem/falsification.py` | **Phase 2.** Reordered `build_falsification_prompt`: stable evidence/timeline first, per-hypothesis challenge + instruction last, so a prefix-caching provider reuses the shared block. Output semantically identical. |
| `backend/postmortem/llm.py` | **Phase 1.** Added optional `max_output_tokens` to the `LLMClient.complete` Protocol; `OpenAICompatibleLLMClient` emits `max_tokens`. `Fake`/`Offline` accept-and-ignore. Default `None` = unchanged. |
| `backend/postmortem/provenance.py` | **Phase 1.** `ROLE_OUTPUT_TOKEN_CAPS` (incident_facts 384, builder 1280, falsifier 448, support_verifier 256, judges 1024) + `output_token_cap_for(role)`; `RecordingLLMClient` forwards the kwarg. Distinct from the ReasoningBudget ceiling, which only *aborts* after the fact. |
| `backend/postmortem/services/stages.py`, `incident_facts.py`, `verification.py`, `evaluation.py` | **Phase 1.** Each model call site passes its role's cap into `complete(max_output_tokens=...)`. |
| `backend/postmortem/services/evaluation.py` | **Phase 3.** `_MAX_JUDGE_EVIDENCE` 40 → 24; skip the judge when the floor fails. |
| `backend/postmortem/scenarios.py` | Test/replay fakes updated for the new `complete` signature. |

### Behavior change to flag
Floor-failed **incident evaluations no longer receive an advisory judge score**.
ADR 0010-defensible (floor is the authority), but it is a visible product change.

---

## Verification

- **Backend suite green** (`backend/.venv/Scripts/python.exe -m pytest -q`, exit 0,
  ~423 tests). The `complete()` signature change rippled to every client/fake; all
  updated, `None` default preserves behavior.
- **Real provider re-run**: caching confirmed (`cached_tokens` 0 → 2,304), builder
  output 759 < 1,280 cap (no truncation → no Targeted Repair retry).

---

## Deferred (still the biggest input lever)

Input is 81% of spend and the largest remaining cut is **evidence selection /
trimming** instead of inlining every full artifact body — explicitly deferred
because it can drop a citation's source line and must be validated against the
deterministic citation floor. Falsifier fan-out reduction (one call/hypothesis) is
the multi-pass value and should be touched only as a last resort.
