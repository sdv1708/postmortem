# Incident notes: Checkout timeout spike

- 2026-06-10T14:06:00Z Customer support reports elevated complaints: shoppers can add items to cart but checkout hangs after submitting payment.
- 2026-06-10T14:08:00Z On-call confirms checkout API p95 latency rose from 420 ms to 8.7 s.
- 2026-06-10T14:11:00Z Error budget burn alert fired for checkout-api in production.
- 2026-06-10T14:13:00Z Initial hypothesis is payment-provider latency because checkout waits on payment authorization before returning order confirmation.
- 2026-06-10T14:18:00Z Counter-signal: payment-provider status page still reports healthy API availability.
- 2026-06-10T14:21:00Z Checkout deploy 2026.06.10.4 was rolled back from 25 percent canary to 0 percent.
- 2026-06-10T14:27:00Z p95 latency improved to 1.1 s after rollback, but a smaller failure rate remained for retries.
- 2026-06-10T14:35:00Z Mitigation complete: retry queue drained and checkout success rate returned above 99.2 percent.

Open questions:
- Did the deploy increase synchronous calls to the payment provider?
- Was the provider actually degraded for our merchant account even though the public status page stayed green?
- Did retry behavior amplify the latency into customer-visible failures?
