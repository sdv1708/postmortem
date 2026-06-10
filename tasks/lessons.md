- Adding scenario fixtures broke a slice-10 Playwright test that clicked
  `getByRole("button", { name: "Seed demo scenario" }).first()`: with three
  scenarios listed, `.first()` selected a different (alphabetically-first) card.
  When a list can grow, never select list controls by `.first()` in e2e — scope
  the click to the specific row (`getByRole("listitem").filter({ hasText: ... })`).
  Growing fixtures is a normal future event; order-dependent selectors are a trap.
- Slice #11 (#12) evaluation independence: to run scenario fixtures "independently
  of product Incident data", the EvaluationRunner materializes each run in an
  ephemeral in-memory SQLite engine (StaticPool + check_same_thread=False so the
  in-memory DB is shared across the session), computes ORM-free check results from
  it, disposes the engine, and persists only the EvaluationRun row to the real
  session. This leaves zero product Incident/Artifact rows behind and avoids
  cascade/lock headaches from deleting a seeded incident. Keep the deterministic
  check floor (citation integrity, required outputs, timeline ordering,
  multiplicity) and the LLM judge as separate recorded fields — citation validity
  is the deterministic `verifier_status` count, never the judge (ADR 0010). Do not
  bake judge scores into fixtures (unlike the RCA replay): a pre-baked grade makes
  the judge dimension a tautology, so the judge is null offline and injected as a
  fake only in tests.
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
- Recurrence of the polyglot `.gitignore` pitfall (#11): the stock Python
  `.gitignore` rule `*.log` silently matched the canonical scenario's `.log`
  evidence fixtures (`backend/scenarios/.../evidence/*.log`), so the demo would
  fail to seed from a clean checkout (the loader raises on the missing file).
  When adding file-based fixtures, `git check-ignore -v` every new asset and add
  a scoped negation (`!backend/scenarios/**/*.log`) for source files that a
  transient-artifact rule would otherwise swallow. Fixture evidence is source.
- Slice #10 (#11) demo determinism: the canonical scenario ships its own
  fakes/replay (ADR 0011) — `replay/rca.json` cites evidence by `source_name`,
  resolved to seeded artifact ids at seed time, plus claim-support overrides — so
  the founder-demo trust path runs offline and identically every time. Keep the
  replay honest in Experiment Metadata (`model_provider=scenario-replay:<id>`, a
  distinct verifier version) so a replayed run is never mistaken for a live model.
  Validate the fixture at load time (missing/empty files, unknown source refs,
  out-of-range line cites, and strict RCA schema) so a broken demo fails fast
  before any product rows are created instead of half-seeding a failed run.
- Never leave local credential scratch files in the repo root. If a token-like
  file appears during development, delete it, add a scoped ignore rule if the
  filename is likely to recur, and rotate the credential because writing it to
  disk is already exposure.
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
- A "merged" slice may not be on `main`. Slice 11 (#12) was reviewed/extended and
  committed on `feature/issue-12-evaluation-runs` (it even added a retrieval module
  and the insufficient-evidence stub) but `main` was never fast-forwarded. Before
  building a blocked-by slice, `git log --all` and check the actual files on disk;
  branch the next slice off the branch that truly contains the dependency, not
  off `main`. The reviewer's extensions (e.g. an `insufficient-evidence` scenario
  stub, eval checks that tolerate emptiness) are part of your starting point.
- Slice #12 (#13) refusal: model "insufficient evidence" as a *deterministic
  product detection*, not a scenario flag. The drafting composer sets
  `evidence_sufficiency = insufficient` when no hypothesis is evidence-backed
  (`assumption == False` count is 0), which generalizes past the fixture to any
  sparse/all-uncited run. The gaps + next-validation-steps it emits are procedural
  statements about evidence *completeness*, not incident facts, so a deterministic
  composer may emit them without violating ADR 0026. Surface it across every layer
  (persist on the Postmortem, read model, schema, Markdown export, Review Surface
  banner) and give evaluation a *positive* refusal check that fails both ways
  (refusal scenario must refuse; normal scenario must not spuriously refuse) plus
  an `insufficient_evidence` Warning Code — tolerating emptiness in the existing
  checks is not the same as proving the system refused.
