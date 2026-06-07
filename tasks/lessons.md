- For light-themed UI, do not set `color-scheme: light dark` unless every native
  form control has been checked in dark browser mode. Force explicit light
  input/select/textarea colors when the app background and text are light.
- Buttons should use a shared button class with border, height, font weight,
  hover, focus, shadow, and disabled states so links and buttons read as
  clickable controls.
- Do not present partially implemented work as ready for manual testing. If the
  frontend acceptance criteria are not wired yet, say that explicitly and keep
  implementing before asking the user to test the slice.
- In a polyglot repo, scope language-specific `.gitignore` rules. A stock Python
  `.gitignore` ignores `lib/`, which silently matched `frontend/src/lib/` and
  kept the (untracked) frontend API client out of git — the app could not build
  from a clean checkout. When adding a Python `.gitignore` to a repo that also
  has JS/TS source, anchor build-output rules (e.g. `/build/`) or add negations
  for source paths, and verify with `git check-ignore -v <path>`.
- The `scripts/e2e.sh` cleanup trap does not reliably reap the Next.js dev
  server child tree when the script is killed (SIGTERM/timeout), leaving stale
  `next-server` processes holding :3000 that make the next run fail instantly
  with empty output. Run the suite in the foreground and, if a run is
  interrupted, `pkill -9 -f next-server` (and uvicorn) before retrying. Confirm
  ports are free first.
- Treat incident lifecycle and evidence locking as separate concerns. Locking an
  artifact preserves run citations; it does not answer whether an entire
  incident should be archived or deleted from the workspace dashboard.
- A schema-compatibility helper that inspects columns before issuing DDL still
  races across process startups. Isolate each `ALTER TABLE` in its own
  transaction and ignore only the database's duplicate-column error.
- Validate configured provider URL schemes when constructing an authenticated
  client. Reject unsupported protocols before creating requests with bearer
  authorization headers.
- When a model documents an exactly-one relational owner invariant, encode it
  at the database layer. For legacy SQLite upgrades, validate existing rows and
  install equivalent write triggers because SQLite cannot append table checks.
- A mutation is not complete if only its success path is visible. Surface
  command failures near the affected Review Surface action, even when no
  optimistic cache update needs reverting.
- A schema-valid RCA response can still be analytically shallow. Treat prompt
  quality as an evaluated phase: distinguish causal mechanism from customer
  impact and require concrete validation and remediation before tuning prompts.
- `scripts/e2e.sh` hardcodes `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, which
  only exists in the Linux/CI image. On this Windows dev box the Playwright
  browsers live in the default `~/AppData/Local/ms-playwright`, so run the suite
  without overriding that env var: start uvicorn (`POSTMORTEM_DEV_BYPASS=1`) on
  :8000 and `next start` on :3000 (the prod build bakes the API base to
  localhost:8000), wait on `/healthz` + `/incidents`, then `npx playwright test`.
  Tear both servers down and delete `backend/_e2e.db` afterward.
- Citation integrity (deterministic: artifact/line/snippet) and claim support
  (semantic) are separate verifier passes (ADR 0014). Keep the deterministic
  pass ORM-free and behind a swappable `CitationVerifier` boundary; a broken
  citation is flagged with a warning code, never deleted and never a run failure
  (ADR 0015). Reuse the same `"\n".join` snippet resolution the claim-generating
  stages use so a `verified` status actually proves source-of-truth equality.
- When a previously no-op pipeline stage starts calling the LLM, every existing
  full-pipeline test that seeded a single-response `FakeLLMClient` for an earlier
  stage will now exhaust it and the run fails late (hypotheses persisted from
  stage 3 stay, so content assertions pass "accidentally" while the run is
  actually failed). Don't paper over it by seeding more raw LLM responses — give
  the new stage a swappable verifier boundary and inject a deterministic fake
  (shared `tests/_fakes.py`) into `AnalysisService`/`PipelineStageRunner`, and
  assert `run.status == "succeeded"` in the shared seed helpers so the failure
  can't hide. Expect the same when stage 5 (drafting) becomes real in #10.
- Resolution for #10: stage 5 (`drafting_postmortem`) was implemented as a
  *deterministic* composer (`DeterministicPostmortemComposer`), not an LLM call.
  That choice does double duty — it satisfies ADR 0026 ("no new factual claims
  after citation verification") by construction, and because it makes no
  `complete()` call it never exhausts a seeded `FakeLLMClient`, so the prior
  full-pipeline tests needed no changes. When a stage only *composes* existing
  verified outputs, prefer a deterministic implementation behind a swappable
  Protocol (so an LLM template stays a future drop-in) over wiring the LLM in and
  paying the seeded-response tax. The structured Postmortem stores only the
  composed narrative (summary + lessons); the factual sections stay their own
  rows so EvidenceRefs remain the citation source of truth, and clean-vs-audit
  export filtering is a render-time concern off the final `support_status`, not
  baked into the persisted row.
