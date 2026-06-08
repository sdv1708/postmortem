# Deploy v184 — 2026-05-09
- 14:28 UTC: v184 deployed to the api-gateway fleet (canary skipped, full rollout)
- Changes: bump ORM 5.2 -> 5.4 and refactor database connection pool acquisition
- Pool max_connections left unchanged at 40 in the application config
- No database schema migration shipped in this release
- Rollback plan: redeploy the v183 image, roughly 3 minutes
