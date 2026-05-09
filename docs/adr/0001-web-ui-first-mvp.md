# Web UI First for the MVP

The MVP will use a focused web UI as the primary Review Surface, with CLI workflows deferred to Milestone 2 as a thin wrapper over the same service layer. This is a deliberate tradeoff: a CLI would be natural for backend engineers, but the product differentiator depends on engineers clicking from generated claims back to exact evidence line ranges, and that proof is strongest in a review-oriented interface.

The frontend stack is Next.js, shadcn/ui, and TanStack Query. Status states are part of the product experience, not just backend bookkeeping, so Analysis Run states need human-readable names and copy that makes progress, uncertainty, and failure understandable.
