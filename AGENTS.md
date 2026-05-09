# AGENTS.md — Postmortem Agent

## What this project is
An AI-powered incident postmortem agent that turns production incident evidence
into structured, evidence-backed postmortems. Ingests logs, stack traces,
deployment notes, and incident notes.

---

## Workflow Orchestration

### Plan Mode
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- Write the plan to `tasks/todo.md` with checkable items before touching code
- Check in with the user before starting implementation
- If something goes sideways mid-task: STOP and re-plan. Do not keep pushing.
- Use plan mode for verification steps, not just building

### Subagent Strategy
- Use subagents to keep the main context window clean
- Offload research, exploration, and parallel analysis to subagents
- One focused task per subagent — no mixing concerns
- For complex problems, throw more compute at it via subagents

### Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules that prevent the same mistake from recurring
- Review `tasks/lessons.md` at the start of each session for relevant context

### Verification Before Done
- Never mark a task complete without proving it works
- Run tests, check logs, demonstrate correctness
- Ask: "Would a staff engineer approve this PR?"
- Mark items complete in `tasks/todo.md` as you go

### Elegance Check
- For non-trivial changes: pause and ask "is there a more elegant solution?"
- If a fix feels hacky: implement the elegant solution instead
- Skip for simple, obvious fixes — do not over-engineer

### Autonomous Bug Fixing
- When given a bug report: fix it. Do not ask for hand-holding.
- Point at logs, errors, failing tests — then resolve them
- Fix failing CI tests without being told how

---

## Task Management

1. **Plan first** — write plan to `tasks/todo.md` with checkable items
2. **Check in** — verify plan with user before implementation
3. **Track progress** — mark items complete as you go
4. **Explain changes** — high-level summary at each step
5. **Document results** — add review section to `tasks/todo.md`
6. **Capture lessons** — update `tasks/lessons.md` after any correction

---

## Core Principles

- **Simplicity first** — make every change as simple as possible
- **No laziness** — find root causes, no temporary fixes
- **Minimal impact** — only touch what's necessary
- **No fake progress** — never mark something done until it actually works

---

## Agent Skills

issue_tracker: github
domain_docs: CONTEXT.md, docs/adr/
triage_labels:
  needs-evaluation: needs-evaluation
  waiting-on-reporter: waiting-on-reporter
  ready-for-agent: ready-for-agent
  ready-for-human: ready-for-human
  wont-fix: wont-fix