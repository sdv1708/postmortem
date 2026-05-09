# Resource APIs With Explicit Command Endpoints

The MVP API will use resource-oriented endpoints for incidents, artifacts, analysis runs, stage events, and postmortem results, plus explicit Command Endpoints for actions that start work or record decisions. Creating an Analysis Run, reviewing a hypothesis, adding a Reviewer Note, and rendering Markdown are commands because they have side effects beyond simple resource retrieval.

This keeps the API legible to the frontend and future CLI without pretending that long-running analysis is ordinary CRUD.
