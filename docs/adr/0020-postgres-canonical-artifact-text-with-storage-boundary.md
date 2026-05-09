# Postgres Canonical Artifact Text With Storage Boundary

The MVP will store canonical line-addressable artifact text in Postgres rather than relying on local filesystem objects as the primary evidence store. This keeps EvidenceRefs, snippet verification, and tests close to the same transactional source of truth.

Artifact Storage should still be modeled as a boundary so cloud blob storage can be added later for larger files, binary uploads, or hosted deployments without changing citation semantics.
