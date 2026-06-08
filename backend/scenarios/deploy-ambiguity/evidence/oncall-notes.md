On-call notes (sev2), scribe: dana
- Error spike began around 14:32, about two minutes after the v184 rollout finished.
- Unclear whether v184 caused it: the pool acquisition refactor is suspicious, but max_connections was unchanged and there was no schema migration.
- A cache node also evicted at 14:33 under memory pressure, which could have pushed read load onto the database independently of the deploy.
- Resizing the connection pool to 80 at 14:40 resolved the 500s, which does not by itself prove the original root cause.
- No upstream provider incident was found, but we did not check every dependency.
