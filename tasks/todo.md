# Polish Markdown Export Quality

- [x] Inspect the exported clean Markdown file.
- [x] Add guardrails so a requested clean/audit export cannot silently download mismatched content.
- [x] Trim incident titles at creation/export boundaries to remove trailing whitespace in generated docs.
- [x] Rename deterministic unknowns in Markdown from "Lessons learned" to "Open questions" so output reads credibly.
- [x] Verify backend export tests and frontend typecheck.

## Review

The inspected file was named `*-clean.md` but contained `Export mode: audit`,
the audit warning note, and an unsupported impact claim. Backend clean/audit
rendering was already covered, so the UI now refuses to download an export if
the response mode, filename, or Markdown mode header does not match the requested
button. Also trimmed incident title/summary on create and changed presentation
of deterministic hypothesis unknowns from "Lessons learned" to "Open questions".

Verification:
- `tests/test_api_incidents.py tests/test_drafting.py tests/test_api_postmortem.py`: 27 passed.
- Full backend suite: 218 passed, 1 existing FastAPI/Starlette deprecation warning.
- Frontend `npm run typecheck`: passed.

# Grill Client Brief: Bounded Multi-Pass RCA

- [x] Read the client brief, domain glossary, relevant ADRs, and current pipeline.
- [x] Resolve the falsification pass's authority and canonical domain language.
- [x] Resolve orchestration, persistence, claim-generation, and verification boundaries.
- [x] Resolve product presentation, evaluation criteria, failure behavior, and MVP scope.
- [x] Update `CONTEXT.md` inline as domain terms are agreed.
- [x] Record an ADR only if the final architecture decision meets the ADR threshold.
- [x] Add a review section summarizing decisions and documentation changes.

## Review

Resolved architecture:
- Keep the existing framework-neutral, DB-persisted orchestration; consider
  LangGraph only if dynamic branching or mid-stage pause/resume becomes necessary.
- Keep six visible stages. Stage 2 extracts incident facts; stage 3 performs
  bounded causal analysis: build, falsify, add at most two alternatives, verify,
  and produce an ordinal advisory ranking.
- The system never declares a root cause. Humans review hypotheses and finalize
  a structured causal account with exactly one Failure Mechanism and optional
  repeatable Triggers and Amplifying Conditions.
- Conclusions are evidence-governed and immutable. Discrepancies are append-only,
  make conclusions disputed, and may lead to a new immutable superseding conclusion.
- Builder, falsifier, ranker, and support verifier are separate Reasoning Roles
  with structured handoffs, even when they share one configured model.
- Incremental citation checks and provisional semantic support protect ranking;
  final audit stages remain the visible trust checkpoints.
- Runtime repair is bounded and deterministic. Missing challenge coverage or
  exhausted repair budgets fail causal analysis rather than publishing degraded output.
- Evaluation compares the multi-pass flow with a builder-only baseline using
  structured scenario expectations plus token and latency constraints.

No ADR was added during the interview. The architecture is substantial enough
to warrant one when implementation starts, but its exact persistence schema and
migration sequence should be recorded with that implementation plan rather than
guessed during domain discovery.

# Publish PRD: Bounded Multi-Pass Causal Analysis

- [x] Re-read the domain glossary, current pipeline, review surface, and evaluation architecture.
- [x] Identify deep implementation modules and testing boundaries.
- [x] Check GitHub for an existing equivalent PRD issue.
- [x] Draft the feature PRD using canonical domain language.
- [x] Publish the PRD to GitHub with the `ready-for-agent` label.
- [x] Record the published issue in this review section.

## Review

Published [GitHub issue #26](https://github.com/sdv1708/postmortem/issues/26):
`PRD: Bounded multi-pass causal analysis and human root cause conclusions`.

Verification:
- No equivalent open issue was found.
- The published body is 30,599 characters.
- The issue has the `ready-for-agent` label.
- The local source is `tasks/bounded-multi-pass-causal-analysis-prd.md`.

# Publish Vertical Slices for PRD #26

- [x] Read the parent PRD and current issue tracker state.
- [x] Draft independently testable end-to-end slices.
- [x] Get user approval for granularity, dependencies, and AFK/HITL classification.
- [x] Publish 13 slices in dependency order with real blocker references.
- [x] Verify parent links, blocker links, and `ready-for-agent` labels.
- [x] Record the published issue map in this review section.

## Review

Published under parent [#26](https://github.com/sdv1708/postmortem/issues/26):

- [#27](https://github.com/sdv1708/postmortem/issues/27) Extract run-level incident facts
- [#28](https://github.com/sdv1708/postmortem/issues/28) Challenge every initial RCA hypothesis
- [#29](https://github.com/sdv1708/postmortem/issues/29) Mark automated output as a provisional postmortem
- [#30](https://github.com/sdv1708/postmortem/issues/30) Add one bounded alternative-expansion round
- [#31](https://github.com/sdv1708/postmortem/issues/31) Produce an evidence-explained advisory ranking
- [#32](https://github.com/sdv1708/postmortem/issues/32) Expose reasoning and retrieval provenance
- [#33](https://github.com/sdv1708/postmortem/issues/33) Finalize a supported human root cause conclusion
- [#34](https://github.com/sdv1708/postmortem/issues/34) Flag an immutable conclusion as disputed
- [#35](https://github.com/sdv1708/postmortem/issues/35) Review remediation proposals after finalization
- [#36](https://github.com/sdv1708/postmortem/issues/36) Qualify partial and critically challenged conclusions
- [#37](https://github.com/sdv1708/postmortem/issues/37) Bound causal analysis and repair invalid outputs
- [#38](https://github.com/sdv1708/postmortem/issues/38) Compare multi-pass analysis with a builder-only baseline
- [#39](https://github.com/sdv1708/postmortem/issues/39) Supersede a disputed conclusion

Verification:
- Every issue references parent #26.
- Every issue has the `ready-for-agent` label.
- Every dependency references a real published issue.
- No unresolved blocker placeholders remain.
- Parent #26 was not modified or closed.
