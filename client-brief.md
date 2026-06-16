# Client Brief: Multi-Agent RCA Recommendation

## Recommendation

We should consider incorporating a bounded multi-agent review flow into the postmortem agent. The goal is not to make the product feel more complex or to add an agent framework for its own sake. The goal is to improve the credibility of the generated root-cause analysis by separating evidence interpretation, hypothesis generation, challenge, and final synthesis into distinct review passes.

From a product perspective, this is the right next step if we want the MVP to move from "AI-generated postmortem draft" toward "defensible incident reasoning assistant."

## Why This Matters

The current product already has a strong evidence-backed foundation: uploaded artifacts, structured analysis runs, citations, deterministic verification, scenario replay, and Markdown postmortem output. That is enough to make the product useful.

The remaining gap is reasoning quality. A single model pass can produce a valid answer that is still too shallow. It may cite the right logs, but fail to clearly distinguish:

- the triggering event
- the amplifying conditions
- the actual failure mechanism
- what evidence rules out weaker explanations
- what is still uncertain
- what follow-up evidence would make the conclusion stronger

A multi-agent design gives us a product-friendly way to improve this without losing the auditability that makes the system trustworthy.

## Suggested Multi-Agent Flow

The recommended approach is a small, controlled set of agents or reasoning passes:

1. **Evidence Mapper**
   Reviews the uploaded evidence and extracts important facts, timestamps, symptoms, metrics, deployment references, and notable gaps.

2. **Hypothesis Builder**
   Produces candidate root-cause hypotheses using only the evidence available in the run. Each hypothesis must cite supporting and contradicting evidence.

3. **Skeptic / Falsifier**
   Challenges each hypothesis by asking: what else could explain this, what evidence is weak, what is missing, and what conclusion is being overstated?

4. **Citation Auditor**
   Verifies that cited artifact references are valid, line ranges exist, snippets match the source material, and unsupported claims are marked as assumptions.

5. **Synthesis Writer**
   Produces the final postmortem narrative from the verified hypotheses, warnings, uncertainties, and action items.

This should be implemented as a deterministic orchestration pattern, not as a free-form agent chat. Each pass should have a narrow job, structured inputs, structured outputs, and recorded metadata.

## Product Value

This addition would make the MVP easier to defend in front of technical users because it creates a visible reasoning process instead of a single opaque model answer.

Expected benefits:

- Better root-cause quality through explicit challenge and synthesis
- Clearer uncertainty handling when evidence is incomplete
- Stronger differentiation from generic AI writing tools
- More credible demos because the system can explain why it believes one cause over another
- Better evaluation hooks because each reasoning pass can be tested independently
- Safer postmortems because unsupported claims can be flagged before the final draft

## Important Constraint

The multi-agent approach must preserve the product's central promise: every important claim must remain traceable to source evidence.

The system should not allow agents to introduce uncited facts during synthesis. The final writer should compose from verified intermediate outputs, not invent new incident claims. If a claim cannot be supported, the product should label it as an assumption or an open question.

## Recommended MVP Version

For the first version, I recommend a minimal three-pass flow:

1. Hypothesis Builder
2. Skeptic / Falsifier
3. Synthesis Writer

The existing deterministic citation verifier should remain outside the model and continue to act as the hard quality floor. This gives us the main product benefit without overbuilding orchestration too early.

## Success Criteria

This feature should be considered successful if a generated postmortem can answer:

- What most likely happened?
- What evidence supports that conclusion?
- What evidence weakens or complicates it?
- What alternatives were considered?
- What remains uncertain?
- What follow-up evidence would make the conclusion stronger?

If the system can answer those questions clearly, the postmortem becomes much easier for an engineer, founder, or reviewer to trust.

## Product Manager Position

My recommendation is to pursue this as the next reasoning-quality improvement, but keep it bounded. We should not market this as "multi-agent AI" for novelty. We should use it as an internal architecture pattern that makes the product more reliable, more reviewable, and more defensible.

The customer-facing promise should stay simple: the product generates evidence-backed postmortems and shows its work.
