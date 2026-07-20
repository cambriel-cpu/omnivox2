"""Privacy-safe aggregation for repeatable evaluation suites."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from omnivox_protocol import AudioInput, RequestContext

from omnivox_evaluation.aggregation import (
    AccuracySummary,
    CostSummary,
    Percentiles,
    RecoverySummary,
    accuracy_summary,
    cost_summary,
    percentiles,
    recovery_summary,
)
from omnivox_evaluation.metrics import AccuracyReference, RecoveryScenario
from omnivox_evaluation.runner import EvaluationOutcome, EvaluationReport


class EvaluationSuiteError(ValueError):
    """The suite definition or evaluator correlation is invalid."""


class InteractionEvaluator(Protocol):
    """Run one latency-only evaluation interaction."""

    async def run(self, audio: AudioInput, context: RequestContext) -> EvaluationReport:
        """Return content-free results for one interaction."""
        ...


class AnnotatedInteractionEvaluator(Protocol):
    """Run an interaction with optional private measurement inputs."""

    async def run(
        self,
        audio: AudioInput,
        context: RequestContext,
        *,
        accuracy: AccuracyReference | None = None,
        recovery_scenario: RecoveryScenario | None = None,
    ) -> EvaluationReport:
        """Return content-free results for an annotated interaction."""
        ...


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """One private input paired with a non-sensitive case identifier."""

    case_id: str
    audio: AudioInput
    context: RequestContext
    accuracy: AccuracyReference | None = None
    recovery_scenario: RecoveryScenario | None = None


@dataclass(frozen=True, slots=True)
class CaseReport:
    """A case identifier paired with its content-free interaction report."""

    case_id: str
    interaction: EvaluationReport

    def as_record(self) -> dict[str, object]:
        """Return a machine-readable content-free case record."""
        return {"case_id": self.case_id, **self.interaction.as_record()}


@dataclass(frozen=True, slots=True)
class SuiteReport:
    """Aggregate outcome and latency data for an ordered evaluation suite."""

    cases: tuple[CaseReport, ...]
    completed: int
    cancelled: int
    failed: int
    transcript: Percentiles
    first_text: Percentiles
    first_audio: Percentiles
    total: Percentiles
    accuracy: AccuracySummary | None
    recovery: RecoverySummary | None
    cost: CostSummary

    def as_record(self) -> dict[str, object]:
        """Return the documented machine-readable suite report."""
        total_cases = len(self.cases)
        completed_percent = (
            (self.completed / total_cases) * 100.0 if total_cases else 0.0
        )
        return {
            "schema_version": 1,
            "total_cases": total_cases,
            "outcomes": {
                "completed": self.completed,
                "cancelled": self.cancelled,
                "failed": self.failed,
            },
            "completed_percent": completed_percent,
            "latency_ms": {
                "transcript": self.transcript.as_record(),
                "first_text": self.first_text.as_record(),
                "first_audio": self.first_audio.as_record(),
                "total": self.total.as_record(),
            },
            "accuracy": self.accuracy.as_record() if self.accuracy else None,
            "recovery": self.recovery.as_record() if self.recovery else None,
            "cost": self.cost.as_record(),
            "cases": [case.as_record() for case in self.cases],
        }


class EvaluationSuite:
    """Run cases in stable order and aggregate privacy-safe measurements."""

    def __init__(
        self,
        evaluator: InteractionEvaluator | AnnotatedInteractionEvaluator,
    ) -> None:
        self._evaluator = evaluator

    async def run(self, cases: Sequence[EvaluationCase]) -> SuiteReport:
        """Run all cases sequentially and calculate nearest-rank percentiles."""
        case_ids = [case.case_id for case in cases]
        if len(case_ids) != len(set(case_ids)):
            message = "evaluation case id must be unique"
            raise EvaluationSuiteError(message)

        reports: list[CaseReport] = []
        completed = 0
        cancelled = 0
        failed = 0

        for case in cases:
            interaction = await self._evaluate(case)
            _validate_correlation(case, interaction)
            reports.append(CaseReport(case.case_id, interaction))
            if interaction.outcome is EvaluationOutcome.COMPLETED:
                completed += 1
            elif interaction.outcome is EvaluationOutcome.CANCELLED:
                cancelled += 1
            else:
                failed += 1

        return SuiteReport(
            cases=tuple(reports),
            completed=completed,
            cancelled=cancelled,
            failed=failed,
            transcript=percentiles(
                report.interaction.transcript_ms for report in reports
            ),
            first_text=percentiles(
                report.interaction.first_text_ms for report in reports
            ),
            first_audio=percentiles(
                report.interaction.first_audio_ms for report in reports
            ),
            total=percentiles(report.interaction.total_ms for report in reports),
            accuracy=accuracy_summary([report.interaction for report in reports]),
            recovery=recovery_summary([report.interaction for report in reports]),
            cost=cost_summary([report.interaction for report in reports]),
        )

    async def _evaluate(self, case: EvaluationCase) -> EvaluationReport:
        if case.accuracy is None and case.recovery_scenario is None:
            return await self._evaluator.run(case.audio, case.context)
        evaluator = cast("AnnotatedInteractionEvaluator", self._evaluator)
        return await evaluator.run(
            case.audio,
            case.context,
            accuracy=case.accuracy,
            recovery_scenario=case.recovery_scenario,
        )


def _validate_correlation(
    case: EvaluationCase,
    interaction: EvaluationReport,
) -> None:
    if interaction.request_id != case.context.request_id:
        message = "evaluation report request does not match its case"
        raise EvaluationSuiteError(message)
    if (case.accuracy is None) != (interaction.accuracy is None):
        message = "evaluation report accuracy does not match its case"
        raise EvaluationSuiteError(message)
    if case.recovery_scenario is None:
        if interaction.recovery is not None:
            message = "evaluation report recovery does not match its case"
            raise EvaluationSuiteError(message)
    elif (
        interaction.recovery is None
        or interaction.recovery.scenario is not case.recovery_scenario
    ):
        message = "evaluation report recovery does not match its case"
        raise EvaluationSuiteError(message)
