# Async Analysis Run API Model

Analysis Runs are asynchronous at the product and API level: clients create a run, observe its Run Status, and fetch results when the run succeeds. This does not require Python `asyncio`; the MVP can execute runs with a simple synchronous worker internally while preserving the external lifecycle needed for retries, progress, observability, and later queue adoption.

The MVP API contract is status polling rather than server-sent events or streamed output. Polling keeps the first implementation simple while preserving a clean path to richer status updates later.
