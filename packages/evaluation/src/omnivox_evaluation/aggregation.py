"""Content-free aggregate calculations for evaluation reports."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import ceil

from omnivox_evaluation.metrics import AccuracyMeasurement, RecoveryMeasurement
from omnivox_evaluation.runner import EvaluationReport


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


def percentiles(values: Iterable[float | None]) -> Percentiles:
    """Calculate deterministic nearest-rank percentiles."""
    observations = sorted(value for value in values if value is not None)
    if not observations:
        return Percentiles(p50=None, p95=None)
    return Percentiles(
        p50=_nearest_rank(observations, 0.50),
        p95=_nearest_rank(observations, 0.95),
    )


def accuracy_summary(
    reports: Sequence[EvaluationReport],
) -> AccuracySummary | None:
    """Micro-average all available accuracy measurements."""
    measurements = [report.accuracy for report in reports if report.accuracy]
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


def recovery_summary(
    reports: Sequence[EvaluationReport],
) -> RecoverySummary | None:
    """Aggregate all available recovery measurements."""
    measurements: list[RecoveryMeasurement] = [
        report.recovery for report in reports if report.recovery is not None
    ]
    if not measurements:
        return None
    recovered = [value for value in measurements if value.recovered]
    return RecoverySummary(
        measured_cases=len(measurements),
        recovered_cases=len(recovered),
        recovery_ms=percentiles(value.recovery_ms for value in recovered),
    )


def cost_summary(reports: Sequence[EvaluationReport]) -> CostSummary:
    """Aggregate observed cost without inventing missing measurements."""
    observed = [
        report.cost_microusd for report in reports if report.cost_microusd is not None
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


def _nearest_rank(observations: list[float], percentile: float) -> float:
    rank = ceil(percentile * len(observations))
    return observations[rank - 1]


def _round_fraction_half_up(numerator: int, denominator: int) -> int:
    return ((2 * numerator) + denominator) // (2 * denominator)
