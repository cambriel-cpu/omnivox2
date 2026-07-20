"""Privacy-safe aggregation for repeatable evaluation suites."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Protocol

from omnivox_protocol import AudioInput, RequestContext

from omnivox_evaluation.metrics import (
    AccuracyMeasurement,
    AccuracyReference,
    RecoveryMeasurement,
    RecoveryScenario,
)
from omnivox_evaluation.runner import EvaluationOutcome, EvaluationReport


class EvaluationSuiteError(ValueError):
    """The suite definition or evaluator correlation is invalid."""


class InteractionEvaluator(Protocol):
    """Run one evaluation interaction."""

    async def run(
        self,
        audio: AudioInput,
        context: RequestContext,
        *,
        accuracy: AccuracyReference | None = None,
        recovery_scenario: RecoveryScenario | None = None,
    ) -> EvaluationReport:
        """Return content-free results for one interaction."""
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
class Percentiles:
    """Nearest-rank p50 and p95 observations."""

    p50: float | None
    p95: float | None

    def as_record(self) -> dict[str, float | None]:
        """Return a machine-readable percentile pair."""
        return {"p50": self.p50, "p95": self.p95}


@dataclass(frozen=True, slots=True)
class AccuracySummary:
    """Micro-averaged content-free accuracy measurements."""

    measured_cases: int
    measurement: AccuracyMeasurement

    def as_record(self) -> dict[str, object]:
        """Return aggregate counts and rates."""
        return {
            "measured_cases": self.measured_cases,
            **self.measurement.as_record(),
        }


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    """Aggregate deterministic recovery results."""

    measured_cases: int
    recovered_cases: int
    recovery_ms: Percentiles

    def as_record(self) -> dict[str, object]:
        """Return aggregate recovery success and latency."""
        return {
            "measured_cases": self.measured_cases,
            "recovered_cases": self.recovered_cases,
            "recovered_percent": (self.recovered_cases / self.measured_cases) * 100.0,
            "recovery_ms": self.recovery_ms.as_record(),
        }


@dataclass(frozen=True, slots=True)
class CostSummary:
    """Observed request cost with a completeness-aware normalized estimate."""

    measured_cases: int
    observed_microusd: int
    per_100_interactions_microusd: int | None

    def as_record(self) -> dict[str, int | None]:
        """Return machine-readable integer cost values."""
        return {
            "measured_cases": self.measured_cases,
            "observed_microusd": self.observed_microusd,
            "per_100_interactions_microusd": self.per_100_interactions_microusd,
        }


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

    def __init__(self, evaluator: InteractionEvaluator) -> None:
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
            interaction = await self._evaluator.run(
                case.audio,
                case.context,
                accuracy=case.accuracy,
                recovery_scenario=case.recovery_scenario,
            )
            if interaction.request_id != case.context.request_id:
                message = "evaluation report request does not match its case"
                raise EvaluationSuiteError(message)
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
            transcript=_percentiles(
                report.interaction.transcript_ms for report in reports
            ),
            first_text=_percentiles(
                report.interaction.first_text_ms for report in reports
            ),
            first_audio=_percentiles(
                report.interaction.first_audio_ms for report in reports
            ),
            total=_percentiles(report.interaction.total_ms for report in reports),
            accuracy=_accuracy_summary(reports),
            recovery=_recovery_summary(reports),
            cost=_cost_summary(reports),
        )


def _percentiles(values: Iterable[float | None]) -> Percentiles:
    observations = sorted(value for value in values if value is not None)
    if not observations:
        return Percentiles(p50=None, p95=None)
    return Percentiles(
        p50=_nearest_rank(observations, 0.50),
        p95=_nearest_rank(observations, 0.95),
    )


def _nearest_rank(observations: list[float], percentile: float) -> float:
    rank = ceil(percentile * len(observations))
    return observations[rank - 1]


def _accuracy_summary(reports: list[CaseReport]) -> AccuracySummary | None:
    measurements = [
        report.interaction.accuracy
        for report in reports
        if report.interaction.accuracy is not None
    ]
    if not measurements:
        return None
    return AccuracySummary(
        measured_cases=len(measurements),
        measurement=AccuracyMeasurement(
            word_errors=sum(value.word_errors for value in measurements),
            reference_words=sum(value.reference_words for value in measurements),
            proper_nouns_correct=sum(
                value.proper_nouns_correct for value in measurements
            ),
            proper_nouns_total=sum(value.proper_nouns_total for value in measurements),
        ),
    )


def _recovery_summary(reports: list[CaseReport]) -> RecoverySummary | None:
    measurements: list[RecoveryMeasurement] = [
        report.interaction.recovery
        for report in reports
        if report.interaction.recovery is not None
    ]
    if not measurements:
        return None
    recovered = [value for value in measurements if value.recovered]
    return RecoverySummary(
        measured_cases=len(measurements),
        recovered_cases=len(recovered),
        recovery_ms=_percentiles(value.recovery_ms for value in recovered),
    )


def _cost_summary(reports: list[CaseReport]) -> CostSummary:
    observed = [
        report.interaction.cost_microusd
        for report in reports
        if report.interaction.cost_microusd is not None
    ]
    total = sum(observed)
    complete = bool(reports) and len(observed) == len(reports)
    normalized = (
        _round_fraction_half_up(total * 100, len(reports)) if complete else None
    )
    return CostSummary(
        measured_cases=len(observed),
        observed_microusd=total,
        per_100_interactions_microusd=normalized,
    )


def _round_fraction_half_up(numerator: int, denominator: int) -> int:
    return ((2 * numerator) + denominator) // (2 * denominator)
