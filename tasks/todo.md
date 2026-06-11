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
