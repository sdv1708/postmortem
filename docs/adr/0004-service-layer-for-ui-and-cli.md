# Shared Analysis Service Layer

The web UI routes and future CLI must call into the same AnalysisService-style service layer rather than duplicating orchestration logic in transport-specific code. This adds a small boundary up front, but it preserves the Milestone 2 CLI path and keeps the product's core behavior testable independent of HTTP or command-line entrypoints.
