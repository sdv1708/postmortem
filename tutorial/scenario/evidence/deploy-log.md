# Deploy v4.7.1 — 2026-05-14
- Started 14:00:12Z, completed 14:04:50Z (rolling deploy across 8 pods).
- Change: adds the faceted_search_v2 code path, guarded by a feature flag defaulting OFF.
- No schema migrations; no connection-pool size or timeout configuration was changed.
- The faceted_search_v2 flag was shipped OFF and was NOT enabled by this deploy.
