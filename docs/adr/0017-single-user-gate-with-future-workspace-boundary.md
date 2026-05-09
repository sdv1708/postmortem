# Single-User Gate With Future Workspace Boundary

The MVP will use a Single-User Gate rather than multi-user auth or enterprise RBAC. Incidents, Artifacts, Analysis Runs, and Postmortems should still belong to a Workspace internally so future tenancy has a clear ownership boundary.

This keeps sensitive incident data out of a fully open app without spending the MVP on permission UX, organization management, or role modeling.
