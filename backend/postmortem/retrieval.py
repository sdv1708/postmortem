from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AnalysisRun, Artifact, EvidenceChunk, TimelineEvent


RETRIEVAL_STRATEGY_VERSION: Final[str] = "deterministic-chunk-artifact-1"


@dataclass(frozen=True)
class RetrievalResult:
    """Candidate evidence selected for a claim-generating pipeline stage."""

    artifacts: tuple[Artifact, ...]


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
        for chunk in session.scalars(
            select(EvidenceChunk)
            .where(EvidenceChunk.run_id == run.id)
            .order_by(EvidenceChunk.sequence.asc())
        ):
            if chunk.artifact_id in by_id and chunk.artifact_id not in ordered_ids:
                ordered_ids.append(chunk.artifact_id)
        selected = tuple(by_id[artifact_id] for artifact_id in ordered_ids)
        return RetrievalResult(artifacts=selected or tuple(artifacts))
