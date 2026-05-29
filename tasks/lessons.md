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
