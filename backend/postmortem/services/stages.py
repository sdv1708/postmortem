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
from ..incident_facts import IncidentFactExtractor, LLMIncidentFactExtractor
from ..llm import LLMClient, OfflineLLMClient
from ..logging import log_event
from ..models import (
    ActionItem,
    AnalysisRun,
    Artifact,
    EvidenceChunk,
    EvidenceRef,
    Hypothesis,
    ImpactClaim,
    Incident,
    Postmortem,
    TimelineEvent,
    RunArtifact,
)
from ..rca import RcaEvidenceRef, RcaGenerationOutput, build_rca_prompt
from ..retrieval import DeterministicChunkArtifactRetrievalStrategy, RetrievalStrategy
from ..timestamps import parse_timestamp
from ..verification import (
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
    ) -> None:
        self._session = session
        self._chunker = chunker or SourceAwareLineWindowChunker()
        # Default to the offline client so deterministic stages still complete a
        # run when no provider is configured; real runs inject a configured
        # client (ADR 0011).
        self._llm = llm_client or OfflineLLMClient()
        # The incident-facts extractor is a swappable Reasoning-Role boundary
        # (ADR 0033): stage 2 produces run-level Impact Claims through it before
        # any causal interpretation. The default uses the configured LLM; the
        # offline client yields no impact so a run still completes.
        self._fact_extractor = incident_fact_extractor or LLMIncidentFactExtractor(self._llm)
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

        by_id = {artifact.id: artifact for artifact in retrieval.artifacts}
        warning_codes: list[str] = []
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

        self._session.flush()
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
        """Classify each Major Claim's evidence support and flag the weak ones.

        The semantic ClaimSupportVerifier (ADR 0014) judges whether the cited
        evidence supports each hypothesis statement and impact claim, recording
        SUPPORTED / PARTIAL / UNSUPPORTED plus a rationale. A claim with no
        supporting citation is an assumption and recorded UNSUPPORTED without
        calling the model. This stage only annotates existing claims (ADR 0026)
        and is idempotent across the single retry: it overwrites the support
        fields in place and adds no rows.

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
            self._classify_claim(
                hypothesis, f"{hypothesis.title}: {hypothesis.summary}", warning_codes
            )
            classified += 1
        # Run-level Impact Claims are Major Claims too, classified once per run
        # rather than per hypothesis (ADR 0033).
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

    def _classify_claim(self, claim, claim_text: str, warning_codes: list[str]) -> None:
        """Stamp one Major Claim's support status + rationale (ADR 0014).

        Contradicting evidence is excluded — support is judged on the supporting
        citations only. Snippets come from the stored EvidenceRefs, which are the
        citation source of truth (ADR 0024), so the verifier never sees
        model-invented text.
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
            return
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
            return
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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
