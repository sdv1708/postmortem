# Explicit Structured Tables With Relational EvidenceRefs

The MVP schema will use explicit structured output tables such as timeline_events, hypotheses, action_items, postmortems, and evidence_refs. EvidenceRefs are relational rather than JSON-only because the citation panel, evaluation aggregation, and referential integrity depend on querying exact artifact line references.

A generic claims table is deferred until duplication proves it is useful. Workspace ownership can exist as a single default Workspace stub with foreign keys for future compatibility, but workspace switching, scoped auth, and workspace management are not part of the MVP.
