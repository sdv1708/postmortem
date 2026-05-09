# Immutable Artifacts After Analysis Use

Artifacts become immutable once they are included in an Analysis Run. Users may delete or replace evidence before running analysis, but corrections after analysis require creating a new Artifact and running analysis again.

This protects EvidenceRefs because citation line ranges and snippets only remain trustworthy if the artifact body cannot change underneath an existing run.
