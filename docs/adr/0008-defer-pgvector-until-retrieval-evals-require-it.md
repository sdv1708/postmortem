# Defer pgvector Until Retrieval Evals Require It

The first MVP path will not require pgvector. Artifacts and Chunks will be stored in Postgres with preserved line numbers, while Retrieval Strategies start with deterministic approaches such as keyword, time-window, and source-type selection behind a swappable interface.

This deliberately cuts against the initial stack preference because the product's first proof is citation correctness, not semantic search. pgvector remains a likely future option, but it should be added when scenario evaluations show deterministic retrieval is failing in ways vector retrieval can address.
