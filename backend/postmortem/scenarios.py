from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

import yaml
from pydantic import ValidationError

from .falsification import (
    FALSIFIER_VERSION,
    MAX_PROPOSED_HYPOTHESES,
    HypothesisChallengeOutput,
)
from .incident_facts import INCIDENT_FACT_EXTRACTOR_VERSION, IncidentFactsOutput
from .llm import LLMResponse
from .rca import RcaGenerationOutput
from .verification import ClaimSupportJudgment, ClaimSupportStatus, ClaimToVerify

# File-based synthetic Incident Scenarios (ADR 0007). Fixtures live as files —
# a Scenario Manifest, evidence files, and a Ground-Truth Postmortem — so demo
# seeding and evaluation stay reproducible and the canonical deploy scenario is
# not the only shape the pipeline is tuned against (ADR 0006).
SCENARIOS_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "scenarios"

# Versioned identity for the bundled scenario claim-support replay, recorded in
# Experiment Metadata (ADR 0025) so a replayed demo run is never mistaken for a
# live semantic judgment.
SCENARIO_CLAIM_SUPPORT_VERSION: Final[str] = "scenario-replay-claim-support-1"


class ScenarioValidationError(ValueError):
    """A scenario fixture is malformed or references missing files/content.

    Raised by ``load_scenario`` so a broken demo fixture fails fast and loudly
    (ADR 0007 reproducibility) rather than producing a half-seeded incident.
    """


class ScenarioNotFoundError(LookupError):
    """No scenario fixture with the requested id exists under the scenarios dir."""


@dataclass(frozen=True)
class ScenarioEvidence:
    """One evidence Artifact described by the manifest, with its loaded body."""

    source_type: str
    source_name: str
    body: str


@dataclass(frozen=True)
class ClaimSupportOverride:
    """A scenario-declared claim-support verdict for claims matching ``match``."""

    match: str
    status: ClaimSupportStatus
    rationale: str


@dataclass(frozen=True)
class LoadedScenario:
    """A validated scenario fixture ready to seed into product data.

    ``rca_replay`` is the parsed RCA model output that still cites evidence by
    ``source_name``; it is resolved to artifact ids at seed time so human authors
    never hand-write UUIDs.
    """

    id: str
    title: str
    severity: str | None
    status: str
    summary: str | None
    started_at: str | None
    detected_at: str | None
    resolved_at: str | None
    ambiguity_notes: str | None
    evaluation_tags: tuple[str, ...]
    expected_hypothesis_families: tuple[str, ...]
    ground_truth_postmortem: str
    evidence: tuple[ScenarioEvidence, ...]
    rca_replay: dict
    # Run-level incident-facts replay (ADR 0033): impact claims produced in stage
    # 2, still citing by ``source_name`` until resolved to artifact ids at seed
    # time. Defaults to empty when a scenario declares no observed impact.
    incident_facts_replay: dict
    # Falsifier replay (ADR 0034): a mapping of hypothesis title -> bundled
    # Hypothesis Challenge, still citing by ``source_name``. Covers every replay
    # hypothesis so the demo's stage-3 challenge coverage is complete and offline.
    # Empty when the scenario declares no hypotheses (e.g. insufficient evidence).
    falsification_replay: dict
    claim_support_overrides: tuple[ClaimSupportOverride, ...]


_VALID_SOURCE_TYPES = {
    "incident_notes",
    "logs",
    "stack_trace",
    "deployment_notes",
    "other",
}


def _require(manifest: Mapping, key: str, scenario_dir: Path) -> object:
    if key not in manifest:
        raise ScenarioValidationError(f"{scenario_dir.name}/scenario.yaml is missing required key {key!r}")
    return manifest[key]


def _read_text(path: Path, scenario_dir: Path, label: str) -> str:
    if not path.is_file():
        raise ScenarioValidationError(
            f"{scenario_dir.name}: {label} references missing file {path.name!r}"
        )
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    # Drop a single trailing newline so the artifact's last line is real content
    # and 1-based line numbers match what the replay and evidence panel show.
    if text.endswith("\n"):
        text = text[:-1]
    if not text.strip():
        raise ScenarioValidationError(f"{scenario_dir.name}: {label} file {path.name!r} is empty")
    return text


def load_scenario(scenario_id: str, base_dir: Path | None = None) -> LoadedScenario:
    """Load and validate a scenario fixture from its directory (ADR 0007).

    Fails fast (``ScenarioValidationError``) when an evidence ``path`` is missing
    or empty, the Ground-Truth Postmortem is missing or empty, a replay ref names
    an unknown ``source_name``, or a replay line range falls outside the cited
    evidence file — so a broken demo fixture can never be silently half-seeded.
    """
    base = base_dir or SCENARIOS_DIR
    scenario_dir = base / scenario_id
    manifest_path = scenario_dir / "scenario.yaml"
    if not manifest_path.is_file():
        raise ScenarioNotFoundError(scenario_id)

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ScenarioValidationError(f"{scenario_id}/scenario.yaml is not a mapping")

    declared_id = _require(manifest, "id", scenario_dir)
    if declared_id != scenario_id:
        raise ScenarioValidationError(
            f"scenario id {declared_id!r} does not match its directory {scenario_id!r}"
        )

    evidence_entries = _require(manifest, "evidence", scenario_dir)
    if not isinstance(evidence_entries, list) or not evidence_entries:
        raise ScenarioValidationError(f"{scenario_id}: 'evidence' must be a non-empty list")

    evidence: list[ScenarioEvidence] = []
    bodies_by_name: dict[str, str] = {}
    for entry in evidence_entries:
        source_type = entry.get("source_type")
        source_name = entry.get("source_name")
        rel_path = entry.get("path")
        if not (source_type and source_name and rel_path):
            raise ScenarioValidationError(
                f"{scenario_id}: each evidence entry needs source_type, source_name, and path"
            )
        if source_type not in _VALID_SOURCE_TYPES:
            raise ScenarioValidationError(
                f"{scenario_id}: evidence {source_name!r} has unknown source_type {source_type!r}"
            )
        if source_name in bodies_by_name:
            raise ScenarioValidationError(
                f"{scenario_id}: duplicate evidence source_name {source_name!r}"
            )
        body = _read_text(scenario_dir / rel_path, scenario_dir, f"evidence {source_name!r}")
        evidence.append(ScenarioEvidence(source_type=source_type, source_name=source_name, body=body))
        bodies_by_name[source_name] = body

    # The Ground-Truth Postmortem must exist with real content (ADR 0006 / 0010).
    ground_truth_name = str(_require(manifest, "ground_truth_postmortem", scenario_dir))
    ground_truth = _read_text(
        scenario_dir / ground_truth_name, scenario_dir, "ground_truth_postmortem"
    )

    replay = _require(manifest, "replay", scenario_dir)
    if not isinstance(replay, Mapping) or "rca" not in replay:
        raise ScenarioValidationError(f"{scenario_id}: 'replay' must include an 'rca' file path")
    rca_path = scenario_dir / str(replay["rca"])
    if not rca_path.is_file():
        raise ScenarioValidationError(f"{scenario_id}: replay rca references missing file {replay['rca']!r}")
    try:
        rca_replay = json.loads(rca_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScenarioValidationError(f"{scenario_id}: replay rca is not valid JSON: {exc}") from exc

    _validate_replay_refs(scenario_id, rca_replay, bodies_by_name)
    _validate_replay_schema(scenario_id, rca_replay, bodies_by_name.keys())

    # Run-level incident-facts replay (ADR 0033). Optional: a scenario with no
    # observed impact (e.g. insufficient-evidence) may omit it.
    incident_facts_replay: dict = {"impact_claims": []}
    if "incident_facts" in replay:
        facts_path = scenario_dir / str(replay["incident_facts"])
        if not facts_path.is_file():
            raise ScenarioValidationError(
                f"{scenario_id}: replay incident_facts references missing file {replay['incident_facts']!r}"
            )
        try:
            incident_facts_replay = json.loads(facts_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ScenarioValidationError(
                f"{scenario_id}: replay incident_facts is not valid JSON: {exc}"
            ) from exc
        _validate_replay_refs(scenario_id, incident_facts_replay, bodies_by_name)
        _validate_incident_facts_schema(scenario_id, incident_facts_replay, bodies_by_name.keys())

    # Falsifier replay (ADR 0034). Required whenever the RCA replay declares
    # hypotheses, because stage 3 fails without complete challenge coverage; the
    # keys must match the hypothesis titles exactly so the demo is self-validating.
    hypothesis_titles = [
        str(hyp.get("title", "")) for hyp in (rca_replay.get("hypotheses") or [])
    ]
    falsification_replay = _load_falsification_replay(
        scenario_id, scenario_dir, replay, hypothesis_titles, bodies_by_name
    )

    overrides = tuple(
        ClaimSupportOverride(
            match=str(item["match"]),
            status=ClaimSupportStatus(item["status"]),
            rationale=str(item.get("rationale", "")),
        )
        for item in (replay.get("claim_support_overrides") or [])
    )

    return LoadedScenario(
        id=scenario_id,
        title=str(_require(manifest, "title", scenario_dir)),
        severity=_opt_str(manifest.get("severity")),
        status=str(manifest.get("status", "open")),
        summary=_opt_str(manifest.get("summary")),
        started_at=_opt_str(manifest.get("started_at")),
        detected_at=_opt_str(manifest.get("detected_at")),
        resolved_at=_opt_str(manifest.get("resolved_at")),
        ambiguity_notes=_opt_str(manifest.get("ambiguity_notes")),
        evaluation_tags=tuple(str(tag) for tag in manifest.get("evaluation_tags", [])),
        expected_hypothesis_families=tuple(
            str(fam) for fam in manifest.get("expected_hypothesis_families", [])
        ),
        ground_truth_postmortem=ground_truth,
        evidence=tuple(evidence),
        rca_replay=rca_replay,
        incident_facts_replay=incident_facts_replay,
        falsification_replay=falsification_replay,
        claim_support_overrides=overrides,
    )


def _load_falsification_replay(
    scenario_id: str,
    scenario_dir: Path,
    replay: Mapping,
    hypothesis_titles: list[str],
    bodies_by_name: Mapping[str, str],
) -> dict:
    """Load + validate the falsifier replay, enforcing complete challenge coverage.

    A scenario with hypotheses must bundle one challenge per hypothesis title
    (ADR 0034), or the demo's stage 3 would fail its mandatory challenge-coverage
    gate. A scenario with no hypotheses (e.g. insufficient evidence) needs none.
    """
    has_falsification = "falsification" in replay
    if not hypothesis_titles:
        if has_falsification:
            raise ScenarioValidationError(
                f"{scenario_id}: replay declares falsification but no hypotheses to challenge"
            )
        return {}
    if not has_falsification:
        raise ScenarioValidationError(
            f"{scenario_id}: replay has hypotheses but no 'falsification' challenge file"
        )

    falsification_path = scenario_dir / str(replay["falsification"])
    if not falsification_path.is_file():
        raise ScenarioValidationError(
            f"{scenario_id}: replay falsification references missing file {replay['falsification']!r}"
        )
    try:
        falsification_replay = json.loads(falsification_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScenarioValidationError(
            f"{scenario_id}: replay falsification is not valid JSON: {exc}"
        ) from exc
    if not isinstance(falsification_replay, Mapping):
        raise ScenarioValidationError(
            f"{scenario_id}: replay falsification must be a mapping of hypothesis title to challenge"
        )

    # A bundled challenge for an initial hypothesis may introduce Proposed RCA
    # Hypotheses (ADR 0036). Each proposed alternative is itself challenged once in
    # the second pass, so the replay must also bundle a challenge keyed by the
    # proposed title — and that challenge may not propose again (no recursion).
    proposed_titles: list[str] = []
    for title in hypothesis_titles:
        challenge = falsification_replay.get(title)
        if isinstance(challenge, Mapping):
            for proposal in challenge.get("proposed_hypotheses") or []:
                if isinstance(proposal, Mapping) and proposal.get("title"):
                    proposed_titles.append(str(proposal["title"]))
    if len(proposed_titles) > MAX_PROPOSED_HYPOTHESES:
        raise ScenarioValidationError(
            f"{scenario_id}: falsification proposes {len(proposed_titles)} alternatives, "
            f"exceeding the bounded maximum of {MAX_PROPOSED_HYPOTHESES}"
        )
    for proposed_title in proposed_titles:
        proposed_challenge = falsification_replay.get(proposed_title)
        if isinstance(proposed_challenge, Mapping) and (
            proposed_challenge.get("proposed_hypotheses")
        ):
            raise ScenarioValidationError(
                f"{scenario_id}: proposed alternative {proposed_title!r} may not itself "
                "propose further hypotheses (no recursive expansion)"
            )

    covered = set(falsification_replay.keys())
    expected = set(hypothesis_titles) | set(proposed_titles)
    if covered != expected:
        raise ScenarioValidationError(
            f"{scenario_id}: falsification must challenge exactly the replay hypotheses and "
            f"their proposed alternatives; missing {sorted(expected - covered)}, "
            f"unexpected {sorted(covered - expected)}"
        )

    _validate_replay_refs(scenario_id, falsification_replay, bodies_by_name)
    _validate_falsification_schema(scenario_id, falsification_replay, bodies_by_name.keys())
    return dict(falsification_replay)


def list_scenarios(base_dir: Path | None = None) -> list[LoadedScenario]:
    """Load every valid scenario fixture under ``base_dir`` (sorted by id)."""
    base = base_dir or SCENARIOS_DIR
    if not base.is_dir():
        return []
    scenarios: list[LoadedScenario] = []
    for child in sorted(base.iterdir()):
        if (child / "scenario.yaml").is_file():
            scenarios.append(load_scenario(child.name, base))
    return scenarios


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_replay_refs(
    scenario_id: str, rca_replay: object, bodies_by_name: Mapping[str, str]
) -> None:
    """Check every replay citation names a known evidence file and a real range.

    Walks the parsed RCA replay for any node carrying a ``source_name`` and
    confirms the file exists in the scenario and the 1-based inclusive line range
    falls inside it. This makes the fixture self-validating before a single
    artifact is seeded (ADR 0007).
    """

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "source_name" in node:
                source_name = node["source_name"]
                if source_name not in bodies_by_name:
                    raise ScenarioValidationError(
                        f"{scenario_id}: replay cites unknown evidence source {source_name!r}"
                    )
                line_count = len(bodies_by_name[source_name].split("\n"))
                start = node.get("line_start")
                end = node.get("line_end")
                if not (isinstance(start, int) and isinstance(end, int)):
                    raise ScenarioValidationError(
                        f"{scenario_id}: replay citation to {source_name!r} needs integer line_start/line_end"
                    )
                if start < 1 or end < start or end > line_count:
                    raise ScenarioValidationError(
                        f"{scenario_id}: replay cites {source_name!r} lines {start}-{end} "
                        f"outside its {line_count} lines"
                    )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(rca_replay)


def _validate_replay_schema(
    scenario_id: str, rca_replay: object, source_names: object
) -> None:
    """Validate replay shape against the strict RCA output contract (ADR 0028).

    Scenario authors cite by ``source_name`` because real Artifact ids do not
    exist until seeding. For schema validation, use those source names as stable
    placeholder artifact ids; seed time will resolve them to the created rows.
    """
    placeholders = {str(name): str(name) for name in source_names}
    try:
        RcaGenerationOutput.model_validate(resolve_replay_rca(rca_replay, placeholders))
    except (ScenarioValidationError, ValidationError) as exc:
        raise ScenarioValidationError(
            f"{scenario_id}: replay rca violates the strict RCA schema: {exc}"
        ) from exc


def _validate_incident_facts_schema(
    scenario_id: str, facts_replay: object, source_names: object
) -> None:
    """Validate the incident-facts replay against the strict contract (ADR 0028 / 0033)."""
    placeholders = {str(name): str(name) for name in source_names}
    try:
        IncidentFactsOutput.model_validate(resolve_replay_rca(facts_replay, placeholders))
    except (ScenarioValidationError, ValidationError) as exc:
        raise ScenarioValidationError(
            f"{scenario_id}: replay incident_facts violates the strict schema: {exc}"
        ) from exc


def _validate_falsification_schema(
    scenario_id: str, falsification_replay: Mapping, source_names: object
) -> None:
    """Validate each bundled challenge against the strict falsifier contract (ADR 0028 / 0034)."""
    placeholders = {str(name): str(name) for name in source_names}
    resolved = resolve_replay_rca(dict(falsification_replay), placeholders)
    for title, challenge in resolved.items():
        try:
            HypothesisChallengeOutput.model_validate(challenge)
        except (ScenarioValidationError, ValidationError) as exc:
            raise ScenarioValidationError(
                f"{scenario_id}: falsification for {title!r} violates the strict schema: {exc}"
            ) from exc


def resolve_replay_rca(rca_replay: object, source_name_to_id: Mapping[str, str]) -> object:
    """Rewrite a replay's ``source_name`` citations to seeded ``artifact_id``s.

    Returns a new structure (the input is not mutated) shaped exactly like the
    strict RCA output contract (ADR 0028), so the RCA stage validates and then
    resolves each snippet from the stored artifact lines (ADR 0024) — the replay
    never supplies snippet text.
    """
    if isinstance(rca_replay, dict):
        resolved: dict = {}
        for key, value in rca_replay.items():
            if key == "source_name":
                if value not in source_name_to_id:
                    raise ScenarioValidationError(f"replay references unseeded evidence source {value!r}")
                resolved["artifact_id"] = source_name_to_id[value]
            else:
                resolved[key] = resolve_replay_rca(value, source_name_to_id)
        return resolved
    if isinstance(rca_replay, list):
        return [resolve_replay_rca(item, source_name_to_id) for item in rca_replay]
    return rca_replay


class ScenarioReplayLLMClient:
    """Replays a scenario's bundled RCA output instead of calling a model.

    A swappable LLMClient (ADR 0009 / 0011) so the canonical demo and its tests
    run deterministically and offline. It is constructed with the RCA citations
    already resolved to seeded artifact ids, and returns that JSON for the RCA
    stage's single completion. Claim support uses the separate replay verifier,
    so this client is only consulted once per run.
    """

    def __init__(self, scenario_id: str, rca_json: str) -> None:
        self._scenario_id = scenario_id
        self._rca_json = rca_json
        self.calls: list[tuple[str, str]] = []

    @property
    def label(self) -> str:
        return f"scenario-replay:{self._scenario_id}"

    def complete(self, *, system: str, user: str) -> LLMResponse:
        self.calls.append((system, user))
        return LLMResponse(text=self._rca_json, usage={"replay": True})


class ScenarioReplayIncidentFactExtractor:
    """Replays a scenario's bundled run-level incident facts (ADR 0009 / 0033).

    A swappable IncidentFactExtractor so stage 2 produces the scenario's impact
    claims deterministically and offline. Constructed with the facts citations
    already resolved to seeded artifact ids; the stage still resolves snippets
    from the stored lines (ADR 0024), so the replay never supplies snippet text.
    """

    version: Final[str] = INCIDENT_FACT_EXTRACTOR_VERSION

    def __init__(self, scenario_id: str, facts_replay: dict) -> None:
        self._scenario_id = scenario_id
        self._output = IncidentFactsOutput.model_validate(facts_replay)
        self.calls = 0

    def extract(self, *, artifacts, timeline_events) -> IncidentFactsOutput:
        self.calls += 1
        return self._output


class ScenarioReplayFalsifier:
    """Replays a scenario's bundled Hypothesis Challenges (ADR 0009 / 0034).

    A swappable Falsifier so the canonical demo's stage-3 falsifier substep runs
    deterministically and offline. Constructed with the challenge citations
    already resolved to seeded artifact ids; the stage still resolves snippets
    from the stored lines (ADR 0024), so the replay never supplies snippet text.
    Keyed by hypothesis title to match the persisted hypotheses the builder
    replay produced — the loader guarantees one challenge per hypothesis, so the
    demo's mandatory challenge coverage is always complete.
    """

    version: Final[str] = FALSIFIER_VERSION

    def __init__(self, scenario_id: str, falsification_replay: dict) -> None:
        self._scenario_id = scenario_id
        self._by_title = {
            title: HypothesisChallengeOutput.model_validate(challenge)
            for title, challenge in falsification_replay.items()
        }
        self.calls = 0

    def challenge(
        self, *, hypothesis, artifacts, timeline_events, allow_proposals: bool = True
    ) -> HypothesisChallengeOutput:
        self.calls += 1
        output = self._by_title.get(hypothesis.title)
        if output is None:
            # A self-validating fixture never reaches this; failing loudly keeps a
            # mis-keyed challenge from silently dropping coverage (ADR 0034).
            raise ValueError(
                f"scenario {self._scenario_id!r} has no bundled challenge for hypothesis "
                f"{hypothesis.title!r}"
            )
        return output


class ScenarioReplayClaimSupportVerifier:
    """Replays scenario-declared claim-support verdicts (ADR 0009 / 0014).

    Defaults every cited Major Claim to SUPPORTED, but a scenario can declare
    ``claim_support_overrides`` (matched as a case-insensitive substring of the
    claim text) to surface PARTIAL or UNSUPPORTED so the demo shows the full
    support spectrum without a live judge. Recorded version keeps Experiment
    Metadata honest that this was a replay (ADR 0025).
    """

    version: Final[str] = SCENARIO_CLAIM_SUPPORT_VERSION

    def __init__(self, overrides: tuple[ClaimSupportOverride, ...] = ()) -> None:
        self._overrides = overrides
        self.calls: list[ClaimToVerify] = []

    def verify(self, claim: ClaimToVerify) -> ClaimSupportJudgment:
        self.calls.append(claim)
        lowered = claim.claim_text.lower()
        for override in self._overrides:
            if override.match.lower() in lowered:
                return ClaimSupportJudgment(status=override.status, rationale=override.rationale)
        return ClaimSupportJudgment(
            status=ClaimSupportStatus.SUPPORTED,
            rationale="The cited evidence supports the claim.",
        )
