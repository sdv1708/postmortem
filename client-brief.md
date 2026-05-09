# Client Brief: Postmortem Agent

## Engineering Philosophy

This should be built like a real product, not a toy demo.

- Vertical slices over horizontal layers — ship one end-to-end flow before broadening surface area
- Testable interfaces — major components sit behind abstractions, not direct SDK calls
- Evidence-backed AI outputs — generated claims must be traceable to source material
- Simple architecture first — only add complexity when something simpler is shown to fail
- Explicit tradeoff experiments — major decisions should be A/B-able
- Observability from the start, not retrofitted

These are directions, not laws. If a tradeoff cuts against one of them, surface it explicitly.

---

## Product Summary

An AI-powered incident postmortem agent that turns production incident evidence into structured, evidence-backed postmortems.

The system ingests logs, stack traces, deployment notes, and human incident notes. The MVP focuses on uploaded or pasted evidence. External integrations (GitHub, Slack, Sentry, Datadog, Grafana, PagerDuty, Linear, Jira) are explicitly out of scope for the MVP and on the roadmap for later.

## Target Users

**Primary:** Startup backend engineers, technical founders/CTOs, small engineering teams without mature SRE processes.

**Secondary:** Platform engineers, DevOps/SRE engineers at smaller teams, open-source maintainers.

## Core Problem

Postmortems are hard because incident evidence is scattered, noisy, incomplete, and time-sensitive. Teams write postmortems too late, rely on memory, miss accurate timelines, and produce vague remediation items.

## MVP Goal

Given incident metadata and evidence, generate:

1. Chronological incident timeline
2. Impact analysis
3. Ranked root-cause hypotheses (multiple when evidence is ambiguous)
4. Supporting and contradicting evidence per hypothesis
5. Concrete remediation/action items
6. Structured Markdown postmortem

## Core Differentiator

Every important AI-generated claim cites original evidence with: artifact ID, source name, line range, snippet, and confidence score. Unsupported claims are explicitly marked as assumptions, not silently dropped.

This is the thing that makes the product not-a-demo. If the citations don't actually work — meaning a reader can click a claim and trace it back to a real log line — the differentiator collapses.

---

## Stack Preferences

These are starting points, not commitments. Open to challenge.

- **Frontend:** Next.js + TypeScript + Tailwind + shadcn/ui
- **Backend:** FastAPI + Pydantic + SQLAlchemy
- **Database:** PostgreSQL + pgvector
- **Queue:** Redis + Celery or Dramatiq
- **Storage:** local filesystem first, MinIO/S3 later
- **AI orchestration:** linear pipeline first, LangGraph if/when justified
- **Evaluation:** benchmark incident dataset + rule checks + LLM-as-judge

## Architectural Constraint: Swappability

Major components should be swappable through interfaces — the project should not hard-code itself around one model, one orchestration framework, or one retrieval method. The components I expect to need this for:

- LLM provider
- Embedding model
- Chunking strategy
- Retrieval strategy
- Agent orchestration
- Evidence verifier
- Vector store
- Postmortem template
- Evaluation suite

The exact interface shapes are not yet decided.

---

## MVP Scope

**In scope:**
- Incident CRUD
- Evidence upload/paste
- Evidence normalization and chunking
- Analysis run creation
- Timeline extraction
- RCA hypothesis generation
- Evidence verification
- Action item generation
- Markdown postmortem generation
- Basic experiment tracking

**Out of scope for MVP:**
- Production remediation / autonomous infra changes
- Datadog / PagerDuty replacement
- Full observability platform
- Enterprise RBAC
- External integrations (those are roadmap items)

---

## Open Questions

Things I have not yet decided and want to think through:

- How citation confidence is actually computed (LLM self-rating vs retrieval similarity vs hybrid verifier)
- Whether the MVP should ship with a UI or stay CLI-first
- How to generate the synthetic incident dataset and what failure modes it should cover
- Where the line is between "still MVP" and "Milestone 2"
- What the minimum eval signal needs to look like before any of this is trustworthy
- Async vs sync analysis runs in the first version
- How to enforce architectural invariants (linting, tests, code review)

---

## What Success Looks Like

When this is shown to a technical founder, the things that should land:

1. The citations actually work end-to-end on a real-feeling incident
2. The system admits uncertainty rather than fabricating confident answers
3. The architecture is genuinely swappable — not just claimed to be
4. The synthetic incidents look like real production failures, not toy examples
