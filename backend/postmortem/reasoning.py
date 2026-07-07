"""Bounded causal analysis: Reasoning Budgets, Runtime Reasoning Gates, and
Targeted Repair (ADR 0043, PRD #26 user stories 59-68).

The Causal Analysis Stage (stage 3) drives several Reasoning Roles — the
builder, the falsifier, the advisory ranker, and the semantic support verifier.
Without bounds, a single role can loop, blow the token budget, or ship
mechanically invalid output as product state. This module supplies the three
deterministic controls that keep the stage bounded and auditable:

* ``ReasoningBudget`` — the recorded per-role and stage limits for retrieval,
  model input, model output, and calls, with capacity reserved for exactly one
  Targeted Repair per role (CONTEXT "Reasoning Budget"). It is stamped into
  Experiment Metadata so a run records the bounds it actually ran under.
* ``ReasoningGateError`` — a Runtime Reasoning Gate failure: a deterministic
  contract violation (schema invalidity, incomplete coverage, an uncited
  Counterclaim, a duplicate hypothesis, a missing dimensioned rationale, a
  configured-limit violation, or a citation-integrity failure). It carries the
  validation errors so a repair attempt can act on them.
* ``targeted_repair`` — the single bounded re-invocation of a failed role using
  its validation errors, without rerunning successful roles. If the repair does
  not resolve the gate, or the budget is exhausted, the stage fails with a
  controlled ``CausalAnalysisError`` code rather than degrading to builder-only
  output (PRD user stories 59-64).

Nothing here stores Sensitive Evidence: gate errors and failure details are the
deterministic contract messages the gates produce, never Artifact text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TypeVar


# The version stamped into Experiment Metadata beside the budget values so a
# budget-shape change is comparable across runs (ADR 0025 / 0043).
REASONING_BUDGET_VERSION = "causal-budget-2"


# --- Controlled failure codes (ADR 0043) ------------------------------------
#
# A failed Causal Analysis Stage records one of these machine-readable codes so
# the failed-run API and UI can explain *why* the stage failed without exposing
# raw Sensitive Evidence (PRD user story 68 / AC #5). The first group are the
# Runtime Reasoning Gate codes carried by a ``ReasoningGateError``; the second
# group are the terminal stage-failure codes on a ``CausalAnalysisError``.

# Runtime Reasoning Gate codes.
GATE_SCHEMA_INVALID = "schema_invalid"
GATE_CHALLENGE_COVERAGE_INCOMPLETE = "challenge_coverage_incomplete"
GATE_RANKING_COVERAGE_INCOMPLETE = "ranking_coverage_incomplete"
GATE_UNCITED_COUNTERCLAIM = "uncited_counterclaim"
GATE_DUPLICATE_HYPOTHESIS = "duplicate_hypothesis"
GATE_MISSING_DIMENSIONAL_RATIONALE = "missing_dimensional_rationale"
GATE_LIMIT_EXCEEDED = "limit_exceeded"
GATE_CITATION_INTEGRITY_FAILURE = "citation_integrity_failure"

GATE_CODES: frozenset[str] = frozenset(
    {
        GATE_SCHEMA_INVALID,
        GATE_CHALLENGE_COVERAGE_INCOMPLETE,
        GATE_RANKING_COVERAGE_INCOMPLETE,
        GATE_UNCITED_COUNTERCLAIM,
        GATE_DUPLICATE_HYPOTHESIS,
        GATE_MISSING_DIMENSIONAL_RATIONALE,
        GATE_LIMIT_EXCEEDED,
        GATE_CITATION_INTEGRITY_FAILURE,
    }
)

# Terminal stage-failure codes.
FAILURE_REPAIR_EXHAUSTED = "repair_exhausted"
FAILURE_BUDGET_EXHAUSTED = "budget_exhausted"
# A structural violation that one role re-invocation could not plausibly fix
# (e.g. a forbidden second expansion round) fails immediately with this code.
FAILURE_LIMIT_EXCEEDED = "limit_exceeded"

FAILURE_CODES: frozenset[str] = frozenset(
    {FAILURE_REPAIR_EXHAUSTED, FAILURE_BUDGET_EXHAUSTED, FAILURE_LIMIT_EXCEEDED}
)


class ReasoningGateError(Exception):
    """A Runtime Reasoning Gate rejected a role's output (ADR 0043).

    ``code`` is one of ``GATE_CODES``; ``errors`` are the deterministic
    validation messages the gate produced, which the Targeted Repair feeds back
    to the role so its single re-invocation is informed rather than blind. These
    messages are gate contract text (counts, ids, line ranges) — never Artifact
    text — so they are safe to persist and surface.
    """

    def __init__(self, code: str, errors: tuple[str, ...] | list[str]) -> None:
        self.code = code
        self.errors: tuple[str, ...] = tuple(errors)
        super().__init__(f"{code}: {'; '.join(self.errors)}")


class CausalAnalysisError(RuntimeError):
    """A terminal, controlled Causal Analysis Stage failure (ADR 0043).

    Raised when a Targeted Repair did not resolve a gate, when the Reasoning
    Budget is exhausted, or when a structural limit is violated. It fails stage 3
    with a machine-readable ``code`` and names the ``substep`` (the role and
    invocation) that failed, so the failed-run diagnostics explain the failure
    without exposing Sensitive Evidence (PRD user stories 63-64, 68). The stage
    must never degrade to a successful builder-only run after this is raised.
    """

    def __init__(
        self,
        code: str,
        *,
        substep: str,
        detail: str,
        gate_code: str | None = None,
    ) -> None:
        self.code = code
        self.substep = substep
        self.detail = detail
        # The underlying gate code, when the terminal failure was a gate that a
        # repair could not resolve. Kept distinct from ``code`` so diagnostics can
        # show both "repair exhausted" and "...because the ranking gate failed".
        self.gate_code = gate_code
        super().__init__(f"causal analysis failed [{code}] at {substep}: {detail}")


@dataclass(frozen=True)
class ReasoningBudget:
    """Recorded per-role and stage limits for the Causal Analysis Stage (ADR 0043).

    The limits bound retrieval breadth, model input/output size, and call counts
    so a run's cost is predictable (PRD user stories 65-67). ``max_calls_per_role``
    is the *normal* per-role ceiling; ``repair_calls_per_role`` is reserved on top
    of it for Targeted Repair, so a normal call can never consume the recovery
    allowance (CONTEXT "Reasoning Budget vs Targeted Repair"). ``max_total_calls``
    bounds the whole stage across every role.

    Zero is treated as "unbounded" for a dimension so a run that does not measure
    tokens (e.g. an offline or fake-role test) is never failed for a limit it has
    no signal for; the call-count and retrieval bounds always apply.
    """

    max_initial_hypotheses: int = 5
    max_proposed_hypotheses: int = 0
    max_final_hypotheses: int = 5
    max_retrieval_chunks_per_role: int = 200
    max_input_tokens_per_role: int = 0
    max_output_tokens_per_role: int = 0
    max_calls_per_role: int = 12
    repair_calls_per_role: int = 1
    max_total_calls: int = 64

    def as_metadata(self) -> dict[str, int | str]:
        """Flatten the budget for Experiment Metadata storage (ADR 0025 / 0043)."""
        return {
            "version": REASONING_BUDGET_VERSION,
            "max_initial_hypotheses": self.max_initial_hypotheses,
            "max_proposed_hypotheses": self.max_proposed_hypotheses,
            "max_final_hypotheses": self.max_final_hypotheses,
            "max_retrieval_chunks_per_role": self.max_retrieval_chunks_per_role,
            "max_input_tokens_per_role": self.max_input_tokens_per_role,
            "max_output_tokens_per_role": self.max_output_tokens_per_role,
            "max_calls_per_role": self.max_calls_per_role,
            "repair_calls_per_role": self.repair_calls_per_role,
            "max_total_calls": self.max_total_calls,
        }


DEFAULT_REASONING_BUDGET = ReasoningBudget()


@dataclass
class _RoleUsage:
    calls: int = 0
    repair_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    retrieval_chunks: int = 0


class BudgetLedger:
    """Tracks Reasoning Budget consumption for one Causal Analysis Stage run (ADR 0043).

    Charges are deterministic and per-role. A normal call charges against
    ``max_calls_per_role`` and ``max_total_calls``; a repair charges against the
    separate ``repair_calls_per_role`` reservation, so exhausting normal calls
    never silently eats the repair allowance and vice versa (CONTEXT "Reasoning
    Budget vs Targeted Repair"). Any over-limit charge raises
    ``CausalAnalysisError(code=budget_exhausted)`` with the offending substep, so
    required challenge or ranking coverage is never skipped silently (PRD user
    story 68).
    """

    def __init__(self, budget: ReasoningBudget) -> None:
        self._budget = budget
        self._roles: dict[str, _RoleUsage] = {}
        self._total_calls = 0

    @property
    def budget(self) -> ReasoningBudget:
        return self._budget

    def _usage(self, role: str) -> _RoleUsage:
        return self._roles.setdefault(role, _RoleUsage())

    def charge_call(self, role: str, substep: str) -> None:
        usage = self._usage(role)
        if usage.calls + 1 > self._budget.max_calls_per_role:
            raise CausalAnalysisError(
                FAILURE_BUDGET_EXHAUSTED,
                substep=substep,
                detail=(
                    f"role {role!r} exceeded its call budget of "
                    f"{self._budget.max_calls_per_role}"
                ),
            )
        if self._total_calls + 1 > self._budget.max_total_calls:
            raise CausalAnalysisError(
                FAILURE_BUDGET_EXHAUSTED,
                substep=substep,
                detail=(
                    f"stage exceeded its total call budget of "
                    f"{self._budget.max_total_calls}"
                ),
            )
        usage.calls += 1
        self._total_calls += 1

    def charge_repair(self, role: str, substep: str) -> None:
        usage = self._usage(role)
        if usage.repair_calls + 1 > self._budget.repair_calls_per_role:
            raise CausalAnalysisError(
                FAILURE_BUDGET_EXHAUSTED,
                substep=substep,
                detail=(
                    f"role {role!r} exhausted its reserved repair budget of "
                    f"{self._budget.repair_calls_per_role}"
                ),
            )
        if self._total_calls + 1 > self._budget.max_total_calls:
            raise CausalAnalysisError(
                FAILURE_BUDGET_EXHAUSTED,
                substep=substep,
                detail=(
                    f"stage exceeded its total call budget of "
                    f"{self._budget.max_total_calls}"
                ),
            )
        usage.repair_calls += 1
        self._total_calls += 1

    def observe_usage(self, role: str, usage: dict | None, substep: str) -> None:
        """Accumulate a model call's token usage against the per-role token budget.

        Provider usage shapes differ, so read input tokens from any of the common
        keys and output tokens likewise. A zero budget for a dimension means
        "unmetered" and never fails (an offline/fake role reports no usage).
        """
        if not usage:
            return
        role_usage = self._usage(role)
        role_usage.input_tokens += _read_tokens(usage, ("prompt_tokens", "input_tokens"))
        role_usage.output_tokens += _read_tokens(
            usage, ("completion_tokens", "output_tokens")
        )
        if (
            self._budget.max_input_tokens_per_role
            and role_usage.input_tokens > self._budget.max_input_tokens_per_role
        ):
            raise CausalAnalysisError(
                FAILURE_BUDGET_EXHAUSTED,
                substep=substep,
                detail=(
                    f"role {role!r} exceeded its input-token budget of "
                    f"{self._budget.max_input_tokens_per_role}"
                ),
            )
        if (
            self._budget.max_output_tokens_per_role
            and role_usage.output_tokens > self._budget.max_output_tokens_per_role
        ):
            raise CausalAnalysisError(
                FAILURE_BUDGET_EXHAUSTED,
                substep=substep,
                detail=(
                    f"role {role!r} exceeded its output-token budget of "
                    f"{self._budget.max_output_tokens_per_role}"
                ),
            )

    def observe_retrieval(self, role: str, chunk_count: int, substep: str) -> None:
        """Bound a single retrieval's breadth for a role (ADR 0043).

        The cap is on the breadth of one retrieval, not a running sum: a role that
        re-retrieves the same set across substeps (the falsifier re-runs
        Falsification Retrieval per challenge) is not penalized for revisiting
        evidence. The snapshot keeps the widest retrieval seen.
        """
        role_usage = self._usage(role)
        role_usage.retrieval_chunks = max(role_usage.retrieval_chunks, chunk_count)
        if chunk_count > self._budget.max_retrieval_chunks_per_role:
            raise CausalAnalysisError(
                FAILURE_BUDGET_EXHAUSTED,
                substep=substep,
                detail=(
                    f"role {role!r} exceeded its retrieval budget of "
                    f"{self._budget.max_retrieval_chunks_per_role} chunks"
                ),
            )

    def snapshot(self) -> dict:
        """A JSON-safe summary of consumption for stage-event usage (ADR 0021/0043)."""
        return {
            "total_calls": self._total_calls,
            "roles": {
                role: {
                    "calls": usage.calls,
                    "repair_calls": usage.repair_calls,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "retrieval_chunks": usage.retrieval_chunks,
                }
                for role, usage in sorted(self._roles.items())
            },
        }


def _read_tokens(usage: dict, keys: tuple[str, ...]) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def append_repair_feedback(user: str, feedback: tuple[str, ...]) -> str:
    """Append a Targeted Repair's deterministic validation errors to a prompt (ADR 0043).

    The single repair re-invocation is *informed*: the gate's contract messages
    (counts, ids, line ranges — never Artifact text) are appended so the role can
    correct the specific violation rather than blindly replay the same request. A
    role that ignores the feedback (a deterministic role, or a fake) is unaffected;
    with no feedback (the first attempt) the prompt is returned unchanged. This is
    shared so every Reasoning Role — builder, falsifier, ranker — phrases the repair
    instruction identically.
    """
    if not feedback:
        return user
    bullets = "\n".join(f"- {error}" for error in feedback)
    return (
        f"{user}\n\n"
        "The previous response was rejected by a deterministic validation gate. "
        "Correct exactly these problems and return only valid output:\n"
        f"{bullets}"
    )


T = TypeVar("T")


def targeted_repair(
    *,
    role: str,
    substep: str,
    ledger: BudgetLedger,
    produce: Callable[[tuple[str, ...]], T],
    validate: Callable[[T], None],
) -> T:
    """Invoke a Reasoning Role through one bounded Targeted Repair (ADR 0043).

    ``produce(feedback)`` invokes the role; ``feedback`` is empty on the first
    attempt and the gate's validation errors on the single repair. ``validate``
    runs the Runtime Reasoning Gate and raises ``ReasoningGateError`` when the
    output is mechanically invalid.

    The flow (PRD user stories 59-64):

    1. Charge a normal call, produce once, and validate. If the gate passes, the
       output is returned — successful roles are never rerun.
    2. On a gate failure, charge the *reserved* repair call and re-invoke only
       this role with the validation errors. Charging may raise
       ``CausalAnalysisError(budget_exhausted)`` if the repair reservation or the
       total-call budget is gone.
    3. Validate the repaired output. If the gate still fails, raise
       ``CausalAnalysisError(repair_exhausted)`` carrying the unresolved gate code
       and its errors. The stage fails; it does not fall back to partial output.

    A ``ReasoningGateError`` is honored whether it is raised while *producing* the
    output (a role that cannot produce schema-valid output at all, e.g. a falsifier
    that cannot challenge a hypothesis) or while *validating* it, so both shapes of
    mechanically invalid role output travel the same single-repair path. The caller
    charges token/retrieval usage inside ``produce`` (it owns the model response),
    so this helper stays focused on the call-count budget and the gate/repair
    contract.
    """

    def attempt(feedback: tuple[str, ...]) -> T:
        output = produce(feedback)
        validate(output)
        return output

    ledger.charge_call(role, substep)
    try:
        return attempt(())
    except ReasoningGateError as first:
        ledger.charge_repair(role, substep)
        try:
            return attempt(first.errors)
        except ReasoningGateError as second:
            raise CausalAnalysisError(
                FAILURE_REPAIR_EXHAUSTED,
                substep=substep,
                detail="; ".join(second.errors),
                gate_code=second.code,
            ) from second
