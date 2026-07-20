from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import pytest
from omnivox_evaluation import (
    AccuracyMeasurement,
    AccuracyReference,
    EvaluationMeasurementError,
    EvaluationOutcome,
    EvaluationRunner,
    RecoveryMeasurement,
    RecoveryObservation,
    RecoveryScenario,
)
from omnivox_gateway.providers import ProviderError
from omnivox_protocol import (
    AudioChunk,
    AudioInput,
    Cancelled,
    Completed,
    PipelineEvent,
    RequestContext,
    ResponseText,
    SpokenAudio,
    TextSegment,
    Transcript,
    TranscriptReady,
)

EXPECTED_DELETION_ERRORS = 2
MEASURED_COST_MICROUSD = 240
MAX_ACCURACY_WORDS = 2_048


@dataclass
class ManualClock:
    current: float = 100.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@dataclass(frozen=True)
class TimedEvent:
    after_seconds: float
    event: PipelineEvent | ProviderError


@dataclass
class ScriptedPipeline:
    clock: ManualClock
    events: tuple[TimedEvent, ...]

    async def execute(
        self, audio: AudioInput, context: RequestContext
    ) -> AsyncIterator[PipelineEvent]:
        del audio, context
        for timed_event in self.events:
            self.clock.advance(timed_event.after_seconds)
            if isinstance(timed_event.event, ProviderError):
                raise timed_event.event
            yield timed_event.event


@pytest.mark.asyncio
async def test_completed_report_has_deterministic_privacy_safe_metrics() -> None:
    clock = ManualClock()
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    transcript = Transcript(text="private transcript", confidence=0.95)
    events = (
        TimedEvent(
            0.100,
            TranscriptReady(context=context, transcript=transcript, provider="stt-a"),
        ),
        TimedEvent(
            0.150,
            ResponseText(
                context=context,
                segment=TextSegment(sequence=0, text="private response"),
                provider="openclaw",
            ),
        ),
        TimedEvent(
            0.050,
            SpokenAudio(
                context=context,
                chunk=AudioChunk(
                    request_id=context.request_id,
                    sequence=0,
                    data=b"private audio",
                ),
                provider="tts-a",
            ),
        ),
        TimedEvent(0.200, Completed(context=context)),
    )
    runner = EvaluationRunner(ScriptedPipeline(clock, events), clock=clock)

    report = await runner.run(AudioInput(codec="opus", data=b"private input"), context)

    assert report.outcome is EvaluationOutcome.COMPLETED
    assert report.as_record() == {
        "request_id": "request-1",
        "outcome": "completed",
        "transcript_ms": pytest.approx(100.0),
        "first_text_ms": pytest.approx(250.0),
        "first_audio_ms": pytest.approx(300.0),
        "total_ms": pytest.approx(500.0),
        "stt_provider": "stt-a",
        "omni_provider": "openclaw",
        "tts_provider": "tts-a",
        "error_code": None,
        "accuracy": None,
        "recovery": None,
        "cost_microusd": None,
    }
    serialized = repr(report.as_record())
    assert "private transcript" not in serialized
    assert "private response" not in serialized
    assert "private audio" not in serialized
    assert "private input" not in serialized


@pytest.mark.asyncio
async def test_provider_failure_records_code_but_not_message() -> None:
    clock = ManualClock()
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    error = ProviderError(
        code="STT_UNAVAILABLE",
        message="sensitive provider detail",
        retryable=False,
    )
    runner = EvaluationRunner(
        ScriptedPipeline(clock, (TimedEvent(0.200, error),)),
        clock=clock,
    )

    report = await runner.run(AudioInput(codec="opus", data=b"audio"), context)

    assert report.outcome is EvaluationOutcome.FAILED
    assert report.error_code == "STT_UNAVAILABLE"
    assert report.total_ms == pytest.approx(200.0)
    assert "sensitive provider detail" not in repr(report.as_record())


@pytest.mark.asyncio
async def test_cancelled_report_is_terminal() -> None:
    clock = ManualClock()
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    runner = EvaluationRunner(
        ScriptedPipeline(
            clock,
            (TimedEvent(0.050, Cancelled(context=context)),),
        ),
        clock=clock,
    )

    report = await runner.run(AudioInput(codec="opus", data=b"audio"), context)

    assert report.outcome is EvaluationOutcome.CANCELLED
    assert report.total_ms == pytest.approx(50.0)
    assert report.error_code is None


@pytest.mark.asyncio
async def test_accuracy_is_reduced_to_content_free_counts() -> None:
    clock = ManualClock()
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    private_hypothesis = "Ask Omni weather"
    events = (
        TimedEvent(
            0.100,
            TranscriptReady(
                context=context,
                transcript=Transcript(text=private_hypothesis),
                provider="stt-a",
            ),
        ),
        TimedEvent(0.100, Completed(context=context)),
    )
    runner = EvaluationRunner(ScriptedPipeline(clock, events), clock=clock)

    report = await runner.run(
        AudioInput(codec="opus", data=b"private input"),
        context,
        accuracy=AccuracyReference(
            reference_transcript="Ask Omni for the weather",
            proper_nouns=("Omni",),
        ),
    )

    assert report.accuracy is not None
    assert report.accuracy.as_record() == {
        "word_errors": 2,
        "reference_words": 5,
        "word_error_rate_percent": 40.0,
        "proper_nouns_correct": 1,
        "proper_nouns_total": 1,
        "proper_noun_accuracy_percent": 100.0,
    }
    serialized = repr(report.as_record())
    assert "Ask Omni for the weather" not in serialized
    assert private_hypothesis not in serialized


@pytest.mark.asyncio
async def test_missing_transcript_counts_as_deletions_for_accuracy() -> None:
    clock = ManualClock()
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    error = ProviderError(code="STT_TIMEOUT", message="private", retryable=False)
    runner = EvaluationRunner(
        ScriptedPipeline(clock, (TimedEvent(0.100, error),)),
        clock=clock,
    )

    report = await runner.run(
        AudioInput(codec="opus", data=b"audio"),
        context,
        accuracy=AccuracyReference(
            reference_transcript="Hello Omni",
            proper_nouns=("Omni",),
        ),
    )

    assert report.accuracy is not None
    assert report.accuracy.word_errors == EXPECTED_DELETION_ERRORS
    assert report.accuracy.proper_nouns_correct == 0


@pytest.mark.asyncio
async def test_recovery_and_cost_use_request_scoped_instrumentation() -> None:
    clock = ManualClock()
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    runner = EvaluationRunner(
        ScriptedPipeline(
            clock,
            (TimedEvent(0.200, Completed(context=context)),),
        ),
        clock=clock,
        recovery_meter=lambda request_id: RecoveryObservation(
            recovered=request_id == context.request_id,
            recovery_ms=125.0,
        ),
        cost_meter=lambda request_id: (
            MEASURED_COST_MICROUSD if request_id == context.request_id else None
        ),
    )

    report = await runner.run(
        AudioInput(codec="opus", data=b"audio"),
        context,
        recovery_scenario=RecoveryScenario.PACKET_LOSS,
    )

    assert report.recovery is not None
    assert report.recovery.as_record() == {
        "scenario": "packet_loss",
        "recovered": True,
        "recovery_ms": 125.0,
    }
    assert report.cost_microusd == MEASURED_COST_MICROUSD


@pytest.mark.asyncio
async def test_declared_recovery_requires_an_observation() -> None:
    clock = ManualClock()
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    runner = EvaluationRunner(
        ScriptedPipeline(
            clock,
            (TimedEvent(0.100, Completed(context=context)),),
        ),
        clock=clock,
    )

    with pytest.raises(EvaluationMeasurementError, match="recovery observation"):
        await runner.run(
            AudioInput(codec="opus", data=b"audio"),
            context,
            recovery_scenario=RecoveryScenario.GATEWAY_RESTART,
        )


@pytest.mark.parametrize(
    ("observation", "message"),
    [
        (lambda: RecoveryObservation(recovered=True, recovery_ms=None), "duration"),
        (
            lambda: RecoveryObservation(recovered=True, recovery_ms=float("inf")),
            "duration",
        ),
        (
            lambda: RecoveryObservation(recovered=False, recovery_ms=1.0),
            "duration",
        ),
    ],
)
def test_recovery_observation_rejects_misleading_duration(
    observation: Callable[[], RecoveryObservation],
    message: str,
) -> None:
    with pytest.raises(EvaluationMeasurementError, match=message):
        observation()


@pytest.mark.asyncio
async def test_cost_rejects_negative_or_non_integer_values() -> None:
    clock = ManualClock()
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    runner = EvaluationRunner(
        ScriptedPipeline(
            clock,
            (TimedEvent(0.100, Completed(context=context)),),
        ),
        clock=clock,
        cost_meter=lambda _request_id: -1,
    )

    with pytest.raises(EvaluationMeasurementError, match="cost"):
        await runner.run(AudioInput(codec="opus", data=b"audio"), context)


@pytest.mark.asyncio
async def test_runner_rejects_pipeline_event_for_another_request() -> None:
    clock = ManualClock()
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    other_context = RequestContext(
        conversation_id="conversation-2",
        request_id="request-2",
    )
    runner = EvaluationRunner(
        ScriptedPipeline(
            clock,
            (TimedEvent(0.100, Completed(context=other_context)),),
        ),
        clock=clock,
    )

    with pytest.raises(EvaluationMeasurementError, match="pipeline event"):
        await runner.run(AudioInput(codec="opus", data=b"audio"), context)


@pytest.mark.asyncio
async def test_accuracy_rejects_an_over_limit_hypothesis() -> None:
    clock = ManualClock()
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    oversized_hypothesis = "word " * (MAX_ACCURACY_WORDS + 1)
    runner = EvaluationRunner(
        ScriptedPipeline(
            clock,
            (
                TimedEvent(
                    0.100,
                    TranscriptReady(
                        context=context,
                        transcript=Transcript(text=oversized_hypothesis),
                        provider="stt-a",
                    ),
                ),
                TimedEvent(0.100, Completed(context=context)),
            ),
        ),
        clock=clock,
    )

    with pytest.raises(EvaluationMeasurementError, match="hypothesis"):
        await runner.run(
            AudioInput(codec="opus", data=b"audio"),
            context,
            accuracy=AccuracyReference("hello"),
        )


@pytest.mark.parametrize(
    "measurement",
    [
        lambda: AccuracyMeasurement(-1, 1, 0, 0),
        lambda: AccuracyMeasurement(0, 0, 0, 0),
        lambda: AccuracyMeasurement(0, 1, 2, 1),
        lambda: RecoveryMeasurement(
            scenario=RecoveryScenario.PACKET_LOSS,
            recovered=True,
            recovery_ms=None,
        ),
    ],
)
def test_content_free_measurements_reject_invalid_values(
    measurement: Callable[[], object],
) -> None:
    with pytest.raises(EvaluationMeasurementError):
        measurement()
