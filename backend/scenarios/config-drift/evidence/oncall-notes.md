On-call notes (sev3), scribe: ray
- Latency alarms fired at 22:13 on product listing endpoints.
- Response caching was disabled by config revision r512 at 22:10.
- The change came from an automated sync, not a human deploy.
- Re-enabling the cache at 22:28 restored latency within two minutes.
