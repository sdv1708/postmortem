from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..chunking import ChunkingStrategy, SourceAwareLineWindowChunker
from ..drafting import (
    DeterministicPostmortemComposer,
    HypothesisDigest,
    PostmortemComposer,
    PostmortemComposerContext,
)
from ..falsification import (
    FALSIFICATION_PROMPT_VERSION,
    FALSIFICATION_SCHEMA_VERSION,
    MAX_PROPOSED_HYPOTHESES,
    Falsifier,
    HypothesisChallengeOutput,
    HypothesisToChallenge,
    LLMFalsifier,
)
from ..incident_facts import (
    INCIDENT_FACTS_PROMPT_VERSION,
    INCIDENT_FACTS_SCHEMA_VERSION,
    IncidentFactExtractor,
    LLMIncidentFactExtractor,
)
from ..llm import LLMClient, OfflineLLMClient
from ..logging import log_event
from ..models import (
    ActionItem,
    AnalysisRun,
    Artifact,
    Counterclaim,
    EvidenceChunk,
    EvidenceRef,
    Hypothesis,
    HypothesisChallenge,
    ImpactClaim,
    Incident,
    ModelCallRecord,
    Postmortem,
    RetrievalTrace,
    TimelineEvent,
    RunArtifact,
)
from ..provenance import (
    FALSIFICATION_RETRIEVAL_STRATEGY,
    ROLE_BUILDER,
    ROLE_FALSIFIER,
    ROLE_INCIDENT_FACTS,
    ROLE_RANKER,
    ROLE_SUPPORT_VERIFIER,
    STAGE2_ROLES,
    STAGE3_ROLES,
    SUPPORT_INPUT_STRATEGY,
    RecordingLLMClient,
)
from ..ranking import (
    ADVISORY_RANKING_SCHEMA_VERSION,
    AdvisoryRanker,
    DeterministicAdvisoryRanker,
    RankingCandidate,
)
from ..rca import (
    MAX_INITIAL_HYPOTHESES,
    PROMPT_VERSION,
    RCA_SCHEMA_VERSION,
    RcaEvidenceRef,
    RcaGenerationOutput,
    build_rca_prompt,
)
from ..retrieval import (
    DeterministicChunkArtifactRetrievalStrategy,
    RetrievalStrategy,
    RetrievedChunk,
)
from ..timestamps import parse_timestamp
from ..verification import (
    CLAIM_SUPPORT_PROMPT_VERSION,
    CLAIM_SUPPORT_SCHEMA_VERSION,
    CitationIntegrityStatus,
    CitationTarget,
    CitationVerifier,
    ClaimSupportStatus,
    ClaimSupportVerifier,
    ClaimToVerify,
    DeterministicCitationIntegrityVerifier,
    LLMClaimSupportVerifier,
)


logger = logging.getLogger("postmortem.stages")


def _as_naive_utc(value: datetime | None) -> datetime | None:
    """Convert an aware datetime to naive UTC; pass through None/naive.

    Timeline timestamps are normalized to UTC (ADR 0019). Storing them naive
    keeps reads uniform across SQLite (which drops tzinfo) and Postgres, so
    chronological sorting never compares an aware value against a naive one.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class PipelineStageRunner:
    """Deterministic stage work for an Analysis Run (slice #5).

    This is the `stage_runner` the StagedRunExecutor invokes per stage. It holds
    the session so a stage can persist its structured output before the next
    stage starts (ADR 0026); the AnalysisService still owns the transaction
    boundary (ADR 0004). No LLM is involved yet — stages 1 and 2 do real
    deterministic work, and the remaining stages stay as no-ops until later
    slices wire them up.

    A stage returns an outcome dict ({"warning_codes": [...]}); the executor
    records it on the Run Stage Event and treats a raised exception as a stage
    failure (ADR 0029).
    """

    def __init__(
        self,
        session: Session,
        chunker: ChunkingStrategy | None = None,
        llm_client: LLMClient | None = None,
        verifier: CitationVerifier | None = None,
        claim_support_verifier: ClaimSupportVerifier | None = None,
        postmortem_composer: PostmortemComposer | None = None,
        retrieval_strategy: RetrievalStrategy | None = None,
        incident_fact_extractor: IncidentFactExtractor | None = None,
        falsifier: Falsifier | None = None,
        advisory_ranker: AdvisoryRanker | None = None,
    ) -> None:
        self._session = session
        self._chunker = chunker or SourceAwareLineWindowChunker()
        # Default to the offline client so deterministic stages still complete a
        # run when no provider is configured; real runs inject a configured
        # client (ADR 0011). The client is wrapped in a RecordingLLMClient so every
        # Reasoning Role that talks to a model funnels through it transparently and
        # each completion's reproducibility metadata (hashes + usage, never prompt
        # or response text) is captured for Model Call Records (ADR 0038). The
        # default roles below are constructed with this wrapped client, so builder,
        # falsifier, and support-verifier calls are all captured.
        self._llm_recorder = RecordingLLMClient(llm_client or OfflineLLMClient())
        self._llm = self._llm_recorder
        # Monotonic provenance sequence per run so the diagnostics view can order
        # Model Call Records and Retrieval Traces in execution order. Keyed by run
        # id to stay correct if one runner instance serves more than one run.
        self._prov_seq: dict[str, int] = {}
        self._chunk_refs_cache: dict[str, list[RetrievedChunk]] = {}
        # The incident-facts extractor is a swappable Reasoning-Role boundary
        # (ADR 0033): stage 2 produces run-level Impact Claims through it before
        # any causal interpretation. The default uses the configured LLM; the
        # offline client yields no impact so a run still completes.
        self._fact_extractor = incident_fact_extractor or LLMIncidentFactExtractor(self._llm)
        # The falsifier is a separate Reasoning-Role boundary (ADR 0034): stage 3
        # challenges every initial RCA Hypothesis through it before it can
        # succeed. The default uses the configured LLM; with the offline client
        # the builder produces no hypotheses, so the falsifier is never invoked.
        self._falsifier = falsifier or LLMFalsifier(self._llm)
        # The advisory ranker is the fourth Reasoning-Role boundary (ADR 0037): the
        # last substep of stage 3 orders every challenged hypothesis into one
        # ordinal Advisory Hypothesis Ranking. The MVP default is deterministic and
        # makes no model call, so a replayed/offline run ranks without a provider;
        # an LLM-backed ranker can be injected behind the same interface.
        self._ranker = advisory_ranker or DeterministicAdvisoryRanker()
        # The citation verifier is a swappable boundary (ADR 0014 / 0009); the
        # MVP default is the deterministic integrity pass.
        self._verifier = verifier or DeterministicCitationIntegrityVerifier()
        # The semantic claim-support verifier is the second swappable verifier
        # boundary (ADR 0014); the MVP default judges support with the configured
        # LLM. It is only consulted when there are Major Claims to evaluate, so an
        # offline run with no hypotheses never calls a model.
        self._claim_support = claim_support_verifier or LLMClaimSupportVerifier(self._llm)
        # The Postmortem template is a swappable boundary (client brief, ADR 0009).
        # The MVP default composes deterministically from the verified structured
        # outputs and makes no model call, so it introduces no new factual claims
        # (ADR 0026) and never consumes an LLM response the RCA stage seeded.
        self._composer = postmortem_composer or DeterministicPostmortemComposer()
        # Retrieval is a swappable deterministic boundary (ADR 0008/0009/0031).
        # The default uses persisted chunks to select artifact candidates while
        # preserving Artifact line numbers as the citation source of truth.
        self._retrieval = retrieval_strategy or DeterministicChunkArtifactRetrievalStrategy()
        self._artifacts_cache: dict[str, list[Artifact]] = {}

    def __call__(self, stage: str, attempt: int, run: AnalysisRun) -> dict | None:
        if stage == "normalizing_evidence":
            return self._normalize_evidence(run)
        if stage == "extracting_incident_facts":
            return self._extract_incident_facts(run)
        if stage == "analyzing_causal_hypotheses":
            return self._generate_rca(run)
        if stage == "verifying_citations":
            return self._verify_citations(run)
        if stage == "drafting_postmortem":
            return self._draft_postmortem(run)
        if stage == "flagging_unsupported_claims":
            return self._flag_unsupported_claims(run)
        return None

    def _normalize_evidence(self, run: AnalysisRun) -> dict | None:
        """Chunk every included Artifact into source-aware line windows.

        Chunks are retrieval aids, not citation targets (ADR 0027), but they
        are persisted as the inspectable output of this stage (ADR 0026). The
        timeline stage and all EvidenceRefs still cite Artifact line ranges.
        """
        self._clear_chunks(run)
        artifacts = self._run_artifacts(run)
        warning_codes: list[str] = []
        total_chunks = 0
        sequence = 1
        for artifact in artifacts:
            chunks = self._chunker.chunk(artifact.source_type, artifact.source_name, artifact.body)
            total_chunks += len(chunks)
            if not chunks:
                warning_codes.append("chunk_count_anomaly")
            for chunk in chunks:
                self._session.add(
                    EvidenceChunk(
                        run_id=run.id,
                        artifact_id=artifact.id,
                        sequence=sequence,
                        source_type=chunk.source_type,
                        source_name=chunk.source_name,
                        line_start=chunk.line_start,
                        line_end=chunk.line_end,
                        text=chunk.text,
                        chunking_strategy=self._chunker.version,
                    )
                )
                sequence += 1
        if total_chunks == 0:
            warning_codes.append("chunk_count_anomaly")
        self._session.flush()
        warning_codes = _dedupe(warning_codes)
        log_event(
            logger,
            logging.INFO,
            "stage_normalizing_evidence_completed",
            run_id=run.id,
            artifact_count=len(artifacts),
            chunk_count=total_chunks,
            warning_codes=",".join(warning_codes) if warning_codes else None,
        )
        return {"warning_codes": warning_codes}

    def _extract_incident_facts(self, run: AnalysisRun) -> dict | None:
        """Extract run-level incident facts: Timeline Events + Impact Claims.

        Incident facts are produced before any causal interpretation (ADR 0033).
        Timeline Events are extracted deterministically from timestamped lines,
        each citing its exact Artifact line (ADR 0024); normalized timestamps sort
        first chronologically and inferred/uncertain timestamps follow in source
        order, flagged (ADR 0019). Run-level Impact Claims are then generated once
        for the whole run through the IncidentFactExtractor — independent of how
        many RCA Hypotheses the later causal stage produces (PRD user stories 1-2).

        Idempotent across the single stage retry (ADR 0029): any timeline events
        and impact claims left by a failed prior attempt are cleared first, so a
        retry never duplicates them or collides on sequence numbers.
        """
        self._clear_timeline(run)
        # Idempotent across the single stage retry (ADR 0029): clear stage-2
        # provenance before the extractor regenerates it.
        self._clear_provenance(run, STAGE2_ROLES)
        artifacts = self._run_artifacts(run)
        candidates: list[_Candidate] = []
        for artifact in artifacts:
            for offset, line in enumerate(artifact.body.split("\n")):
                parsed = parse_timestamp(line)
                if parsed is None:
                    continue
                line_number = offset + 1
                candidates.append(
                    _Candidate(
                        artifact=artifact,
                        line_number=line_number,
                        line_text=line,
                        original_ts_text=parsed.original_text,
                        normalized_ts=parsed.normalized,
                        uncertain=parsed.inferred,
                    )
                )

        ordered = _order_candidates(candidates)
        for sequence, candidate in enumerate(ordered, start=1):
            event = TimelineEvent(
                run_id=run.id,
                sequence=sequence,
                # Store naive UTC so the value round-trips identically on SQLite
                # and Postgres; comparisons/sorting in later slices never mix
                # naive and aware datetimes. UTC tz is re-attached on API read.
                normalized_ts=_as_naive_utc(candidate.normalized_ts),
                original_ts_text=candidate.original_ts_text,
                uncertain=candidate.uncertain,
                description=candidate.description,
            )
            event.evidence_refs.append(
                EvidenceRef(
                    artifact_id=candidate.artifact.id,
                    source_name=candidate.artifact.source_name,
                    line_start=candidate.line_number,
                    line_end=candidate.line_number,
                    snippet=candidate.line_text,
                    confidence_score=0.5 if candidate.uncertain else 1.0,
                )
            )
            self._session.add(event)
        self._session.flush()
        log_event(
            logger,
            logging.INFO,
            "stage_extracting_timeline_completed",
            run_id=run.id,
            artifact_count=len(artifacts),
            timeline_event_count=len(ordered),
            uncertain_count=sum(1 for candidate in ordered if candidate.uncertain),
        )

        warning_codes = self._extract_impact_claims(run, artifacts)
        return {"warning_codes": warning_codes} if warning_codes else None

    def _extract_impact_claims(self, run: AnalysisRun, artifacts: list[Artifact]) -> list[str]:
        """Generate run-level Impact Claims via the IncidentFactExtractor (ADR 0033).

        Impact is a Major Claim, so each claim's citations are resolved from the
        stored Artifact lines (the citation source of truth, ADR 0024); an
        impact claim left without supporting evidence is normalized to an
        assumption and flagged ``uncited_claim`` (ADR 0013). A model citation to
        an artifact outside the run or to out-of-range lines is dropped and
        flagged ``invalid_citation`` so one bad citation cannot block the rest.

        Idempotent across the single stage retry: prior run-level impact claims
        are cleared first.
        """
        self._clear_impact_claims(run)
        if not artifacts:
            return []
        timeline = list(
            self._session.scalars(
                select(TimelineEvent)
                .where(TimelineEvent.run_id == run.id)
                .order_by(TimelineEvent.sequence.asc())
            )
        )
        output = self._fact_extractor.extract(artifacts=artifacts, timeline_events=timeline)
        # Record the extractor's Model Call Record (ADR 0038). This also drains the
        # recording buffer at the stage-2 boundary so a stage-3 builder call is
        # never mis-attributed the extractor's capture.
        self._record_model_call(
            run,
            role=ROLE_INCIDENT_FACTS,
            substep="extract",
            prompt_version=INCIDENT_FACTS_PROMPT_VERSION,
            schema_version=INCIDENT_FACTS_SCHEMA_VERSION,
            fallback_identity=self._fact_extractor.version,
            structured_output=_sanitized_facts_output(output),
        )
        by_id = {artifact.id: artifact for artifact in artifacts}
        warning_codes: list[str] = []
        for sequence, impact in enumerate(output.impact_claims, start=1):
            evidence = self._resolve_refs(by_id, impact.evidence, "supporting", warning_codes)
            assumption = not evidence
            if assumption:
                warning_codes.append("uncited_claim")
            claim = ImpactClaim(
                run_id=run.id,
                sequence=sequence,
                description=impact.description,
                assumption=assumption,
            )
            claim.evidence_refs.extend(evidence)
            self._session.add(claim)
        self._session.flush()
        warning_codes = _dedupe(warning_codes)
        log_event(
            logger,
            logging.INFO,
            "stage_extracting_impact_completed",
            run_id=run.id,
            impact_claim_count=len(output.impact_claims),
            warning_codes=",".join(warning_codes) if warning_codes else None,
        )
        return warning_codes

    def _generate_rca(self, run: AnalysisRun) -> dict | None:
        """Generate ranked RCA Hypotheses from the run's cited evidence.

        Calls the configured LLMClient (ADR 0011), validates its output against a
        strict JSON schema (ADR 0028) — invalid JSON or a schema violation raises,
        which the executor turns into a stage failure with one retry (ADR 0029) —
        then persists hypotheses and their remediation items with EvidenceRefs
        resolved from the actual Artifact lines (ADR 0024). Impact Claims are not
        produced here; they are run-level incident facts from the earlier stage
        (ADR 0033). Any Major
        Claim left without supporting evidence is normalized to an assumption and
        counted as an `uncited_claim` warning (ADR 0013); that does not fail the
        run.

        Idempotent across the single retry: prior hypotheses for the run are
        cleared first, and the chunk/timeline outputs from earlier stages are
        untouched, so a failed-then-retried RCA never duplicates or corrupts state.
        """
        self._clear_hypotheses(run)
        # Idempotent across the single stage retry (ADR 0029): clear stage-3
        # provenance (builder, falsifier, support verifier, ranker) before the
        # substeps regenerate it. Also drop any undrained capture so a builder
        # Model Call Record is never attributed a stale completion.
        self._clear_provenance(run, STAGE3_ROLES)
        self._llm_recorder.drain()
        artifacts = self._run_artifacts(run)
        if not artifacts:
            return None

        timeline = list(
            self._session.scalars(
                select(TimelineEvent)
                .where(TimelineEvent.run_id == run.id)
                .order_by(TimelineEvent.sequence.asc())
            )
        )
        retrieval = self._retrieval.select_for_rca(
            session=self._session,
            run=run,
            artifacts=artifacts,
            timeline_events=timeline,
        )
        log_event(
            logger,
            logging.INFO,
            "stage_generating_rca_prompt_ready",
            run_id=run.id,
            artifact_count=len(retrieval.artifacts),
            timeline_event_count=len(timeline),
            retrieval_strategy=self._retrieval.version,
        )
        system, user = build_rca_prompt(retrieval.artifacts, timeline)
        response = self._llm.complete(system=system, user=user)
        try:
            output = RcaGenerationOutput.model_validate_json(response.text)
        except ValidationError as exc:
            # Schema-invalid (or non-JSON) model output fails the stage rather
            # than becoming pipeline state (ADR 0028).
            raise ValueError(f"RCA output failed schema validation: {exc}") from exc

        # Runtime Reasoning Gate: the builder is bounded to MAX_INITIAL_HYPOTHESES
        # (ADR 0036, PRD #26 / #30 user story 65). An over-budget candidate set fails
        # the stage rather than persisting and challenging an unbounded number of
        # hypotheses, which would blow the bounded review/token surface. Failing
        # before persistence keeps the gate deterministic and uses the same bounded
        # repair/failure contract as the proposed-alternative cap (one retry, ADR 0029).
        if len(output.hypotheses) > MAX_INITIAL_HYPOTHESES:
            raise ValueError(
                f"builder generated {len(output.hypotheses)} initial hypotheses, exceeding the "
                f"bounded maximum of {MAX_INITIAL_HYPOTHESES}"
            )

        # Provenance for the builder substep (ADR 0038): a Retrieval Trace over the
        # chunks the strategy selected — flagging which the model actually cited so
        # retrieved-but-ignored evidence is visible (PRD user story 70) — and a
        # Model Call Record linking the builder call to that trace.
        builder_trace = self._record_retrieval(
            run,
            role=ROLE_BUILDER,
            substep="generate",
            chunks=retrieval.chunks,
            query=retrieval.query or "RCA candidate retrieval",
            strategy_version=self._retrieval.version,
            cited_ranges=self._builder_cited_ranges(output),
        )
        self._record_model_call(
            run,
            role=ROLE_BUILDER,
            substep="generate",
            prompt_version=PROMPT_VERSION,
            schema_version=RCA_SCHEMA_VERSION,
            fallback_identity=self._llm.label,
            structured_output=_sanitized_builder_output(output),
            retrieval_trace=builder_trace,
        )

        by_id = {artifact.id: artifact for artifact in retrieval.artifacts}
        warning_codes: list[str] = []
        hypotheses: list[Hypothesis] = []
        for rank, hyp in enumerate(output.hypotheses, start=1):
            supporting = self._resolve_refs(
                by_id, hyp.supporting_evidence, "supporting", warning_codes
            )
            contradicting = self._resolve_refs(
                by_id, hyp.contradicting_evidence, "contradicting", warning_codes
            )
            assumption = not supporting
            if assumption:
                warning_codes.append("uncited_claim")
            hypothesis = Hypothesis(
                run_id=run.id,
                rank=rank,
                origin="initial",
                title=hyp.title,
                summary=hyp.summary,
                assumption=assumption,
                review_status="proposed",
                unknowns=list(hyp.unknowns),
                validation_steps=list(hyp.validation_steps),
            )
            hypothesis.evidence_refs.extend(supporting)
            hypothesis.evidence_refs.extend(contradicting)
            for sequence, remediation in enumerate(hyp.remediation_items, start=1):
                item = ActionItem(sequence=sequence, description=remediation.description)
                item.evidence_refs.extend(
                    self._resolve_refs(
                        by_id, remediation.evidence, "supporting", warning_codes
                    )
                )
                hypothesis.action_items.append(item)
            self._session.add(hypothesis)
            hypotheses.append(hypothesis)

        self._session.flush()

        # Bounded Falsification Round (ADR 0034 / 0036): challenge every initial
        # hypothesis, then run one bounded alternative-expansion pass that may add
        # up to two Proposed RCA Hypotheses and challenges those once. The falsifier
        # searches all run artifacts, so counterclaims and proposed-alternative
        # citations resolve against the full immutable evidence set, not just the
        # builder's retrieval subset.
        self._run_falsification_round(run, hypotheses, timeline, warning_codes)

        # Final substep of stage 3 (ADR 0037): incrementally verify the candidates'
        # citations, judge provisional semantic support, then produce one ordinal
        # Advisory Hypothesis Ranking across all initial and proposed hypotheses.
        self._rank_hypotheses(run, warning_codes)

        outcome: dict = {}
        if warning_codes:
            outcome["warning_codes"] = _dedupe(warning_codes)
        if response.usage:
            outcome["usage"] = response.usage
        log_event(
            logger,
            logging.INFO,
            "stage_generating_rca_completed",
            run_id=run.id,
            hypothesis_count=len(output.hypotheses),
            warning_codes=",".join(_dedupe(warning_codes)) if warning_codes else None,
            usage_keys=",".join(sorted(response.usage.keys())) if response.usage else None,
        )
        return outcome or None

    def _run_falsification_round(
        self,
        run: AnalysisRun,
        initial_hypotheses: list[Hypothesis],
        timeline: list[TimelineEvent],
        warning_codes: list[str],
    ) -> None:
        """Run the single bounded Falsification Round (ADR 0034 / 0036).

        The round has two passes and never recurses (PRD user story 16):

        1. Challenge every initial RCA Hypothesis. Each receives exactly one
           persisted Hypothesis Challenge — severity, cited Counterclaims (or an
           explicit assumption marker, ADR 0013), Evidence Gaps, and Falsification
           Tests. While challenging an initial hypothesis the falsifier may surface
           missed alternatives; they are collected in order.

        2. Persist at most ``MAX_PROPOSED_HYPOTHESES`` Proposed RCA Hypotheses
           (``origin='proposed'``) from those collected, then challenge each once
           with proposals disabled. A proposed alternative thus travels the exact
           same citation/challenge/review path as an initial hypothesis and is
           challenged exactly once (PRD user story 15).

        Runtime Reasoning Gate (ADR 0036, PRD user story 65 / AC #4): more than two
        proposed alternatives, or a second-round challenge that tries to propose
        again, raises — which fails the stage after its single retry (ADR 0029),
        the bounded repair/failure contract available at this point. Complete
        challenge coverage stays mandatory (ADR 0034). Idempotent across the retry:
        ``_clear_hypotheses`` cascades both initial and proposed hypotheses, their
        challenges, and counterclaims away before regeneration.
        """
        if not initial_hypotheses:
            return
        all_artifacts = self._run_artifacts(run)
        by_id = {artifact.id: artifact for artifact in all_artifacts}

        # Pass 1: challenge initial hypotheses, collecting proposed alternatives.
        proposed: list = []
        for hypothesis in initial_hypotheses:
            result = self._challenge_hypothesis(
                run, hypothesis, all_artifacts, timeline, by_id, warning_codes, allow_proposals=True
            )
            proposed.extend(result.proposed_hypotheses)

        # Runtime Reasoning Gate: the expansion round is bounded. Exceeding the cap
        # fails the stage rather than silently truncating, so the bound is auditable.
        if len(proposed) > MAX_PROPOSED_HYPOTHESES:
            raise ValueError(
                f"falsification proposed {len(proposed)} alternatives, exceeding the "
                f"bounded maximum of {MAX_PROPOSED_HYPOTHESES}"
            )

        # Pass 2: persist each proposed alternative as an origin='proposed'
        # hypothesis and challenge it once with proposals disabled (no recursion).
        proposed_hypotheses: list[Hypothesis] = []
        next_rank = len(initial_hypotheses)
        for offset, candidate in enumerate(proposed, start=1):
            next_rank += 1
            hypothesis = self._persist_proposed_hypothesis(
                run, candidate, next_rank, by_id, warning_codes
            )
            proposed_hypotheses.append(hypothesis)
        self._session.flush()
        for hypothesis in proposed_hypotheses:
            result = self._challenge_hypothesis(
                run, hypothesis, all_artifacts, timeline, by_id, warning_codes, allow_proposals=False
            )
            if result.proposed_hypotheses:
                # No recursive expansion: a proposed hypothesis may not itself
                # spawn further alternatives (ADR 0036, PRD user story 16 / AC #1).
                raise ValueError(
                    "falsification attempted a second expansion round while challenging a "
                    "proposed alternative"
                )

        self._session.flush()
        total = len(initial_hypotheses) + len(proposed_hypotheses)
        log_event(
            logger,
            logging.INFO,
            "stage_challenging_hypotheses_completed",
            run_id=run.id,
            hypothesis_count=total,
            initial_count=len(initial_hypotheses),
            proposed_count=len(proposed_hypotheses),
            falsifier_version=self._falsifier.version,
        )

    def _challenge_hypothesis(
        self,
        run: AnalysisRun,
        hypothesis: Hypothesis,
        all_artifacts: list[Artifact],
        timeline: list[TimelineEvent],
        by_id: dict[str, Artifact],
        warning_codes: list[str],
        *,
        allow_proposals: bool,
    ) -> HypothesisChallengeOutput:
        """Challenge one hypothesis and persist its Hypothesis Challenge (ADR 0034).

        The falsifier is handed the persisted hypothesis and ALL run artifacts so
        it can find counterevidence the builder's retrieval subset omitted (PRD
        user story 13); a Counterclaim's citations resolve from the stored artifact
        lines, never model text (ADR 0024). A schema-invalid or missing challenge
        raises, failing the stage after its single retry rather than shipping
        partial coverage (PRD user stories 61-62). Returns the falsifier output so
        the caller can read any proposed alternatives.
        """
        target = HypothesisToChallenge(
            title=hypothesis.title,
            summary=hypothesis.summary,
            supporting_snippets=tuple(
                ref.snippet for ref in hypothesis.evidence_refs if ref.role != "contradicting"
            ),
            contradicting_snippets=tuple(
                ref.snippet for ref in hypothesis.evidence_refs if ref.role == "contradicting"
            ),
        )
        result = self._falsifier.challenge(
            hypothesis=target,
            artifacts=all_artifacts,
            timeline_events=timeline,
            allow_proposals=allow_proposals,
        )
        # Provenance for this falsifier substep (ADR 0038). Falsification Retrieval
        # spans ALL run artifacts (PRD user story 13), so the Retrieval Trace
        # records the whole ordered chunk set and flags which the counterclaims
        # cited — retrieved-but-uncited chunks stay visible (PRD user story 70). The
        # Model Call Record links the challenge call to that trace.
        substep = f"challenge:{hypothesis.origin or 'initial'}:{hypothesis.id}"
        falsifier_trace = self._record_retrieval(
            run,
            role=ROLE_FALSIFIER,
            substep=substep,
            chunks=self._run_chunk_refs(run),
            query=f"Falsification retrieval across all run artifacts for: {hypothesis.title}",
            strategy_version=FALSIFICATION_RETRIEVAL_STRATEGY,
            cited_ranges=[
                (ref.artifact_id, ref.line_start, ref.line_end)
                for counter in result.counterclaims
                for ref in counter.evidence
            ],
        )
        self._record_model_call(
            run,
            role=ROLE_FALSIFIER,
            substep=substep,
            prompt_version=FALSIFICATION_PROMPT_VERSION,
            schema_version=FALSIFICATION_SCHEMA_VERSION,
            fallback_identity=self._falsifier.version,
            structured_output=_sanitized_falsifier_output(result),
            retrieval_trace=falsifier_trace,
        )
        challenge = HypothesisChallenge(
            run_id=run.id,
            hypothesis_id=hypothesis.id,
            challenged_claim=result.challenged_claim,
            severity=result.severity,
            evidence_gaps=list(result.evidence_gaps),
            falsification_tests=list(result.falsification_tests),
            falsifier_version=self._falsifier.version,
        )
        for sequence, counter in enumerate(result.counterclaims, start=1):
            # A Counterclaim is a Major Claim: resolve its citations from the
            # stored artifact lines, or normalize it to an assumption when it cites
            # nothing resolvable (ADR 0013), so the falsifier cannot introduce
            # unchecked incident facts.
            evidence = self._resolve_refs(by_id, counter.evidence, "supporting", warning_codes)
            assumption = not evidence
            if assumption:
                warning_codes.append("uncited_claim")
            counterclaim = Counterclaim(
                sequence=sequence,
                statement=counter.statement,
                assumption=assumption,
            )
            counterclaim.evidence_refs.extend(evidence)
            challenge.counterclaims.append(counterclaim)
        self._session.add(challenge)
        return result

    def _persist_proposed_hypothesis(
        self,
        run: AnalysisRun,
        candidate,
        rank: int,
        by_id: dict[str, Artifact],
        warning_codes: list[str],
    ) -> Hypothesis:
        """Persist a falsifier-proposed alternative as an origin='proposed' row.

        Mirrors the builder's hypothesis persistence (ADR 0036): citations resolve
        from the stored artifact lines over the full immutable run-artifact set,
        an uncited statement is normalized to an assumption (ADR 0013), and
        remediation items hang off the hypothesis. The hypothesis then receives the
        same challenge, citation-audit, and support treatment as an initial one;
        ``origin`` only records how it entered, never a different trust level.
        """
        supporting = self._resolve_refs(
            by_id, candidate.supporting_evidence, "supporting", warning_codes
        )
        contradicting = self._resolve_refs(
            by_id, candidate.contradicting_evidence, "contradicting", warning_codes
        )
        assumption = not supporting
        if assumption:
            warning_codes.append("uncited_claim")
        hypothesis = Hypothesis(
            run_id=run.id,
            rank=rank,
            origin="proposed",
            title=candidate.title,
            summary=candidate.summary,
            assumption=assumption,
            review_status="proposed",
            unknowns=list(candidate.unknowns),
            validation_steps=list(candidate.validation_steps),
        )
        hypothesis.evidence_refs.extend(supporting)
        hypothesis.evidence_refs.extend(contradicting)
        for sequence, remediation in enumerate(candidate.remediation_items, start=1):
            item = ActionItem(sequence=sequence, description=remediation.description)
            item.evidence_refs.extend(
                self._resolve_refs(by_id, remediation.evidence, "supporting", warning_codes)
            )
            hypothesis.action_items.append(item)
        self._session.add(hypothesis)
        return hypothesis

    def _rank_hypotheses(self, run: AnalysisRun, warning_codes: list[str]) -> None:
        """Produce one ordinal Advisory Hypothesis Ranking for the run (ADR 0037).

        The final substep of stage 3 (PRD #26 user stories 17-25). It runs after
        every initial and proposed hypothesis has been persisted and challenged,
        in three deterministic steps so ranking never rests on broken or
        unsupported evidence:

        1. Incremental Citation Check — verify the stage-3 citations (hypotheses,
           their remediation, and counterclaims) in place so a broken reference
           cannot be counted as positive support before the visible Final Citation
           Audit in stage 4 (CONTEXT "Incremental Citation Check vs Final Citation
           Audit").
        2. Support Judgment — judge each hypothesis's semantic support from its
           *verified* supporting citations only, so ranking accounts for whether a
           valid citation actually backs the claim (PRD user story 23). This single
           judgment is canonical for the hypothesis: stage 6's complete audit
           reuses it (surfacing the Warning Code) rather than re-invoking the
           verifier, so the final audit can never contradict the ranking it
           informed (CONTEXT "Provisional Support Judgment vs Final Unsupported-
           Claim Audit"). Warnings are emitted at that audit, not here.
        3. Advisory ranking — hand the ranker post-challenge facts (a Role Handoff,
           not hidden reasoning) and order every candidate exactly once. A Runtime
           Reasoning Gate fails the stage if the ranking does not cover every
           candidate, so an incomplete ranking can never be presented (PRD user
           story 60). The original builder order stays on ``rank`` for audit
           (PRD user story 20).

        Idempotent across the single stage retry (ADR 0029): a retry clears and
        regenerates the hypotheses, and this overwrites ``advisory_rank`` /
        ``ranking_rationale`` in place.
        """
        hypotheses = list(
            self._session.scalars(
                select(Hypothesis).where(Hypothesis.run_id == run.id).order_by(Hypothesis.rank.asc())
            )
        )
        if not hypotheses:
            return

        self._incremental_citation_check(run, hypotheses)

        # Provisional semantic support, judged off verified citations only. Warnings
        # belong to the stage-6 final audit, so discard them here. A Model Call
        # Record is persisted for each hypothesis whose support the verifier was
        # actually consulted on (ADR 0038); a deterministic short-circuit — no
        # verified citation to judge — makes no model call and records none, so the
        # provenance honestly reflects which judgments invoked a model.
        provisional_warnings: list[str] = []
        for hypothesis in hypotheses:
            consulted = self._classify_claim(
                hypothesis, f"{hypothesis.title}: {hypothesis.summary}", provisional_warnings
            )
            if consulted:
                # Trace the verified citations the support judgment actually saw
                # (its Role Handoff), so an input omission is distinguishable from a
                # reasoning outcome (PRD user story 69). The structured output keeps
                # only the support status — the rationale is model free text that
                # could quote Artifact text and already lives on the claim row.
                support_trace = self._record_support_trace(run, hypothesis)
                self._record_model_call(
                    run,
                    role=ROLE_SUPPORT_VERIFIER,
                    substep=f"support:{hypothesis.id}",
                    prompt_version=CLAIM_SUPPORT_PROMPT_VERSION,
                    schema_version=CLAIM_SUPPORT_SCHEMA_VERSION,
                    fallback_identity=self._claim_support.version,
                    structured_output={"status": hypothesis.support_status},
                    retrieval_trace=support_trace,
                )

        candidates = [self._ranking_candidate(hypothesis) for hypothesis in hypotheses]
        output = self._ranker.rank(candidates)

        # Runtime Reasoning Gate (PRD user story 60, issue #31 AC): the advisory
        # ranking must place every candidate exactly once. A missing, duplicated, or
        # unknown candidate fails the stage after its single retry rather than
        # shipping a partial ranking.
        expected = {hypothesis.id for hypothesis in hypotheses}
        ranked_ids = [entry.hypothesis_id for entry in output.rankings]
        seen = set(ranked_ids)
        if len(ranked_ids) != len(seen) or seen != expected:
            raise ValueError(
                "advisory ranking must cover every hypothesis exactly once: "
                f"missing {sorted(expected - seen)}, unexpected {sorted(seen - expected)}, "
                f"duplicates {sorted({i for i in ranked_ids if ranked_ids.count(i) > 1})}"
            )

        by_id = {hypothesis.id: hypothesis for hypothesis in hypotheses}
        for position, entry in enumerate(output.rankings, start=1):
            hypothesis = by_id[entry.hypothesis_id]
            hypothesis.advisory_rank = position
            hypothesis.ranking_rationale = entry.rationale.model_dump()
        self._session.flush()
        # The ranker's Model Call Record (ADR 0038). The MVP ranker is deterministic
        # and makes no model call, so this records the role's own version as model
        # identity with null usage/hashes — the record documents that the ranking
        # substep ran and with which contract, even without a model.
        self._record_model_call(
            run,
            role=ROLE_RANKER,
            substep="rank",
            prompt_version=self._ranker.version,
            schema_version=ADVISORY_RANKING_SCHEMA_VERSION,
            fallback_identity=self._ranker.version,
            structured_output=_sanitized_ranker_output(output),
        )
        log_event(
            logger,
            logging.INFO,
            "stage_advisory_ranking_completed",
            run_id=run.id,
            hypothesis_count=len(hypotheses),
            ranker_version=self._ranker.version,
        )

    def _incremental_citation_check(
        self, run: AnalysisRun, hypotheses: list[Hypothesis]
    ) -> None:
        """Verify the stage-3 citations in place before ranking (ADR 0037).

        Stamps ``verifier_status`` on each hypothesis's supporting/contradicting
        EvidenceRefs, its remediation citations, and its challenge's Counterclaim
        citations, using the same deterministic integrity verifier the Final
        Citation Audit uses (ADR 0014). Idempotent and additive: stage 4 rechecks
        the full run, so an incremental status here is never the last word.
        """
        bodies = {artifact.id: artifact.body for artifact in self._run_artifacts(run)}
        for hypothesis in hypotheses:
            refs = list(hypothesis.evidence_refs)
            for item in hypothesis.action_items:
                refs.extend(item.evidence_refs)
            if hypothesis.challenge is not None:
                for counterclaim in hypothesis.challenge.counterclaims:
                    refs.extend(counterclaim.evidence_refs)
            for ref in refs:
                ref.verifier_status = self._verifier.verify(
                    CitationTarget(
                        artifact_id=ref.artifact_id,
                        line_start=ref.line_start,
                        line_end=ref.line_end,
                        snippet=ref.snippet,
                    ),
                    bodies,
                ).value
        self._session.flush()

    def _ranking_candidate(self, hypothesis: Hypothesis) -> RankingCandidate:
        """Distill a persisted Hypothesis into the ranker's Role Handoff (ADR 0037).

        Only *verified* supporting citations count toward ``supported_citation_count``,
        and an UNSUPPORTED hypothesis contributes zero, so broken or semantically
        unsupported evidence can never be counted as positive ranking support
        (PRD user story 23, issue #31 AC).
        """
        verified_supporting = sum(
            1
            for ref in hypothesis.evidence_refs
            if ref.role != "contradicting"
            and ref.verifier_status == CitationIntegrityStatus.VERIFIED.value
        )
        if hypothesis.support_status == ClaimSupportStatus.UNSUPPORTED.value:
            verified_supporting = 0
        challenge = hypothesis.challenge
        return RankingCandidate(
            hypothesis_id=hypothesis.id,
            title=hypothesis.title,
            origin=hypothesis.origin or "initial",
            builder_rank=hypothesis.rank,
            support_status=hypothesis.support_status,
            supported_citation_count=verified_supporting,
            challenge_severity=challenge.severity if challenge is not None else None,
            counterclaim_count=len(challenge.counterclaims) if challenge is not None else 0,
            evidence_gap_count=len(challenge.evidence_gaps) if challenge is not None else 0,
            assumption=hypothesis.assumption,
        )

    def _resolve_refs(
        self,
        by_id: dict[str, Artifact],
        refs: list[RcaEvidenceRef],
        role: str,
        warning_codes: list[str],
    ) -> list[EvidenceRef]:
        resolved: list[EvidenceRef] = []
        for ref in refs:
            evidence_ref = self._resolve_ref(by_id, ref, role)
            if evidence_ref is None:
                warning_codes.append("invalid_citation")
                continue
            resolved.append(evidence_ref)
        return resolved

    def _resolve_ref(
        self, by_id: dict[str, Artifact], ref: RcaEvidenceRef, role: str
    ) -> EvidenceRef | None:
        """Turn a model-cited line range into a citation with an exact snippet.

        The snippet is read from the stored Artifact lines, never from the model,
        so the citation remains the source of truth (ADR 0024). A ref to an
        artifact outside the run or to out-of-range lines is dropped and flagged
        by the caller so one bad model citation does not prevent human review of
        the rest of the run.
        """
        artifact = by_id.get(ref.artifact_id)
        if artifact is None:
            return None
        lines = artifact.body.split("\n")
        if ref.line_start < 1 or ref.line_end < ref.line_start or ref.line_end > len(lines):
            return None
        snippet = "\n".join(lines[ref.line_start - 1 : ref.line_end])
        return EvidenceRef(
            artifact_id=artifact.id,
            source_name=artifact.source_name,
            line_start=ref.line_start,
            line_end=ref.line_end,
            snippet=snippet,
            confidence_score=ref.confidence_score,
            role=role,
        )

    def _verify_citations(self, run: AnalysisRun) -> dict | None:
        """Deterministically verify every EvidenceRef the run produced (ADR 0014).

        For each citation owned by the run (timeline, hypothesis, impact claim, or
        action item) the CitationIntegrityVerifier confirms the cited Artifact is
        in the run, the line range exists, and the stored snippet matches those
        exact lines. The outcome is stamped on ``EvidenceRef.verifier_status`` so
        citation trust is visible end to end. This stage only annotates existing
        claims — it never introduces new ones (ADR 0026).

        A broken citation is flagged with a `citation_integrity_failure` warning,
        not deleted and not a run failure (ADR 0015 / CONTEXT "flagged, not
        deleted"). Idempotent across the single stage retry (ADR 0029): it
        recomputes the same statuses in place and adds no rows.
        """
        bodies = {artifact.id: artifact.body for artifact in self._run_artifacts(run)}
        warning_codes: list[str] = []
        refs = self._run_evidence_refs(run)
        verified = 0
        for ref in refs:
            status = self._verifier.verify(
                CitationTarget(
                    artifact_id=ref.artifact_id,
                    line_start=ref.line_start,
                    line_end=ref.line_end,
                    snippet=ref.snippet,
                ),
                bodies,
            )
            ref.verifier_status = status.value
            if not status.ok:
                warning_codes.append("citation_integrity_failure")
            else:
                verified += 1
        self._session.flush()
        warning_codes = _dedupe(warning_codes)
        log_event(
            logger,
            logging.INFO,
            "stage_verifying_citations_completed",
            run_id=run.id,
            citation_total=len(refs),
            citation_verified=verified,
            warning_codes=",".join(warning_codes) if warning_codes else None,
        )
        return {"warning_codes": warning_codes} if warning_codes else None

    def _run_evidence_refs(self, run: AnalysisRun) -> list[EvidenceRef]:
        """Every EvidenceRef owned by the run, across all four owner types.

        EvidenceRefs hang off timeline events, hypotheses, and run-level impact
        claims directly, and off action items through their parent hypothesis, so
        this walks each owner's relationship to the run rather than assuming a
        single join path.
        """
        refs: list[EvidenceRef] = list(
            self._session.scalars(
                select(EvidenceRef)
                .join(TimelineEvent, EvidenceRef.timeline_event_id == TimelineEvent.id)
                .where(TimelineEvent.run_id == run.id)
            )
        )
        refs += self._session.scalars(
            select(EvidenceRef)
            .join(Hypothesis, EvidenceRef.hypothesis_id == Hypothesis.id)
            .where(Hypothesis.run_id == run.id)
        )
        refs += self._session.scalars(
            select(EvidenceRef)
            .join(ImpactClaim, EvidenceRef.impact_claim_id == ImpactClaim.id)
            .where(ImpactClaim.run_id == run.id)
        )
        refs += self._session.scalars(
            select(EvidenceRef)
            .join(ActionItem, EvidenceRef.action_item_id == ActionItem.id)
            .join(Hypothesis, ActionItem.hypothesis_id == Hypothesis.id)
            .where(Hypothesis.run_id == run.id)
        )
        # Counterclaims are Major Claims (ADR 0034); their citations are audited at
        # the same trust checkpoint as every other EvidenceRef.
        refs += self._session.scalars(
            select(EvidenceRef)
            .join(Counterclaim, EvidenceRef.counterclaim_id == Counterclaim.id)
            .join(HypothesisChallenge, Counterclaim.challenge_id == HypothesisChallenge.id)
            .where(HypothesisChallenge.run_id == run.id)
        )
        return refs

    def _draft_postmortem(self, run: AnalysisRun) -> dict | None:
        """Compose the structured Postmortem from the verified outputs (ADR 0012).

        Drafting runs after citation verification, so it may only compose existing
        claims, never introduce new factual ones (ADR 0026). The composer is fed an
        ORM-free digest of the run's timeline and hypotheses and returns connective
        narrative (summary + lessons) only; the factual sections stay their own
        rows and are assembled at read/export time. This stage adds no EvidenceRefs
        and mutates no claim.

        Idempotent across the single stage retry (ADR 0029): the run's prior
        Postmortem (if any) is replaced in place, so a failed-then-retried draft
        never leaves two postmortems for one run.
        """
        self._clear_postmortem(run)
        incident = self._session.get(Incident, run.incident_id)
        timeline = list(
            self._session.scalars(
                select(TimelineEvent)
                .where(TimelineEvent.run_id == run.id)
                .order_by(TimelineEvent.sequence.asc())
            )
        )
        hypotheses = list(
            self._session.scalars(
                select(Hypothesis).where(Hypothesis.run_id == run.id).order_by(Hypothesis.rank.asc())
            )
        )
        draft = self._composer.compose(
            self._build_compose_context(run, incident, timeline, hypotheses)
        )
        self._session.add(
            Postmortem(
                run_id=run.id,
                summary=draft.summary,
                lessons_learned=list(draft.lessons_learned),
                evidence_sufficiency=draft.evidence_sufficiency,
                evidence_gaps=list(draft.evidence_gaps),
                next_validation_steps=list(draft.next_validation_steps),
                # An automated run only produces a provisional draft; finalization
                # is a separate human action (ADR 0035, PRD #26 stories 26-30).
                conclusion_status="provisional",
                composer_version=self._composer.version,
            )
        )
        self._session.flush()
        log_event(
            logger,
            logging.INFO,
            "stage_drafting_postmortem_completed",
            run_id=run.id,
            timeline_event_count=len(timeline),
            hypothesis_count=len(hypotheses),
            evidence_sufficiency=draft.evidence_sufficiency,
            evidence_gap_count=len(draft.evidence_gaps),
            validation_step_count=len(draft.next_validation_steps),
        )
        # Refusal is a non-fatal Warning Code (ADR 0015 / 0029) so it is visible
        # in the run's stage events and aggregated by evaluation (ADR 0021 / 0025).
        if draft.evidence_sufficiency == "insufficient":
            return {"warning_codes": ["insufficient_evidence"]}
        return None

    def _build_compose_context(
        self,
        run: AnalysisRun,
        incident: Incident | None,
        timeline: list[TimelineEvent],
        hypotheses: list[Hypothesis],
    ) -> PostmortemComposerContext:
        # Anchor the timeline span on the normalized-timestamp events only, in
        # chronological order, so the summary never claims a span from an inferred
        # or unparseable timestamp.
        dated = [event for event in timeline if event.normalized_ts is not None]
        earliest = dated[0].original_ts_text if dated else None
        latest = dated[-1].original_ts_text if dated else None
        artifacts = self._run_artifacts(run)
        return PostmortemComposerContext(
            incident_title=incident.title if incident is not None else "Incident",
            incident_severity=incident.severity if incident is not None else None,
            artifact_count=len(artifacts),
            timeline_event_count=len(timeline),
            earliest_ts_text=earliest,
            latest_ts_text=latest,
            present_source_types=tuple(sorted({a.source_type for a in artifacts})),
            hypotheses=tuple(
                HypothesisDigest(
                    rank=hypothesis.rank,
                    title=hypothesis.title,
                    assumption=hypothesis.assumption,
                    unknowns=tuple(hypothesis.unknowns),
                )
                for hypothesis in hypotheses
            ),
        )

    def _clear_postmortem(self, run: AnalysisRun) -> None:
        existing = self._session.scalars(
            select(Postmortem).where(Postmortem.run_id == run.id)
        )
        for postmortem in existing:
            self._session.delete(postmortem)
        self._session.flush()

    def _flag_unsupported_claims(self, run: AnalysisRun) -> dict | None:
        """Surface every Major Claim's support status and flag the weak ones.

        The complete unsupported-claim audit at the visible trust checkpoint
        (ADR 0014 / 0037). For Hypotheses it reuses the single semantic support
        judgment already made during the stage-3 ranking substep rather than
        re-invoking the verifier: that judgment is canonical, so the final audit
        can never contradict the Advisory Hypothesis Ranking it informed (issue
        #31 — semantically unsupported evidence must not be counted as positive
        ranking support, and a hypothesis must never read ``unsupported`` while
        carrying a rank computed as ``supported``). Re-judging with the LLM-backed
        verifier could diverge run-to-run and reintroduce exactly that
        inconsistency. Run-level Impact Claims are not ranked and are judged here
        for the first time, so they are classified now. This stage only annotates
        existing claims (ADR 0026) and is idempotent across the single retry: it
        re-reads the persisted statuses and adds no rows.

        Unsupported and partially-supported claims are flagged with Warning Codes
        so they surface as Review Findings, but they never fail the run or trigger
        a retry (ADR 0015 / 0029).
        """
        hypotheses = list(
            self._session.scalars(
                select(Hypothesis).where(Hypothesis.run_id == run.id).order_by(Hypothesis.rank.asc())
            )
        )
        impact_claims = list(
            self._session.scalars(
                select(ImpactClaim)
                .where(ImpactClaim.run_id == run.id)
                .order_by(ImpactClaim.sequence.asc())
            )
        )
        warning_codes: list[str] = []
        classified = 0
        for hypothesis in hypotheses:
            if hypothesis.support_status == "unevaluated":
                # Defensive: ranking always judges support, so a hypothesis should
                # already carry a status here. Classify only if one slipped through
                # unjudged so the audit is still complete.
                self._classify_claim(
                    hypothesis, f"{hypothesis.title}: {hypothesis.summary}", warning_codes
                )
            else:
                self._warn_for_support(hypothesis.support_status, warning_codes)
            classified += 1
        # Run-level Impact Claims are Major Claims too, classified once per run
        # rather than per hypothesis (ADR 0033). They are not ranked, so the audit
        # is where they are judged.
        for claim in impact_claims:
            self._classify_claim(claim, claim.description, warning_codes)
            classified += 1
        self._session.flush()
        warning_codes = _dedupe(warning_codes)
        log_event(
            logger,
            logging.INFO,
            "stage_flagging_unsupported_claims_completed",
            run_id=run.id,
            hypothesis_count=len(hypotheses),
            major_claim_count=classified,
            warning_codes=",".join(warning_codes) if warning_codes else None,
        )
        return {"warning_codes": warning_codes} if warning_codes else None

    def _warn_for_support(self, support_status: str, warning_codes: list[str]) -> None:
        """Emit the Warning Code for an already-judged support status (ADR 0037).

        The final audit surfaces a claim's weakness from its persisted, canonical
        support judgment without re-running the verifier, so the warning the audit
        reports always matches the status the ranking used.
        """
        if support_status == ClaimSupportStatus.UNSUPPORTED.value:
            warning_codes.append("unsupported_claim")
        elif support_status == ClaimSupportStatus.PARTIAL.value:
            warning_codes.append("partial_claim_support")

    def _classify_claim(self, claim, claim_text: str, warning_codes: list[str]) -> bool:
        """Stamp one Major Claim's support status + rationale (ADR 0014).

        Contradicting evidence is excluded — support is judged on the supporting
        citations only. Snippets come from the stored EvidenceRefs, which are the
        citation source of truth (ADR 0024), so the verifier never sees
        model-invented text.

        Returns whether the semantic support verifier was actually consulted: an
        uncited or broken-citation claim is judged UNSUPPORTED deterministically
        with no model call, so the caller records no support Model Call Record for
        it (ADR 0038). It returns True only when a model judgment was made.
        """
        supporting = [ref for ref in claim.evidence_refs if ref.role != "contradicting"]
        verified_supporting = [
            ref for ref in supporting if ref.verifier_status == CitationIntegrityStatus.VERIFIED.value
        ]
        if not supporting:
            # An uncited Major Claim is an assumption (already flagged in the RCA
            # stage); there is no evidence to support, so it is UNSUPPORTED.
            claim.support_status = ClaimSupportStatus.UNSUPPORTED.value
            claim.support_rationale = (
                "No supporting evidence was cited, so this is recorded as an assumption "
                "rather than an evidence-backed claim."
            )
            warning_codes.append("unsupported_claim")
            return False
        if not verified_supporting:
            # Semantic support cannot rescue a broken citation. Citation integrity
            # is the deterministic trust floor (ADR 0014), so claims with only
            # unverified/broken support citations stay out of the authoritative narrative.
            claim.support_status = ClaimSupportStatus.UNSUPPORTED.value
            claim.support_rationale = (
                "No verified supporting citations were available, so this is recorded as "
                "unsupported until the cited evidence resolves to immutable artifact lines."
            )
            warning_codes.append("unsupported_claim")
            return False
        judgment = self._claim_support.verify(
            ClaimToVerify(
                claim_text=claim_text,
                evidence=tuple(ref.snippet for ref in verified_supporting),
            )
        )
        claim.support_status = judgment.status.value
        claim.support_rationale = judgment.rationale
        if judgment.status is ClaimSupportStatus.UNSUPPORTED:
            warning_codes.append("unsupported_claim")
        elif judgment.status is ClaimSupportStatus.PARTIAL:
            warning_codes.append("partial_claim_support")
        return True

    def _run_artifacts(self, run: AnalysisRun) -> list[Artifact]:
        # The included-artifact set is immutable once a run starts, so both
        # stages share one query. Tiebreak on Artifact.id: artifacts added in
        # one start_run share a created_at, so id keeps processing (and
        # inferred-event) order stable and deterministic across identical input.
        cached = self._artifacts_cache.get(run.id)
        if cached is not None:
            return cached
        stmt = (
            select(Artifact)
            .join(RunArtifact, RunArtifact.artifact_id == Artifact.id)
            .where(RunArtifact.run_id == run.id)
            .order_by(RunArtifact.created_at.asc(), Artifact.id.asc())
        )
        artifacts = list(self._session.scalars(stmt))
        self._artifacts_cache[run.id] = artifacts
        return artifacts

    # --- Reasoning/retrieval provenance (ADR 0038) --------------------------
    #
    # Persist a Model Call Record per Reasoning Role invocation and a Retrieval
    # Trace per role retrieval so the causal analysis is diagnosable without
    # duplicating Sensitive Evidence (PRD #26 user stories 57, 69-73). The
    # recording client buffers each completion's hashes + usage; these helpers
    # drain that buffer at the role boundary and attach the role/substep identity,
    # versions, and validated structured output — never prompt or response text.

    def _next_provenance_sequence(self, run: AnalysisRun) -> int:
        value = self._prov_seq.get(run.id, 0) + 1
        self._prov_seq[run.id] = value
        return value

    def _run_chunk_refs(self, run: AnalysisRun) -> list[RetrievedChunk]:
        """Ordered references to every persisted chunk in the run (ADR 0038).

        The falsifier's Falsification Retrieval spans all immutable run artifacts
        (PRD user story 13), so its Retrieval Trace records the whole ordered chunk
        set — references only, never chunk text.
        """
        cached = self._chunk_refs_cache.get(run.id)
        if cached is not None:
            return cached
        refs = [
            RetrievedChunk(
                chunk_id=chunk.id,
                artifact_id=chunk.artifact_id,
                sequence=chunk.sequence,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
            )
            for chunk in self._session.scalars(
                select(EvidenceChunk)
                .where(EvidenceChunk.run_id == run.id)
                .order_by(EvidenceChunk.sequence.asc())
            )
        ]
        self._chunk_refs_cache[run.id] = refs
        return refs

    def _builder_cited_ranges(
        self, output: RcaGenerationOutput
    ) -> list[tuple[str, int, int]]:
        """The (artifact, line_start, line_end) ranges the builder cited (ADR 0038).

        Drawn from the model's own structured output — supporting, contradicting,
        and remediation citations across every hypothesis — so the builder's
        Retrieval Trace can mark which retrieved chunks were actually cited.
        """
        ranges: list[tuple[str, int, int]] = []
        for hyp in output.hypotheses:
            refs = list(hyp.supporting_evidence) + list(hyp.contradicting_evidence)
            for remediation in hyp.remediation_items:
                refs.extend(remediation.evidence)
            for ref in refs:
                ranges.append((ref.artifact_id, ref.line_start, ref.line_end))
        return ranges

    def _record_retrieval(
        self,
        run: AnalysisRun,
        *,
        role: str,
        substep: str,
        chunks: list[RetrievedChunk] | tuple[RetrievedChunk, ...],
        query: str,
        strategy_version: str,
        cited_ranges: list[tuple[str, int, int]],
    ) -> RetrievalTrace:
        """Persist a Retrieval Trace, flagging retrieved-but-uncited chunks (ADR 0038).

        ``cited_ranges`` are the (artifact, line_start, line_end) ranges the role
        actually cited; a chunk is ``cited`` if any cited range overlaps it.
        Recording the uncited remainder is what lets a diagnostician separate a
        retrieval omission (a relevant chunk never retrieved) from a model omission
        (a chunk retrieved but ignored) — PRD user story 70.
        """
        cited_by_artifact: dict[str, list[tuple[int, int]]] = {}
        for artifact_id, line_start, line_end in cited_ranges:
            cited_by_artifact.setdefault(artifact_id, []).append((line_start, line_end))
        chunk_refs: list[dict] = []
        for chunk in chunks:
            ranges = cited_by_artifact.get(chunk.artifact_id, [])
            cited = any(
                not (end < chunk.line_start or start > chunk.line_end)
                for (start, end) in ranges
            )
            chunk_refs.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "artifact_id": chunk.artifact_id,
                    "sequence": chunk.sequence,
                    "line_start": chunk.line_start,
                    "line_end": chunk.line_end,
                    "cited": cited,
                }
            )
        trace = RetrievalTrace(
            run_id=run.id,
            sequence=self._next_provenance_sequence(run),
            role=role,
            substep=substep,
            query=query,
            strategy_version=strategy_version,
            chunk_refs=chunk_refs,
        )
        self._session.add(trace)
        self._session.flush()
        return trace

    def _record_support_trace(self, run: AnalysisRun, hypothesis: Hypothesis) -> RetrievalTrace:
        """Trace the verified citations a support judgment received (ADR 0038).

        The support verifier is a synthesis role, not a retrieval role: it judges
        the hypothesis's *verified supporting* citations handed to it. Recording the
        chunks those citations resolve to makes its input visible — a support
        record with an empty trace means no evidence reached it (input omission),
        distinct from one that saw evidence and judged it unsupported (PRD user
        story 69). The chunks are references only, never snippet text.
        """
        ranges = [
            (ref.artifact_id, ref.line_start, ref.line_end)
            for ref in hypothesis.evidence_refs
            if ref.role != "contradicting"
            and ref.verifier_status == CitationIntegrityStatus.VERIFIED.value
        ]
        overlapping = [
            chunk
            for chunk in self._run_chunk_refs(run)
            if any(
                artifact_id == chunk.artifact_id
                and not (end < chunk.line_start or start > chunk.line_end)
                for (artifact_id, start, end) in ranges
            )
        ]
        return self._record_retrieval(
            run,
            role=ROLE_SUPPORT_VERIFIER,
            substep=f"support:{hypothesis.id}",
            chunks=overlapping,
            query=f"Verified supporting citations judged for: {hypothesis.title}",
            strategy_version=SUPPORT_INPUT_STRATEGY,
            cited_ranges=ranges,
        )

    def _record_model_call(
        self,
        run: AnalysisRun,
        *,
        role: str,
        substep: str,
        prompt_version: str,
        schema_version: str,
        fallback_identity: str,
        structured_output: dict | None,
        retrieval_trace: RetrievalTrace | None = None,
    ) -> ModelCallRecord:
        """Persist one Reasoning Role invocation's reproducibility metadata (ADR 0038).

        Drains the recording client's buffer for the just-finished role call: a
        model-backed role contributes one capture (prompt/response hashes + token
        usage, never text), while a deterministic role (the default ranker) or an
        injected fake contributes none, so the record falls back to the role's own
        version as model identity with null usage/hashes. ``structured_output`` is
        the role's validated Role Handoff — its own assertions and line-range
        citations, never Artifact text — and ``retrieval_trace`` links the call to
        the evidence it received so a retrieval failure is distinguishable from a
        reasoning failure (PRD user story 69).
        """
        captures = self._llm_recorder.drain()
        capture = captures[-1] if captures else None
        record = ModelCallRecord(
            run_id=run.id,
            sequence=self._next_provenance_sequence(run),
            role=role,
            substep=substep,
            prompt_version=prompt_version,
            schema_version=schema_version,
            model_identity=capture.model_identity if capture else fallback_identity,
            input_hash=capture.input_hash if capture else None,
            output_hash=capture.output_hash if capture else None,
            usage=capture.usage if capture else None,
            structured_output=structured_output,
            retrieval_trace_id=retrieval_trace.id if retrieval_trace is not None else None,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def _clear_provenance(self, run: AnalysisRun, roles: frozenset[str]) -> None:
        """Remove a stage's prior provenance before it regenerates (ADR 0029).

        Idempotent across the single stage retry: a retried claim-generating stage
        clears only its own roles' Model Call Records and Retrieval Traces, so a
        failed-then-retried attempt never leaves duplicate provenance. Records are
        deleted before traces because a record references its trace.
        """
        for record in self._session.scalars(
            select(ModelCallRecord)
            .where(ModelCallRecord.run_id == run.id, ModelCallRecord.role.in_(roles))
        ):
            self._session.delete(record)
        for trace in self._session.scalars(
            select(RetrievalTrace)
            .where(RetrievalTrace.run_id == run.id, RetrievalTrace.role.in_(roles))
        ):
            self._session.delete(trace)
        self._session.flush()

    def _clear_timeline(self, run: AnalysisRun) -> None:
        existing = self._session.scalars(
            select(TimelineEvent).where(TimelineEvent.run_id == run.id)
        )
        for event in existing:
            self._session.delete(event)  # cascade removes its EvidenceRefs
        self._session.flush()

    def _clear_chunks(self, run: AnalysisRun) -> None:
        existing = self._session.scalars(
            select(EvidenceChunk).where(EvidenceChunk.run_id == run.id)
        )
        for chunk in existing:
            self._session.delete(chunk)
        self._session.flush()

    def _clear_hypotheses(self, run: AnalysisRun) -> None:
        existing = self._session.scalars(
            select(Hypothesis).where(Hypothesis.run_id == run.id)
        )
        for hypothesis in existing:
            # cascade removes action items and all hypothesis EvidenceRefs
            self._session.delete(hypothesis)
        self._session.flush()

    def _clear_impact_claims(self, run: AnalysisRun) -> None:
        existing = self._session.scalars(
            select(ImpactClaim).where(ImpactClaim.run_id == run.id)
        )
        for claim in existing:
            # cascade removes the impact claim's EvidenceRefs
            self._session.delete(claim)
        self._session.flush()


class _Candidate:
    __slots__ = (
        "artifact",
        "line_number",
        "line_text",
        "original_ts_text",
        "normalized_ts",
        "uncertain",
    )

    def __init__(
        self,
        artifact: Artifact,
        line_number: int,
        line_text: str,
        original_ts_text: str,
        normalized_ts,
        uncertain: bool,
    ) -> None:
        self.artifact = artifact
        self.line_number = line_number
        self.line_text = line_text
        self.original_ts_text = original_ts_text
        self.normalized_ts = normalized_ts
        self.uncertain = uncertain

    @property
    def description(self) -> str:
        # The event description is the cited line with its timestamp prefix
        # stripped, so the timeline reads as events rather than raw log lines.
        text = self.line_text.strip()
        if text.startswith(self.original_ts_text):
            text = text[len(self.original_ts_text):]
        return text.strip(" \t-:[]") or self.line_text.strip()


def _order_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    """Normalized timestamps first, in chronological order; inferred after.

    Inferred candidates keep their discovery order (a stable proxy for source
    order) because they have no comparable absolute time.
    """
    dated = [c for c in candidates if c.normalized_ts is not None]
    undated = [c for c in candidates if c.normalized_ts is None]
    dated.sort(key=lambda c: c.normalized_ts)
    return dated + undated


# --- Sanitized structured-output shaping for provenance (ADR 0038) ----------
#
# A Model Call Record persists the role's *validated structured output*, but it
# must not duplicate Artifact text (PRD #26 user stories 71, 73). A model can quote
# an artifact line verbatim into a free-text field (a hypothesis summary, a
# counterclaim statement, a support rationale), so the recorder never stores those
# free-text fields. Instead it stores the validated output's diagnostic skeleton:
# citations as *references* (artifact id + line range, never snippet text), plus
# counts, severities, statuses, and ranking order. The full free text already
# lives in the product tables (hypotheses, counterclaims, ranking rationale) that
# the normal Review Surface renders; provenance keeps only what reproducibility
# diagnosis needs.


def _citation_ref(ref) -> dict:
    """A citation as a reference only (artifact id + line range), never text."""
    return {
        "artifact_id": ref.artifact_id,
        "line_start": ref.line_start,
        "line_end": ref.line_end,
        "confidence_score": ref.confidence_score,
    }


def _sanitized_builder_output(output) -> dict:
    return {
        "hypothesis_count": len(output.hypotheses),
        "hypotheses": [
            {
                "supporting_citations": [_citation_ref(r) for r in hyp.supporting_evidence],
                "contradicting_citations": [_citation_ref(r) for r in hyp.contradicting_evidence],
                "unknown_count": len(hyp.unknowns),
                "validation_step_count": len(hyp.validation_steps),
                "remediation_count": len(hyp.remediation_items),
                "remediation_citations": [
                    _citation_ref(ref)
                    for remediation in hyp.remediation_items
                    for ref in remediation.evidence
                ],
            }
            for hyp in output.hypotheses
        ],
    }


def _sanitized_facts_output(output) -> dict:
    return {
        "impact_claim_count": len(output.impact_claims),
        "impact_citations": [
            _citation_ref(ref) for claim in output.impact_claims for ref in claim.evidence
        ],
    }


def _sanitized_falsifier_output(output) -> dict:
    return {
        "severity": output.severity,
        "counterclaim_count": len(output.counterclaims),
        "counterclaim_citations": [
            _citation_ref(ref) for counter in output.counterclaims for ref in counter.evidence
        ],
        "evidence_gap_count": len(output.evidence_gaps),
        "falsification_test_count": len(output.falsification_tests),
        "proposed_hypothesis_count": len(output.proposed_hypotheses),
    }


def _sanitized_ranker_output(output) -> dict:
    # Ordered candidate ids are the ranking outcome; the per-dimension rationale is
    # model free text already persisted on Hypothesis.ranking_rationale.
    return {"rankings": [{"hypothesis_id": entry.hypothesis_id} for entry in output.rankings]}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
