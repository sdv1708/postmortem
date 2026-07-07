"""Reasoning/retrieval provenance tests (ADR 0038, PRD #26 user stories 57, 69-73).

These exercise the causal-analysis stage end to end with deterministic fake
Reasoning Roles and assert the persisted provenance: a Model Call Record per
builder, falsifier, support-verifier, and ranker invocation; a Retrieval Trace
with ordered Chunk references including retrieved-but-uncited results; that
Sensitive Evidence is never copied into the provenance tables; and that a
retrieval omission is distinguishable from a model omission.
"""

from __future__ import annotations

import json

from postmortem.models import EvidenceChunk, ModelCallRecord, RetrievalTrace
from postmortem.llm import FakeLLMClient
from postmortem.rca import RcaEvidenceRef
from postmortem.retrieval import (
    DeterministicChunkArtifactRetrievalStrategy,
    RetrievalResult,
)
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService
from postmortem.verification import ClaimSupportJudgment, ClaimSupportStatus

from tests._fakes import (
    FakeClaimSupportVerifier,
    FakeFalsifier,
    FakeIncidentFactExtractor,
)
from postmortem.falsification import FalsificationCounterclaim


BODY = "alpha line\nbeta line\ngamma line\ndelta line"


def _incident(session):
    return IncidentService(session).create(IncidentCreate(title="Provenance incident"))


def _add(session, incident_id, body=BODY, source_type="logs", source_name="api.log"):
    return ArtifactService(session).create(
        incident_id,
        ArtifactCreate(source_type=source_type, source_name=source_name, body=body),
    )


def _two_hypotheses(artifact_id: str) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Alpha",
                    "summary": "Cause alpha.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 2}
                    ],
                },
                {
                    "title": "Beta",
                    "summary": "Cause beta.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 3, "line_end": 4}
                    ],
                },
            ]
        }
    )


def _run(
    session,
    incident_id,
    builder_json,
    *,
    falsifier,
    support_verifier=None,
    retrieval_strategy=None,
    usage=None,
):
    return AnalysisService(
        session,
        llm_client=FakeLLMClient([builder_json], label="fake-model", usage=usage),
        claim_support_verifier=support_verifier or FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=falsifier,
        retrieval_strategy=retrieval_strategy,
    ).start_run(incident_id, AnalysisRunCreate())


def _records(session, run_id, role=None):
    stmt = session.query(ModelCallRecord).filter(ModelCallRecord.run_id == run_id)
    if role is not None:
        stmt = stmt.filter(ModelCallRecord.role == role)
    return list(stmt.order_by(ModelCallRecord.sequence))


def _traces(session, run_id, role=None):
    stmt = session.query(RetrievalTrace).filter(RetrievalTrace.run_id == run_id)
    if role is not None:
        stmt = stmt.filter(RetrievalTrace.role == role)
    return list(stmt.order_by(RetrievalTrace.sequence))


def test_model_call_records_persisted_for_every_reasoning_role(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    run = _run(
        fresh_session,
        incident.id,
        _two_hypotheses(artifact.id),
        falsifier=FakeFalsifier(),
        usage={"total_tokens": 11},
    )
    fresh_session.commit()
    assert run.status == "succeeded"

    roles = {r.role for r in _records(fresh_session, run.id)}
    # The four causal roles named in the AC, plus the stage-2 extractor.
    assert {"incident_facts", "builder", "falsifier", "support_verifier", "ranker"} <= roles

    # The builder call funneled through the recording client: it carries the model
    # identity, prompt/response hashes, token usage, the validated structured
    # output, and a link to its Retrieval Trace — but the structured output is the
    # model's own assertions, not Artifact text.
    (builder,) = _records(fresh_session, run.id, "builder")
    assert builder.model_identity == "fake-model"
    assert builder.prompt_version == "rca-4"
    assert builder.schema_version == "rca-output-1"
    assert builder.input_hash and builder.output_hash
    assert builder.usage == {"total_tokens": 11}
    assert "hypotheses" in builder.structured_output
    assert builder.retrieval_trace_id is not None

    # The falsifier challenged both initial hypotheses: one record per challenge,
    # each linked to a Falsification Retrieval trace. The fake role makes no model
    # call, so its identity is the role version with no usage/hashes.
    falsifier = _records(fresh_session, run.id, "falsifier")
    assert len(falsifier) == 2
    assert all(r.model_identity == "fake-falsifier-0" for r in falsifier)
    assert all(r.usage is None and r.input_hash is None for r in falsifier)
    assert all(r.retrieval_trace_id is not None for r in falsifier)

    # Support was judged for both hypotheses (both carry verified citations), and
    # each support judgment links to an input trace of the evidence it saw, so an
    # input omission is diagnosable separately from a reasoning outcome (story 69).
    support = _records(fresh_session, run.id, "support_verifier")
    assert len(support) == 2
    assert all(r.retrieval_trace_id is not None for r in support)
    assert all(r.structured_output == {"status": "supported"} for r in support)

    # The deterministic ranker records its own version as model identity, no usage.
    # It is a synthesis role over the candidate handoff, not a retrieval role, so it
    # has no retrieval trace by design (ADR 0038); its inputs are the ordered ids.
    (ranker,) = _records(fresh_session, run.id, "ranker")
    assert ranker.model_identity == "deterministic-advisory-ranker-1"
    assert ranker.usage is None
    assert ranker.retrieval_trace_id is None
    assert "rankings" in ranker.structured_output


def test_support_record_only_when_verifier_consulted(fresh_session):
    """A deterministic short-circuit (no verified citation) makes no model call.

    Distinguishing model omission honestly: a hypothesis with no resolvable
    citation is judged unsupported without a model, so no support Model Call Record
    is written for it — the provenance reflects which judgments invoked a model.
    """
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # Alpha cites a valid line; Beta cites a line that does not exist, so its
    # citation never verifies and support short-circuits with no model call.
    builder = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Alpha",
                    "summary": "Cause alpha.",
                    "supporting_evidence": [
                        {"artifact_id": artifact.id, "line_start": 1, "line_end": 1}
                    ],
                },
                {
                    "title": "Beta",
                    "summary": "Cause beta.",
                    "supporting_evidence": [
                        {"artifact_id": artifact.id, "line_start": 999, "line_end": 999}
                    ],
                },
            ]
        }
    )
    run = _run(fresh_session, incident.id, builder, falsifier=FakeFalsifier())
    fresh_session.commit()
    assert run.status == "succeeded"
    # Only Alpha's support was consulted; Beta short-circuited.
    assert len(_records(fresh_session, run.id, "support_verifier")) == 1


def test_retrieval_traces_record_ordered_uncited_chunks(fresh_session):
    """Falsification Retrieval records every run chunk, flagging uncited ones.

    The falsifier sees all run artifacts; with no counterclaims it cites nothing,
    so its trace shows retrieved-but-uncited chunks — the signal that the evidence
    was in front of the model and ignored (model omission), distinct from never
    being retrieved (PRD user story 70).
    """
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    run = _run(
        fresh_session,
        incident.id,
        _two_hypotheses(artifact.id),
        falsifier=FakeFalsifier(),  # default: no counterclaims, cites nothing
    )
    fresh_session.commit()
    assert run.status == "succeeded"

    run_chunk_ids = {
        c.id
        for c in fresh_session.query(EvidenceChunk).filter(EvidenceChunk.run_id == run.id)
    }
    assert run_chunk_ids  # stage 1 produced chunks

    falsifier_traces = _traces(fresh_session, run.id, "falsifier")
    assert len(falsifier_traces) == 2
    for trace in falsifier_traces:
        # Falsification Retrieval spans all run chunks, ordered by sequence.
        traced_ids = [c["chunk_id"] for c in trace.chunk_refs]
        assert set(traced_ids) == run_chunk_ids
        seqs = [c["sequence"] for c in trace.chunk_refs]
        assert seqs == sorted(seqs)
        # The falsifier cited nothing, so every retrieved chunk is uncited.
        assert all(c["cited"] is False for c in trace.chunk_refs)


def test_builder_trace_marks_cited_chunks(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    run = _run(
        fresh_session,
        incident.id,
        _two_hypotheses(artifact.id),
        falsifier=FakeFalsifier(),
    )
    fresh_session.commit()
    assert run.status == "succeeded"

    (builder_trace,) = _traces(fresh_session, run.id, "builder")
    assert builder_trace.strategy_version == DeterministicChunkArtifactRetrievalStrategy.version
    assert builder_trace.chunk_refs
    # The builder cited lines spanning the whole 4-line artifact, so its single
    # chunk is marked cited.
    assert any(c["cited"] for c in builder_trace.chunk_refs)


def test_provenance_does_not_duplicate_sensitive_evidence(fresh_session):
    """No Artifact text reaches provenance, even when the model quotes it.

    A real model can copy a secret/log line from the prompt into a free-text
    field — a hypothesis summary, a counterclaim statement, a support rationale.
    Provenance must store only the validated *outcome skeleton* (citations as
    references, counts, statuses), so a marker repeated into those free-text
    fields must never appear in any Model Call Record or Retrieval Trace (PRD #26
    user stories 71, 73), even though it legitimately lives in the product tables
    and the cited EvidenceRef snippet.
    """
    marker = "ZZSENSITIVEMARKERZZ"
    incident = _incident(fresh_session)
    body = f"alpha {marker} line\nbeta line\ngamma line\ndelta line"
    artifact = _add(fresh_session, incident.id, body=body)
    fresh_session.commit()

    # The model quotes the marker into the hypothesis summary (free text)...
    builder = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Alpha",
                    "summary": f"Cause alpha, quoting {marker} from the log.",
                    "supporting_evidence": [
                        {"artifact_id": artifact.id, "line_start": 1, "line_end": 1}
                    ],
                }
            ]
        }
    )
    run = _run(
        fresh_session,
        incident.id,
        builder,
        # ...and into a counterclaim statement, and the support rationale.
        falsifier=FakeFalsifier(
            counterclaims=[
                FalsificationCounterclaim(
                    statement=f"Weakness quoting {marker} verbatim.",
                    evidence=[RcaEvidenceRef(artifact_id=artifact.id, line_start=1, line_end=1)],
                )
            ]
        ),
        support_verifier=FakeClaimSupportVerifier(
            status=ClaimSupportStatus.SUPPORTED,
            rationale=f"Supported because the log says {marker}.",
        ),
    )
    fresh_session.commit()
    assert run.status == "succeeded"

    from postmortem.models import EvidenceRef, Hypothesis

    # The marker legitimately lives in the product tables and the cited snippet...
    assert any(
        marker in h.summary
        for h in fresh_session.query(Hypothesis).filter(Hypothesis.run_id == run.id)
    )
    assert any(
        marker in ref.snippet for ref in fresh_session.query(EvidenceRef).all()
    )

    # ...but never in any provenance row (records or traces).
    blob = json.dumps(
        [
            {
                "model_identity": r.model_identity,
                "structured_output": r.structured_output,
                "input_hash": r.input_hash,
                "output_hash": r.output_hash,
                "usage": r.usage,
            }
            for r in _records(fresh_session, run.id)
        ]
        + [
            {"query": t.query, "chunk_refs": t.chunk_refs, "strategy": t.strategy_version}
            for t in _traces(fresh_session, run.id)
        ]
    )
    assert marker not in blob


class _SubsetRetrieval:
    """Retrieval strategy that drops the last chunk to model a retrieval omission.

    The builder thus never receives that chunk (retrieval omission), while the
    falsifier's all-artifacts retrieval still does (where it can be retrieved-but-
    uncited — model omission), so a single run exhibits both signals.
    """

    version = "subset-retrieval-test-0"

    def select_for_rca(self, *, session, run, artifacts, timeline_events):
        full = DeterministicChunkArtifactRetrievalStrategy().select_for_rca(
            session=session, run=run, artifacts=artifacts, timeline_events=timeline_events
        )
        return RetrievalResult(
            artifacts=full.artifacts, chunks=full.chunks[:-1], query=full.query
        )


def test_retrieval_omission_distinguishable_from_model_omission(fresh_session):
    incident = _incident(fresh_session)
    # A long log so chunking yields multiple windows (logs window = 40 lines).
    body = "\n".join(f"2026-05-09T14:{n % 60:02d}:00Z log line {n}" for n in range(1, 91))
    artifact = _add(fresh_session, incident.id, body=body)
    fresh_session.commit()

    # The builder cites only line 1 (in the first chunk); later chunks are uncited.
    builder = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Solo",
                    "summary": "Single cause.",
                    "supporting_evidence": [
                        {"artifact_id": artifact.id, "line_start": 1, "line_end": 1}
                    ],
                }
            ]
        }
    )
    run = _run(
        fresh_session,
        incident.id,
        builder,
        falsifier=FakeFalsifier(),
        retrieval_strategy=_SubsetRetrieval(),
    )
    fresh_session.commit()
    assert run.status == "succeeded"

    run_chunk_ids = {
        c.id
        for c in fresh_session.query(EvidenceChunk).filter(EvidenceChunk.run_id == run.id)
    }
    assert len(run_chunk_ids) >= 2  # the body chunked into multiple windows

    (builder_trace,) = _traces(fresh_session, run.id, "builder")
    builder_ids = {c["chunk_id"] for c in builder_trace.chunk_refs}
    # Retrieval omission: at least one run chunk was never handed to the builder.
    omitted_from_retrieval = run_chunk_ids - builder_ids
    assert omitted_from_retrieval

    # The same chunk(s) the builder never retrieved WERE retrieved by the falsifier
    # but cited by nothing — model omission. The two are therefore distinguishable
    # from the persisted provenance alone.
    falsifier_trace = _traces(fresh_session, run.id, "falsifier")[0]
    falsifier_by_id = {c["chunk_id"]: c for c in falsifier_trace.chunk_refs}
    for chunk_id in omitted_from_retrieval:
        assert chunk_id in falsifier_by_id  # retrieved by the falsifier
        assert falsifier_by_id[chunk_id]["cited"] is False  # but ignored by the model


def test_provenance_cleared_and_regenerated_on_stage_retry(fresh_session):
    """A stage-3 retry clears its own provenance so records never duplicate.

    The builder fails its first attempt (malformed JSON) then succeeds on the
    retry; exactly one builder Model Call Record and one builder Retrieval Trace
    survive (ADR 0029 idempotency).
    """
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    good = _two_hypotheses(artifact.id)
    run = AnalysisService(
        fresh_session,
        # First builder attempt is malformed (fails stage 3); the retry succeeds.
        llm_client=FakeLLMClient(["not json", good], label="fake-model"),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=FakeFalsifier(),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    assert len(_records(fresh_session, run.id, "builder")) == 1
    assert len(_traces(fresh_session, run.id, "builder")) == 1
