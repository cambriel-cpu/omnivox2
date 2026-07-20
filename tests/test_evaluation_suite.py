from dataclasses import dataclass, field

import pytest
from omnivox_evaluation import (
    EvaluationCase,
    EvaluationOutcome,
    EvaluationReport,
    EvaluationSuite,
    EvaluationSuiteError,
)
from omnivox_protocol import AudioInput, RequestContext

CASE_COUNT = 4


@dataclass
class StubEvaluator:
    reports: dict[str, EvaluationReport]
    seen_audio: list[bytes] = field(default_factory=list)

    async def run(self, audio: AudioInput, context: RequestContext) -> EvaluationReport:
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
        "total_cases": 0,
        "outcomes": {"completed": 0, "cancelled": 0, "failed": 0},
        "completed_percent": 0.0,
        "latency_ms": {
            "transcript": {"p50": None, "p95": None},
            "first_text": {"p50": None, "p95": None},
            "first_audio": {"p50": None, "p95": None},
            "total": {"p50": None, "p95": None},
        },
        "cases": [],
    }


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
