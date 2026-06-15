# Deploy notes: checkout-api 2026.06.10.4

- 2026-06-10T13:52:00Z Build 2026.06.10.4 promoted to production canary at 10 percent.
- 2026-06-10T14:04:00Z Canary increased to 25 percent for checkout-api.
- Change included payment authorization refactor: checkout-api now calls payment-authorizer synchronously before order row commit.
- Feature flag `checkout.syncPaymentCapture` enabled for 25 percent canary traffic.
- Retry policy changed from max_attempts=1 to max_attempts=3 for payment authorization.
- No database schema migration shipped in this release.
- 2026-06-10T14:21:00Z Rollback started: checkout-api 2026.06.10.4 canary reduced from 25 percent to 0 percent.
- 2026-06-10T14:24:00Z Rollback completed. Previous stable build 2026.06.09.2 serving 100 percent.

Rollback note:
- Latency dropped after rollback, but the retry queue continued to drain for roughly 10 minutes.
