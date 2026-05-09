# Swappability Only for Exercised MVP Boundaries

The MVP will define explicit interfaces only for components that are exercised by the MVP pipeline or needed for near-term experiments: AnalysisService, LLMClient, ChunkingStrategy, RetrievalStrategy, ClaimVerifier, PostmortemRenderer, RunExecutor, and EvaluationRunner. Swappability must be demonstrated with fakes or alternate implementations in tests, not just claimed through unused abstractions.

Embedding model, vector store, and agent-orchestration abstractions are deferred until those concerns enter the working product path. This keeps the architecture testable without turning the first milestone into framework plumbing.
