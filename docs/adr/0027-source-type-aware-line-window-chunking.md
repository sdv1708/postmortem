# Source-Type-Aware Line-Window Chunking

The MVP Chunking Strategy will use source-type-aware line windows with 15% overlap to reduce missed boundary events. Logs should be chunked with timestamp-aware windows, stack traces should stay together when possible, human notes should preserve paragraph or heading boundaries, and deploy notes can usually stay as small release-entry chunks.

Chunks are retrieval aids, not durable citation targets. EvidenceRefs must point to artifact line ranges because chunk boundaries may change across strategy versions.
