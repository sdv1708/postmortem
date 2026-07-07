# Results, learnings & observations

A running engineering retrospective for the Postmortem Agent: what we changed, what
actually moved the needle, and the non-obvious lessons. Raw numbers and diffs live in
the referenced docs/PRs — this file captures the **why** and the **learnings** so we
don't relearn them.

---

## 1. Cost & caching — measurement beat intuition

**The headline result: the only lever that actually reduced tokens was a prompt reorder
that turns on the provider's prefix cache.** Everything else we shipped for "cost" is a
guardrail, not a reduction.

- **Spend profile:** input ≈ **81%** of tokens, output ≈ 19%. The falsifier dominates
  input because it re-sends the full evidence once per hypothesis (multi-pass fan-out).
- **How caching was used:** OpenAI (and compatible providers) automatically cache a
  *stable prefix* of the prompt and bill it at ~50% off — but only if the repeated calls
  actually **share a leading byte-identical block**. Our falsifier led with the
  *variable* per-hypothesis text, so every call had a different prefix and
  `cached_tokens = 0`. Reordering the prompt to **stable-content-first** (system + full
  evidence + timeline, then the per-hypothesis challenge last) made the shared block
  cacheable. Measured `cached_tokens`: **0 → 2,304** on one run, and the saving **grows
  with fan-out** — every hypothesis after the first reuses the evidence prefix. Builder
  and incident_facts were already evidence-first, so they cache across *repeated runs* of
  the same incident (e.g. the multi-pass vs builder-only A/B).
- **What did NOT move tokens (this workload):** provider-side `max_output_tokens` caps —
  the model naturally emits under them (builder peaked 759 vs a 1,280 cap), so realized
  savings ≈ 0. They are a **runaway-cost guardrail**, not a cut. Same for the judge
  evidence trim (40→24) and skip-judge-on-floor-fail — they only matter on the eval path
  / very large incidents.

**Learnings**
- **Order every role's prompt stable-content-first.** It's free, semantically identical
  output, and it's the single biggest realized win. Put the system prompt + full evidence
  + timeline at the top; put the per-call variable text and instruction at the bottom.
- **Distinguish reductions from guardrails.** Output caps and judge trims are correct
  hygiene but bound worst-case cost; they don't cut typical spend. Don't count them as
  savings.
- **Measure per-role, compare structural quantities.** Single live runs are noisy — model
  nondeterminism changes the hypothesis count, which changes how many falsifier/verifier
  calls fire, which changes run totals. Compare `cached_tokens` and per-call output vs
  cap, **not** grand totals. Demo/replay runs report 0 tokens, so a real-provider run is
  required.

**Details / raw tables:** [handoffs/token-usage-cutdown-results.md](../handoffs/token-usage-cutdown-results.md),
memory `token-cutdown-findings`, harness `token-measurement-harness`.
**Still the biggest unclaimed lever:** input is 81% of spend; the real remaining cut is
*selecting/trimming evidence* instead of inlining every full artifact body — deferred
because it can drop a citation's source line and must be validated against the
deterministic citation floor.

---

## 2. Reasoning depth — the model was (almost) never the limit

We repeatedly diagnosed "the analysis is too shallow" and it was **wiring, not model
capability**, four times running.

- `gpt-4o-mini` genuinely sat under the depth bar. But `gpt-5.4-mini` clears the full 7/7
  `tutorial/EXPECTED_REASONING.md` checklist **after four plumbing fixes**, not prompt
  magic: GPT-5/o-series param handling (`temperature` omitted, `max_completion_tokens`),
  a falsifier `item`→`description` output alias, truncation of over-cap proposals instead
  of failing the run, and promoting falsification evidence-gaps into the composed
  postmortem. (PRs #63–66; memory `tutorial-depth-tuning`.)

**Learning:** when output looks shallow, suspect the plumbing first — provider param
incompatibilities, schema-alias mismatches, silent truncation, and composer omissions all
*look* like "the model isn't smart enough." Fix the pipe before blaming the model.

---

## 3. Hypothesis cardinality — ceilings, not quotas

- Capping hypotheses to 4 (#67) compressed the tutorial scenario's depth: the model merged
  the deploy + Elasticsearch red herrings and dropped the traffic-surge amplifier. We
  raised the ceiling to 5 (#68) as a **quality-gated cap**, with the prompt explicitly
  forbidding padding to reach the number.
- **Key observation from 3 live runs:** raising the cap changed nothing — `gpt-5.4-mini`
  consistently emits **4** hypotheses even with 5 slots and *merges* the two red herrings
  (defensible: they share the recovery-on-flag-disable rebuttal). **The cap was never the
  binding constraint; the model's own consolidation is.** In 1 of 3 runs it dropped the ES
  red herring entirely — that drop, not the merge, was the real defect.
- The fix (#69, prompt `rca-5`) was **prompt, not number**: *never drop a strongly-invited
  wrong explanation that has its own distinct counter-evidence.* After it, ES was surfaced
  3/3 runs.

**Learnings**
- A cap should be a **ceiling with a quality bar, not a target.** Raising a ceiling does
  not make the model fill it — models self-limit by their own sense of parsimony.
- **To change coverage, change the prompt's must-surface rule, not the max.** The count
  knob and the coverage knob are different knobs.
- Grade **multi-run stability**, not a single run — the ES drop only showed up in 1 of 3.

---

## 4. The deterministic trust floor is sacred

Every optimization above was constrained to **never touch the deterministic citation
floor** (ADR 0010): caching reorders bytes but not semantics; output caps never truncate
valid JSON on this model; judges never gate pass/fail (a floor-failed run is simply not
graded). Result: **100% verified citations across every live run** we measured, including
the token-optimized and cap-changed ones. The floor is what lets us optimize aggressively
elsewhere without eroding trust.

**Learning:** having one inviolable, deterministic authority makes every *other* part of
the system safe to tune. Name it, defend it, and route optimizations *around* it.

---

## 5. Product / UX — a plain-language layer over precise domain terms

The Review Surface was accurate but expert-only: bare jargon badges (`advisory rank`,
`assumption`, `material challenge`), all-caps micro-labels, single-file upload. The fix
(#70, #71) added a **presentation glossary + hover/focus tooltips** and reworded labels
for humans (`Why this rank` → `How the agent ranked this`; `Counterclaims` → `Points
against it`) — **without renaming the domain model or schema.** Bulk upload lets a whole
evidence bundle land in one action.

**Learning:** keep the domain vocabulary precise in the code and data; translate it *at
the presentation edge*. Don't dumb down the model to make the UI friendly.

---

## 6. Process observations

- **An in-process measurement harness paid for itself.** Fresh sqlite,
  `expire_on_commit=False`, the real six-stage pipeline with the real provider, reading
  per-role `ModelCallRecord.usage`. Without it, every "did that help?" was a guess.
- **Squash-merge trap:** a commit pushed to a branch *after* its PR is squash-merged is
  NOT on `main`. Branch fresh off `origin/main` and cherry-pick. (Bit us on #69 and #71.)
- **Workspace tenancy:** scenario seeds land in the seeder's workspace; to see them in the
  local UI you must seed *through the browser's BFF* so the visitor workspace matches
  (ADR 0017), or you get a spurious "incident not found".
- **Don't persist secrets to reach real data.** The prod token is paste-per-session; for
  visual work use `POSTMORTEM_DEV_BYPASS=1` + a seeded scenario (deterministic replay, no
  key needed).

---

## Change log (source of the above)

| Theme | PRs / refs |
|---|---|
| Token cutdown + caching | [token-usage-cutdown-results.md](../handoffs/token-usage-cutdown-results.md) |
| Depth wiring fixes | #63, #64, #65, #66 |
| Hypothesis cap → quality-gated ceiling | #67, #68 |
| Never-drop red herring (`rca-5`) | #69 |
| Review Surface polish | #70, #71 |

Architecture map & undocumented decisions awaiting ADRs:
[handoffs/architecture-reference-and-decisions-handoff.md](../handoffs/architecture-reference-and-decisions-handoff.md).
