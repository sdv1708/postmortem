# Single Default LLM Provider Behind an Interface

The MVP will use one configured default LLM provider behind an LLMClient interface, with fake or replay clients for tests. Analysis Runs and Evaluation Runs should record provider, model name, and Prompt Version metadata so outputs remain auditable and experiments can be compared.

The product will not expose provider switching in the MVP. This proves the service boundary needed for later swappability without spending the first milestone on provider-matrix behavior that is not central to the citation-backed postmortem experience.
