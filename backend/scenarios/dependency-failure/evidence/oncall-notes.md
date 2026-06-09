On-call notes (sev2), scribe: lee
- Checkout 502s started around 09:06 with payments provider timeouts.
- The provider status page confirmed an upstream incident at 09:04.
- Our circuit breaker opened at 09:07, shedding load until the provider recovered.
- No deploy went out today, so a local code regression is unlikely.
- We lack retry and backoff on charge.create, which amplified user-visible failures.
