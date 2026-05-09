# Split Citation Integrity From Claim Support Verification

The MVP verifier will split citation verification into two passes: CitationIntegrityVerifier and ClaimSupportVerifier. CitationIntegrityVerifier is deterministic and checks artifact existence, line ranges, and exact snippet matches; ClaimSupportVerifier is semantic and classifies whether the cited evidence supports, partially supports, or does not support the Major Claim.

This keeps the trust-critical addressability contract mechanically testable while still allowing LLM-assisted support judgment where language understanding is required.
