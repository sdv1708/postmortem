# Feature flag audit — faceted_search_v2
- 2026-05-14T14:02:03Z enabled (false -> true) by the automated progressive-rollout job, not a human.
- Scope jumped straight to 100% of search traffic; the staged 5% / 25% steps were skipped due to a misconfigured rollout guardrail.
- Behavior change: adds a facet aggregation over brand.keyword to every search query.
- brand.keyword is not indexed for aggregation, so each faceted query holds a database connection roughly 8x longer than the non-faceted path.
- Rollback: disabling the flag reverts to the non-faceted query path immediately, with no deploy required.
