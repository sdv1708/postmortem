from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AnalysisRun, Artifact, EvidenceChunk, TimelineEvent


RETRIEVAL_STRATEGY_VERSION: Final[str] = "deterministic-chunk-artifact-1"


@dataclass(frozen=True)
class RetrievedChunk:
    """An ordered reference to one chunk a retrieval strategy selected (ADR 0038).

    A reference only — chunk id, owning artifact, source order, and line span —
    never the chunk text, so a persisted Retrieval Trace built from these never
    duplicates Sensitive Evidence (PRD user stories 70-71).
    """

    chunk_id: str
    artifact_id: str
    sequence: int
    line_start: int
    line_end: int


@dataclass(frozen=True)
class RetrievalResult:
    """Candidate evidence selected for a claim-generating pipeline stage.

    ``artifacts`` is the candidate set the stage hands to the model (RCA cites
    durable Artifact line ranges, not chunk ids, ADR 0027). ``chunks`` is the
    ordered Chunk references the strategy actually examined, retained so the stage
    can persist a Retrieval Trace that shows retrieved-but-uncited evidence
    (ADR 0038, PRD user story 70); ``query`` describes what was retrieved. Both
    default to empty so existing strategies/fakes that only set ``artifacts``
    remain valid.
    """

    artifacts: tuple[Artifact, ...]
    chunks: tuple[RetrievedChunk, ...] = ()
    query: str = ""


class RetrievalStrategy(Protocol):
    """Swappable retrieval boundary for deterministic stage inputs (ADR 0008/0009).

    Retrieval is separate from chunking: chunks are persisted by stage 1, while a
    retrieval strategy chooses which evidence should be handed to a later stage.
    The MVP strategy is deterministic and non-vector, but tests can inject an
    alternate strategy behind this same interface.
    """

    @property
    def version(self) -> str: ...

    def select_for_rca(
        self,
        *,
        session: Session,
        run: AnalysisRun,
        artifacts: Sequence[Artifact],
        timeline_events: Sequence[TimelineEvent],
    ) -> RetrievalResult: ...


class DeterministicChunkArtifactRetrievalStrategy:
    """Select RCA evidence from the run's persisted chunks, preserving source order.

    The result is still Artifact rows because the RCA prompt cites durable
    Artifact line numbers, not mutable chunk ids (ADR 0027). Chunks are used to
    determine the candidate set; if a legacy run has no chunks, the strategy
    falls back to the immutable run artifact set so existing data remains
    analyzable.
    """

    version: Final[str] = RETRIEVAL_STRATEGY_VERSION

    def select_for_rca(
        self,
        *,
        session: Session,
        run: AnalysisRun,
        artifacts: Sequence[Artifact],
        timeline_events: Sequence[TimelineEvent],
    ) -> RetrievalResult:
        by_id = {artifact.id: artifact for artifact in artifacts}
        ordered_ids: list[str] = []
        retrieved: list[RetrievedChunk] = []
        for chunk in session.scalars(
            select(EvidenceChunk)
            .where(EvidenceChunk.run_id == run.id)
            .order_by(EvidenceChunk.sequence.asc())
        ):
            if chunk.artifact_id not in by_id:
                continue
            retrieved.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    artifact_id=chunk.artifact_id,
                    sequence=chunk.sequence,
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                )
            )
            if chunk.artifact_id not in ordered_ids:
                ordered_ids.append(chunk.artifact_id)
        selected = tuple(by_id[artifact_id] for artifact_id in ordered_ids)
        query = (
            f"RCA candidate selection over {len(retrieved)} run chunks "
            f"across {len(ordered_ids) or len(artifacts)} artifacts"
        )
        return RetrievalResult(
            artifacts=selected or tuple(artifacts),
            chunks=tuple(retrieved),
            query=query,
        )
