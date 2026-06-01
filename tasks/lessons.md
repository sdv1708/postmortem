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
