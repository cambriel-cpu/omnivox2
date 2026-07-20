from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from omnivox_evaluation import EvaluationOutcome, EvaluationRunner
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
