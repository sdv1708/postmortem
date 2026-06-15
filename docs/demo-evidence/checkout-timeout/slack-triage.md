# Slack triage transcript

2026-06-10T14:08:12Z maya-oncall: Checkout submit is timing out. I see 504s from payment-authorizer.
2026-06-10T14:09:31Z ian-payments: PayLink public status is green, but our provider latency graph jumped after 14:06.
2026-06-10T14:12:05Z maya-oncall: Current canary is 25 percent on checkout-api 2026.06.10.4.
2026-06-10T14:13:18Z priya-release: That build enabled syncPaymentCapture and max_attempts=3 for payment auth.
2026-06-10T14:16:40Z ian-payments: Retries are stacking. Even approved auths are taking 8-9 seconds.
2026-06-10T14:20:14Z maya-oncall: Recommend rollback. Provider may be slow, but canary made the checkout path wait synchronously.
2026-06-10T14:21:02Z priya-release: Rolling back canary to 0 percent now.
2026-06-10T14:27:44Z maya-oncall: p95 back near 1 second. Retry queue still draining.
2026-06-10T14:35:38Z ian-payments: Queue drained. Checkout success rate back above 99 percent.
