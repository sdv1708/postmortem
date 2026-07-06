On-call thread (sev2), scribe: dana
14:08 — pages firing for search 503s during the flash sale; assuming the 14:00 deploy, considering a rollback.
14:16 — deploy rollback started but 503s continued, so the deploy is likely not the trigger.
14:29 — noticed faceted_search_v2 flipped on at 14:02, two minutes AFTER the deploy started; the facet query looks expensive.
14:35 — last week's sale had HIGHER traffic (3200 rps) and was fine, so raw traffic volume is not sufficient on its own.
14:41 — disabled faceted_search_v2; the connection pool drained and 503s fell within about three minutes.
14:48 — fully recovered. Follow-ups: the flag skipped its staged rollout, and the facet field is not indexed for aggregation.
