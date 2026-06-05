from __future__ import annotations

import json

from postmortem.llm import FakeLLMClient
from postmortem.models import EvidenceRef, RunStageEvent
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService
from postmortem.services.stages import PipelineStageRunner
from postmortem.verification import (
    CITATION_VERIFIER_VERSION,
    CitationIntegrityStatus,
)

from tests._fakes import FakeClaimSupportVerifier


BODY = (
    "2026-05-09T14:28:31Z deploy v184 rolled out\n"
    "2026-05-09T14:31:10Z db connection pool exhausted\n"
    "2026-05-09T14:32:02Z api 500 rate climbing"
)


def _incident(session):
    return IncidentService(session).create(IncidentCreate(title="Citation integrity"))


def _add(session, incident_id):
    return ArtifactService(session).create(
        incident_id,
        ArtifactCreate(source_type="logs", source_name="api.log", body=BODY),
    )


def _hypotheses_json(artifact_id: str) -> str:
    # Cites supporting + contradicting + impact + remediation evidence so the
    # verification stage exercises all four EvidenceRef owner types.
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Deploy v184 regressed the pool",
                    "summary": "v184 preceded pool exhaustion and the 500 spike.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 2}
                    ],
                    "contradicting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 3, "line_end": 3}
                    ],
                    "impact_claims": [
                        {
                            "description": "API served 500s",
                            "evidence": [
                                {"artifact_id": artifact_id, "line_start": 3, "line_end": 3}
                            ],
                        }
                    ],
                    "remediation_items": [
                        {
                            "description": "Roll back v184",
                            "evidence": [
                                {"artifact_id": artifact_id, "line_start": 1, "line_end": 1}
                            ],
                        }
                    ],
                }
            ]
        }
    )


def _all_refs(session, run_id):
    return list(session.query(EvidenceRef))


def _verify_event(session, run_id):
    return (
        session.query(RunStageEvent)
        .filter(
            RunStageEvent.run_id == run_id,
            RunStageEvent.stage == "verifying_citations",
        )
        .order_by(RunStageEvent.sequence.desc())
        .first()
    )


class _FakeVerifier:
    """A swappable stand-in proving the verifier boundary is real (ADR 0009)."""

    version = "fake-verifier-9"

    def __init__(self, result: CitationIntegrityStatus) -> None:
        self._result = result
        self.targets: list = []

    def verify(self, target, artifact_bodies):
        self.targets.append(target)
        return self._result


def test_pipeline_stamps_every_citation_verified(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    fake = FakeLLMClient([_hypotheses_json(artifact.id)], label="fake-model")
    claim_support = FakeClaimSupportVerifier()
    run = AnalysisService(
        fresh_session, llm_client=fake, claim_support_verifier=claim_support
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    # Both verifier passes (integrity + claim support) are stamped (ADR 0025).
    assert run.verifier_version == f"{CITATION_VERIFIER_VERSION}+{claim_support.version}"

    refs = _all_refs(fresh_session, run.id)
    # Timeline (3 timestamped lines) + hypothesis supporting/contradicting +
    # impact + remediation citations were all produced and verified.
    assert len(refs) >= 6
    assert {ref.verifier_status for ref in refs} == {"verified"}

    event = _verify_event(fresh_session, run.id)
    assert event.status == "succeeded"
    assert "citation_integrity_failure" not in event.warning_codes


def test_reverification_flags_a_tampered_snippet_without_failing_the_run(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    fake = FakeLLMClient([_hypotheses_json(artifact.id)], label="fake-model")
    run = AnalysisService(
        fresh_session, llm_client=fake, claim_support_verifier=FakeClaimSupportVerifier()
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()
    assert run.status == "succeeded"

    # Simulate citation drift: corrupt one stored snippet so it no longer matches
    # its cited lines, then re-run the deterministic verification stage.
    target = fresh_session.query(EvidenceRef).first()
    target.snippet = target.snippet + " DRIFTED"
    fresh_session.flush()

    outcome = PipelineStageRunner(fresh_session)("verifying_citations", 1, run)
    fresh_session.flush()

    fresh_session.refresh(target)
    assert target.verifier_status == "snippet_mismatch"
    # The broken citation is flagged, not deleted and not a run failure
    # (ADR 0015 / CONTEXT "flagged, not deleted"). The warning is deduped.
    assert outcome == {"warning_codes": ["citation_integrity_failure"]}
    # Untampered citations re-verify cleanly.
    intact = [r for r in _all_refs(fresh_session, run.id) if r.id != target.id]
    assert {r.verifier_status for r in intact} == {"verified"}


def test_citation_verifier_boundary_is_swappable(fresh_session):
    incident = _incident(fresh_session)
    _add(fresh_session, incident.id)
    fresh_session.commit()

    # Offline default → no hypotheses, but the timestamped lines still yield
    # timeline EvidenceRefs for the verifier to act on.
    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    fake_verifier = _FakeVerifier(CitationIntegrityStatus.ARTIFACT_MISSING)
    outcome = PipelineStageRunner(fresh_session, verifier=fake_verifier)(
        "verifying_citations", 1, run
    )
    fresh_session.flush()

    # The injected verifier was actually consulted for each citation, and the
    # stage persisted exactly what it returned.
    assert fake_verifier.targets, "the injected verifier was never called"
    refs = _all_refs(fresh_session, run.id)
    assert refs
    assert {ref.verifier_status for ref in refs} == {"artifact_missing"}
    assert outcome == {"warning_codes": ["citation_integrity_failure"]}
