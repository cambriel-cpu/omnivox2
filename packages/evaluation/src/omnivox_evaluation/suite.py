"""Privacy-safe aggregation for repeatable evaluation suites."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Protocol

from omnivox_protocol import AudioInput, RequestContext

from omnivox_evaluation.runner import EvaluationOutcome, EvaluationReport


class EvaluationSuiteError(ValueError):
    """The suite definition or evaluator correlation is invalid."""


class InteractionEvaluator(Protocol):
    """Run one evaluation interaction."""

    async def run(self, audio: AudioInput, context: RequestContext) -> EvaluationReport:
        """Return content-free results for one interaction."""
        ...


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """One private input paired with a non-sensitive case identifier."""

    case_id: str
    audio: AudioInput
    context: RequestContext


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

    def as_record(self) -> dict[str, object]:
        """Return the documented machine-readable suite report."""
        total_cases = len(self.cases)
        completed_percent = (
            (self.completed / total_cases) * 100.0 if total_cases else 0.0
        )
        return {
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
            interaction = await self._evaluator.run(case.audio, case.context)
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
