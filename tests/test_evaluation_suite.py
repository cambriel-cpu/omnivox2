from dataclasses import dataclass, field

import pytest
from omnivox_evaluation import (
    AccuracyMeasurement,
    AccuracyReference,
    EvaluationCase,
    EvaluationOutcome,
    EvaluationReport,
    EvaluationSuite,
    EvaluationSuiteError,
    RecoveryMeasurement,
    RecoveryScenario,
)
from omnivox_protocol import AudioInput, RequestContext

CASE_COUNT = 4
ROUNDED_COST_PER_100_MICROUSD = 13


@dataclass
class StubEvaluator:
    reports: dict[str, EvaluationReport]
    seen_audio: list[bytes] = field(default_factory=list)

    async def run(
        self,
        audio: AudioInput,
        context: RequestContext,
        *,
        accuracy: AccuracyReference | None = None,
        recovery_scenario: RecoveryScenario | None = None,
    ) -> EvaluationReport:
        del accuracy, recovery_scenario
        self.seen_audio.append(audio.data)
        return self.reports[context.request_id]


def report(  # noqa: PLR0913
    request_id: str,
    outcome: EvaluationOutcome,
    *,
    transcript_ms: float | None,
    first_text_ms: float | None,
    first_audio_ms: float | None,
    total_ms: float,
    error_code: str | None = None,
    accuracy: AccuracyMeasurement | None = None,
    recovery: RecoveryMeasurement | None = None,
    cost_microusd: int | None = None,
) -> EvaluationReport:
    return EvaluationReport(
        request_id=request_id,
        outcome=outcome,
        transcript_ms=transcript_ms,
        first_text_ms=first_text_ms,
        first_audio_ms=first_audio_ms,
        total_ms=total_ms,
        stt_provider="stt" if transcript_ms is not None else None,
        omni_provider="openclaw" if first_text_ms is not None else None,
        tts_provider="tts" if first_audio_ms is not None else None,
        error_code=error_code,
        accuracy=accuracy,
        recovery=recovery,
        cost_microusd=cost_microusd,
    )


def evaluation_case(index: int) -> EvaluationCase:
    return EvaluationCase(
        case_id=f"case-{index}",
        audio=AudioInput(codec="opus", data=f"private-audio-{index}".encode()),
        context=RequestContext(
            conversation_id=f"conversation-{index}",
            request_id=f"request-{index}",
        ),
    )


@pytest.mark.asyncio
async def test_suite_aggregates_nearest_rank_percentiles_and_outcomes() -> None:
    reports = {
        "request-1": report(
            "request-1",
            EvaluationOutcome.COMPLETED,
            transcript_ms=100.0,
            first_text_ms=200.0,
            first_audio_ms=300.0,
            total_ms=500.0,
        ),
        "request-2": report(
            "request-2",
            EvaluationOutcome.COMPLETED,
            transcript_ms=200.0,
            first_text_ms=400.0,
            first_audio_ms=600.0,
            total_ms=900.0,
        ),
        "request-3": report(
            "request-3",
            EvaluationOutcome.CANCELLED,
            transcript_ms=None,
            first_text_ms=None,
            first_audio_ms=None,
            total_ms=50.0,
        ),
        "request-4": report(
            "request-4",
            EvaluationOutcome.FAILED,
            transcript_ms=300.0,
            first_text_ms=None,
            first_audio_ms=None,
            total_ms=1000.0,
            error_code="STT_UNAVAILABLE",
        ),
    }
    evaluator = StubEvaluator(reports)
    suite = EvaluationSuite(evaluator)

    result = await suite.run(tuple(evaluation_case(index) for index in range(1, 5)))
    record = result.as_record()

    assert record["total_cases"] == CASE_COUNT
    assert record["outcomes"] == {"completed": 2, "cancelled": 1, "failed": 1}
    assert record["completed_percent"] == pytest.approx(50.0)
    assert record["latency_ms"] == {
        "transcript": {"p50": 200.0, "p95": 300.0},
        "first_text": {"p50": 200.0, "p95": 400.0},
        "first_audio": {"p50": 300.0, "p95": 600.0},
        "total": {"p50": 500.0, "p95": 1000.0},
    }
    case_records = record["cases"]
    assert isinstance(case_records, list)
    assert [case["case_id"] for case in case_records] == [
        "case-1",
        "case-2",
        "case-3",
        "case-4",
    ]
    serialized = repr(record)
    assert "private-audio" not in serialized
    assert evaluator.seen_audio == [
        b"private-audio-1",
        b"private-audio-2",
        b"private-audio-3",
        b"private-audio-4",
    ]


@pytest.mark.asyncio
async def test_empty_suite_has_zero_counts_and_no_percentiles() -> None:
    result = await EvaluationSuite(StubEvaluator({})).run(())

    assert result.as_record() == {
        "schema_version": 1,
        "total_cases": 0,
        "outcomes": {"completed": 0, "cancelled": 0, "failed": 0},
        "completed_percent": 0.0,
        "latency_ms": {
            "transcript": {"p50": None, "p95": None},
            "first_text": {"p50": None, "p95": None},
            "first_audio": {"p50": None, "p95": None},
            "total": {"p50": None, "p95": None},
        },
        "accuracy": None,
        "recovery": None,
        "cost": {
            "measured_cases": 0,
            "observed_microusd": 0,
            "per_100_interactions_microusd": None,
        },
        "cases": [],
    }


@pytest.mark.asyncio
async def test_suite_aggregates_accuracy_recovery_and_complete_cost() -> None:
    reports = {
        "request-1": report(
            "request-1",
            EvaluationOutcome.COMPLETED,
            transcript_ms=100.0,
            first_text_ms=200.0,
            first_audio_ms=300.0,
            total_ms=500.0,
            accuracy=AccuracyMeasurement(
                word_errors=1,
                reference_words=4,
                proper_nouns_correct=1,
                proper_nouns_total=1,
            ),
            recovery=RecoveryMeasurement(
                scenario=RecoveryScenario.PACKET_LOSS,
                recovered=True,
                recovery_ms=125.0,
            ),
            cost_microusd=100,
        ),
        "request-2": report(
            "request-2",
            EvaluationOutcome.FAILED,
            transcript_ms=None,
            first_text_ms=None,
            first_audio_ms=None,
            total_ms=900.0,
            error_code="STT_TIMEOUT",
            accuracy=AccuracyMeasurement(
                word_errors=2,
                reference_words=6,
                proper_nouns_correct=0,
                proper_nouns_total=1,
            ),
            recovery=RecoveryMeasurement(
                scenario=RecoveryScenario.PROVIDER_TIMEOUT,
                recovered=False,
                recovery_ms=None,
            ),
            cost_microusd=201,
        ),
    }

    record = (
        await EvaluationSuite(StubEvaluator(reports)).run(
            (evaluation_case(1), evaluation_case(2))
        )
    ).as_record()

    assert record["schema_version"] == 1
    assert record["accuracy"] == {
        "measured_cases": 2,
        "word_errors": 3,
        "reference_words": 10,
        "word_error_rate_percent": 30.0,
        "proper_nouns_correct": 1,
        "proper_nouns_total": 2,
        "proper_noun_accuracy_percent": 50.0,
    }
    assert record["recovery"] == {
        "measured_cases": 2,
        "recovered_cases": 1,
        "recovered_percent": 50.0,
        "recovery_ms": {"p50": 125.0, "p95": 125.0},
    }
    assert record["cost"] == {
        "measured_cases": 2,
        "observed_microusd": 301,
        "per_100_interactions_microusd": 15050,
    }


@pytest.mark.asyncio
async def test_partial_cost_does_not_claim_a_per_100_estimate() -> None:
    first = report(
        "request-1",
        EvaluationOutcome.COMPLETED,
        transcript_ms=1.0,
        first_text_ms=2.0,
        first_audio_ms=3.0,
        total_ms=4.0,
        cost_microusd=0,
    )
    second = report(
        "request-2",
        EvaluationOutcome.COMPLETED,
        transcript_ms=1.0,
        first_text_ms=2.0,
        first_audio_ms=3.0,
        total_ms=4.0,
    )

    result = await EvaluationSuite(
        StubEvaluator({"request-1": first, "request-2": second})
    ).run((evaluation_case(1), evaluation_case(2)))

    assert result.as_record()["cost"] == {
        "measured_cases": 1,
        "observed_microusd": 0,
        "per_100_interactions_microusd": None,
    }


@pytest.mark.asyncio
async def test_cost_per_100_rounds_half_up_to_integer_microusd() -> None:
    case_count = 8
    reports = {
        f"request-{index}": report(
            f"request-{index}",
            EvaluationOutcome.COMPLETED,
            transcript_ms=1.0,
            first_text_ms=2.0,
            first_audio_ms=3.0,
            total_ms=4.0,
            cost_microusd=1 if index == 1 else 0,
        )
        for index in range(1, case_count + 1)
    }

    result = await EvaluationSuite(StubEvaluator(reports)).run(
        tuple(evaluation_case(index) for index in range(1, case_count + 1))
    )

    assert result.cost.per_100_interactions_microusd == ROUNDED_COST_PER_100_MICROUSD


@pytest.mark.asyncio
async def test_suite_rejects_report_for_a_different_request() -> None:
    wrong_report = report(
        "different-request",
        EvaluationOutcome.COMPLETED,
        transcript_ms=1.0,
        first_text_ms=2.0,
        first_audio_ms=3.0,
        total_ms=4.0,
    )
    suite = EvaluationSuite(StubEvaluator({"request-1": wrong_report}))

    with pytest.raises(EvaluationSuiteError, match="request"):
        await suite.run((evaluation_case(1),))


@pytest.mark.asyncio
async def test_suite_rejects_duplicate_case_ids_before_execution() -> None:
    evaluator = StubEvaluator({})
    first = evaluation_case(1)
    duplicate = EvaluationCase(
        case_id=first.case_id,
        audio=AudioInput(codec="opus", data=b"different private audio"),
        context=RequestContext(
            conversation_id="different-conversation",
            request_id="different-request",
        ),
    )

    with pytest.raises(EvaluationSuiteError, match="case id"):
        await EvaluationSuite(evaluator).run((first, duplicate))

    assert evaluator.seen_audio == []
