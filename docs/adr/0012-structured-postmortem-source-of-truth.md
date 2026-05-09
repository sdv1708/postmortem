# Structured Postmortem as Source of Truth

The MVP will store generated postmortem output as structured data rather than treating Markdown as the source of truth. Timeline events, hypotheses, impact claims, remediation items, and section summaries can each carry EvidenceRefs, verifier statuses, or assumption labels in a way that is testable and UI-addressable.

Markdown is rendered on request as an export artifact for sharing, copying, or archiving. The system should not parse exported Markdown back into product truth.
