import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import pytest
from omnivox_gateway.pipeline import ProviderBinding, VoicePipeline
from omnivox_gateway.policy import PipelineLimits, PipelineStage
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
class StubSpeechToText:
    result: Transcript | ProviderError
    calls: list[tuple[AudioInput, RequestContext]] = field(default_factory=list)

    async def transcribe(
        self, audio: AudioInput, context: RequestContext
    ) -> Transcript:
        self.calls.append((audio, context))
        if isinstance(self.result, ProviderError):
            raise self.result
        return self.result


@dataclass
class StubOmniSession:
    segments: tuple[TextSegment, ...]
    calls: list[tuple[str, RequestContext]] = field(default_factory=list)
    cancel_calls: list[str] = field(default_factory=list)

    async def respond(
        self, transcript: str, context: RequestContext
    ) -> AsyncIterator[TextSegment]:
        self.calls.append((transcript, context))
        for segment in self.segments:
            yield segment

    async def cancel(self, request_id: str) -> None:
        self.cancel_calls.append(request_id)


@dataclass
class StubTextToSpeech:
    chunks: tuple[AudioChunk, ...]
    received_text: list[TextSegment] = field(default_factory=list)

    async def synthesize(
        self, text: AsyncIterator[TextSegment], context: RequestContext
    ) -> AsyncIterator[AudioChunk]:
        del context
        async for segment in text:
            self.received_text.append(segment)
            yield self.chunks[len(self.received_text) - 1]


@dataclass
class BlockingTextToSpeech:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def synthesize(
        self, text: AsyncIterator[TextSegment], context: RequestContext
    ) -> AsyncIterator[AudioChunk]:
        async for segment in text:
            del segment
            self.entered.set()
            await self.release.wait()
            yield AudioChunk(
                request_id=context.request_id,
                sequence=0,
                data=b"late audio",
            )


@dataclass
class FailingTextToSpeech:
    error: ProviderError
    chunks_before_failure: tuple[AudioChunk, ...] = ()
    received_text: list[TextSegment] = field(default_factory=list)
    calls: int = 0

    async def synthesize(
        self, text: AsyncIterator[TextSegment], context: RequestContext
    ) -> AsyncIterator[AudioChunk]:
        del context
        self.calls += 1
        async for segment in text:
            self.received_text.append(segment)
            chunk_index = len(self.received_text) - 1
            if chunk_index < len(self.chunks_before_failure):
                yield self.chunks_before_failure[chunk_index]
        raise self.error


@dataclass
class BlockingFailingTextToSpeech:
    error: ProviderError
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def synthesize(
        self, text: AsyncIterator[TextSegment], context: RequestContext
    ) -> AsyncIterator[AudioChunk]:
        del context
        async for segment in text:
            del segment
            self.entered.set()
            await self.release.wait()
            raise self.error
        if False:
            yield  # pragma: no cover


@dataclass
class DeterministicDeadlineRunner:
    timeouts: list[PipelineStage]
    calls: list[PipelineStage] = field(default_factory=list)

    async def wait[ResultT](
        self,
        stage: PipelineStage,
        operation: Callable[[], Awaitable[ResultT]],
        timeout_seconds: float,
    ) -> ResultT:
        del timeout_seconds
        self.calls.append(stage)
        if self.timeouts and self.timeouts[0] is stage:
            self.timeouts.pop(0)
            raise TimeoutError
        return await operation()


def binding[ProviderT](name: str, provider: ProviderT) -> ProviderBinding[ProviderT]:
    return ProviderBinding(name=name, provider=provider)


@pytest.mark.asyncio
async def test_pipeline_streams_correlated_events_in_order() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    audio = AudioInput(codec="opus", data=b"encoded speech")
    transcript = Transcript(text="What time is it?", confidence=0.98)
    segments = (
        TextSegment(sequence=0, text="It is "),
        TextSegment(sequence=1, text="three o'clock."),
    )
    chunks = (
        AudioChunk(request_id=context.request_id, sequence=0, data=b"first"),
        AudioChunk(request_id=context.request_id, sequence=1, data=b"second"),
    )
    stt = StubSpeechToText(transcript)
    omni = StubOmniSession(segments)
    tts = StubTextToSpeech(chunks)
    pipeline = VoicePipeline(
        stt=binding("primary-stt", stt),
        omni=binding("openclaw", omni),
        tts=binding("primary-tts", tts),
    )

    events = [event async for event in pipeline.execute(audio, context)]

    assert events == [
        TranscriptReady(context=context, transcript=transcript, provider="primary-stt"),
        ResponseText(context=context, segment=segments[0], provider="openclaw"),
        SpokenAudio(context=context, chunk=chunks[0], provider="primary-tts"),
        ResponseText(context=context, segment=segments[1], provider="openclaw"),
        SpokenAudio(context=context, chunk=chunks[1], provider="primary-tts"),
        Completed(context=context),
    ]
    assert stt.calls == [(audio, context)]
    assert omni.calls == [(transcript.text, context)]
    assert tts.received_text == list(segments)


@pytest.mark.asyncio
async def test_retryable_stt_failure_uses_one_fallback() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    primary = StubSpeechToText(
        ProviderError(
            code="STT_UNAVAILABLE", message="primary unavailable", retryable=True
        )
    )
    fallback_transcript = Transcript(text="Fallback worked", confidence=0.8)
    fallback = StubSpeechToText(fallback_transcript)
    pipeline = VoicePipeline(
        stt=binding("primary-stt", primary),
        stt_fallback=binding("fallback-stt", fallback),
        omni=binding("openclaw", StubOmniSession(())),
        tts=binding("primary-tts", StubTextToSpeech(())),
    )

    events = [
        event
        async for event in pipeline.execute(
            AudioInput(codec="opus", data=b"audio"), context
        )
    ]

    assert events[0] == TranscriptReady(
        context=context,
        transcript=fallback_transcript,
        provider="fallback-stt",
    )
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


@pytest.mark.asyncio
async def test_non_retryable_stt_failure_does_not_use_fallback() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    error = ProviderError(
        code="INVALID_AUDIO", message="unsupported input", retryable=False
    )
    fallback = StubSpeechToText(Transcript(text="not used", confidence=1.0))
    pipeline = VoicePipeline(
        stt=binding("primary-stt", StubSpeechToText(error)),
        stt_fallback=binding("fallback-stt", fallback),
        omni=binding("openclaw", StubOmniSession(())),
        tts=binding("primary-tts", StubTextToSpeech(())),
    )

    with pytest.raises(ProviderError) as raised:
        _ = [
            event
            async for event in pipeline.execute(
                AudioInput(codec="opus", data=b"bad audio"), context
            )
        ]

    assert raised.value is error
    assert fallback.calls == []


@pytest.mark.asyncio
async def test_pipeline_rejects_audio_for_another_request() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    pipeline = VoicePipeline(
        stt=binding(
            "primary-stt",
            StubSpeechToText(Transcript(text="hello", confidence=1.0)),
        ),
        omni=binding(
            "openclaw", StubOmniSession((TextSegment(sequence=0, text="Hello."),))
        ),
        tts=binding(
            "primary-tts",
            StubTextToSpeech(
                (AudioChunk(request_id="old-request", sequence=0, data=b"stale"),)
            ),
        ),
    )

    with pytest.raises(ProviderError, match="stale audio") as raised:
        _ = [
            event
            async for event in pipeline.execute(
                AudioInput(codec="opus", data=b"audio"), context
            )
        ]

    assert raised.value.code == "STALE_PROVIDER_OUTPUT"
    assert raised.value.retryable is False


@pytest.mark.asyncio
async def test_cancellation_is_idempotent_and_discards_late_audio() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    transcript = Transcript(text="hello", confidence=1.0)
    omni = StubOmniSession((TextSegment(sequence=0, text="Hello."),))
    tts = BlockingTextToSpeech()
    pipeline = VoicePipeline(
        stt=binding("primary-stt", StubSpeechToText(transcript)),
        omni=binding("openclaw", omni),
        tts=binding("primary-tts", tts),
    )

    async def collect_events() -> list[PipelineEvent]:
        return [
            event
            async for event in pipeline.execute(
                AudioInput(codec="opus", data=b"audio"), context
            )
        ]

    execution = asyncio.create_task(collect_events())
    await asyncio.wait_for(tts.entered.wait(), timeout=1.0)

    await pipeline.cancel(context.request_id)
    await pipeline.cancel(context.request_id)
    tts.release.set()
    events = await asyncio.wait_for(execution, timeout=1.0)

    assert events == [
        TranscriptReady(context=context, transcript=transcript, provider="primary-stt"),
        Cancelled(context=context),
    ]
    assert omni.cancel_calls == [context.request_id]
    assert not any(isinstance(event, SpokenAudio) for event in events)


@pytest.mark.asyncio
async def test_retryable_tts_failure_replays_text_once_to_fallback() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    transcript = Transcript(text="hello", confidence=1.0)
    segments = (
        TextSegment(sequence=0, text="First."),
        TextSegment(sequence=1, text="Second."),
    )
    error = ProviderError(
        code="TTS_UNAVAILABLE",
        message="primary unavailable",
        retryable=True,
    )
    primary = FailingTextToSpeech(error)
    fallback_chunks = (
        AudioChunk(request_id=context.request_id, sequence=0, data=b"fallback-1"),
        AudioChunk(request_id=context.request_id, sequence=1, data=b"fallback-2"),
    )
    fallback = StubTextToSpeech(fallback_chunks)
    pipeline = VoicePipeline(
        stt=binding("primary-stt", StubSpeechToText(transcript)),
        omni=binding("openclaw", StubOmniSession(segments)),
        tts=binding("primary-tts", primary),
        tts_fallback=binding("fallback-tts", fallback),
    )

    events = [
        event
        async for event in pipeline.execute(
            AudioInput(codec="opus", data=b"audio"), context
        )
    ]

    assert primary.calls == 1
    assert primary.received_text == list(segments)
    assert fallback.received_text == list(segments)
    assert [event.segment for event in events if isinstance(event, ResponseText)] == [
        *segments
    ]
    assert [event.provider for event in events if isinstance(event, SpokenAudio)] == [
        "fallback-tts",
        "fallback-tts",
    ]


@pytest.mark.asyncio
async def test_tts_failure_after_primary_audio_does_not_fallback() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    error = ProviderError(
        code="TTS_UNAVAILABLE",
        message="failed after speech began",
        retryable=True,
    )
    first_chunk = AudioChunk(
        request_id=context.request_id,
        sequence=0,
        data=b"already spoken",
    )
    primary = FailingTextToSpeech(error, chunks_before_failure=(first_chunk,))
    fallback = StubTextToSpeech(
        (AudioChunk(request_id=context.request_id, sequence=0, data=b"duplicate"),)
    )
    pipeline = VoicePipeline(
        stt=binding(
            "primary-stt",
            StubSpeechToText(Transcript(text="hello", confidence=1.0)),
        ),
        omni=binding(
            "openclaw",
            StubOmniSession(
                (
                    TextSegment(sequence=0, text="First."),
                    TextSegment(sequence=1, text="Second."),
                )
            ),
        ),
        tts=binding("primary-tts", primary),
        tts_fallback=binding("fallback-tts", fallback),
    )
    stream = pipeline.execute(AudioInput(codec="opus", data=b"audio"), context)
    transcript_event = await anext(stream)
    text_event = await anext(stream)
    spoken_event = await anext(stream)

    with pytest.raises(ProviderError) as raised:
        await anext(stream)

    assert raised.value is error
    assert fallback.received_text == []
    assert isinstance(transcript_event, TranscriptReady)
    assert isinstance(text_event, ResponseText)
    assert spoken_event == SpokenAudio(
        context=context,
        chunk=first_chunk,
        provider="primary-tts",
    )


@pytest.mark.asyncio
async def test_cancellation_suppresses_pending_tts_fallback() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    primary = BlockingFailingTextToSpeech(
        ProviderError(
            code="TTS_UNAVAILABLE",
            message="primary unavailable",
            retryable=True,
        )
    )
    fallback = StubTextToSpeech(
        (AudioChunk(request_id=context.request_id, sequence=0, data=b"not used"),)
    )
    omni = StubOmniSession((TextSegment(sequence=0, text="Hello."),))
    pipeline = VoicePipeline(
        stt=binding(
            "primary-stt",
            StubSpeechToText(Transcript(text="hello", confidence=1.0)),
        ),
        omni=binding("openclaw", omni),
        tts=binding("primary-tts", primary),
        tts_fallback=binding("fallback-tts", fallback),
    )

    async def collect_events() -> list[PipelineEvent]:
        return [
            event
            async for event in pipeline.execute(
                AudioInput(codec="opus", data=b"audio"), context
            )
        ]

    execution = asyncio.create_task(collect_events())
    await asyncio.wait_for(primary.entered.wait(), timeout=1.0)
    await pipeline.cancel(context.request_id)
    primary.release.set()
    events = await asyncio.wait_for(execution, timeout=1.0)

    assert events[-1] == Cancelled(context=context)
    assert fallback.received_text == []
    assert omni.cancel_calls == [context.request_id]


@pytest.mark.asyncio
async def test_stt_timeout_uses_single_fallback() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    fallback_transcript = Transcript(text="fallback", confidence=0.8)
    fallback = StubSpeechToText(fallback_transcript)
    deadlines = DeterministicDeadlineRunner([PipelineStage.STT])
    pipeline = VoicePipeline(
        stt=binding(
            "primary-stt",
            StubSpeechToText(Transcript(text="not reached", confidence=1.0)),
        ),
        stt_fallback=binding("fallback-stt", fallback),
        omni=binding("openclaw", StubOmniSession(())),
        tts=binding("primary-tts", StubTextToSpeech(())),
        deadline_runner=deadlines,
    )

    events = [
        event
        async for event in pipeline.execute(
            AudioInput(codec="opus", data=b"audio"), context
        )
    ]

    assert events[0] == TranscriptReady(
        context=context,
        transcript=fallback_transcript,
        provider="fallback-stt",
    )
    assert fallback.calls == [(AudioInput(codec="opus", data=b"audio"), context)]
    expected_attempts = 2
    assert deadlines.calls.count(PipelineStage.STT) == expected_attempts


@pytest.mark.asyncio
async def test_openclaw_segment_timeout_is_normalized() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    deadlines = DeterministicDeadlineRunner([PipelineStage.OPENCLAW])
    pipeline = VoicePipeline(
        stt=binding(
            "primary-stt",
            StubSpeechToText(Transcript(text="hello", confidence=1.0)),
        ),
        omni=binding(
            "openclaw", StubOmniSession((TextSegment(sequence=0, text="Hello."),))
        ),
        tts=binding(
            "primary-tts",
            StubTextToSpeech(
                (AudioChunk(request_id=context.request_id, sequence=0, data=b"audio"),)
            ),
        ),
        deadline_runner=deadlines,
    )

    with pytest.raises(ProviderError) as raised:
        _ = [
            event
            async for event in pipeline.execute(
                AudioInput(codec="opus", data=b"audio"), context
            )
        ]

    assert raised.value.code == "OPENCLAW_TIMEOUT"
    assert raised.value.retryable is False


@pytest.mark.asyncio
async def test_tts_timeout_before_audio_uses_fallback() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    segment = TextSegment(sequence=0, text="Hello.")
    fallback = StubTextToSpeech(
        (AudioChunk(request_id=context.request_id, sequence=0, data=b"fallback"),)
    )
    deadlines = DeterministicDeadlineRunner([PipelineStage.TTS])
    pipeline = VoicePipeline(
        stt=binding(
            "primary-stt",
            StubSpeechToText(Transcript(text="hello", confidence=1.0)),
        ),
        omni=binding("openclaw", StubOmniSession((segment,))),
        tts=binding("primary-tts", StubTextToSpeech(())),
        tts_fallback=binding("fallback-tts", fallback),
        deadline_runner=deadlines,
    )

    events = [
        event
        async for event in pipeline.execute(
            AudioInput(codec="opus", data=b"audio"), context
        )
    ]

    assert fallback.received_text == [segment]
    assert [event.provider for event in events if isinstance(event, SpokenAudio)] == [
        "fallback-tts"
    ]


@pytest.mark.asyncio
async def test_response_character_limit_is_non_retryable() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    fallback = StubTextToSpeech(
        (AudioChunk(request_id=context.request_id, sequence=0, data=b"not used"),)
    )
    pipeline = VoicePipeline(
        stt=binding(
            "primary-stt",
            StubSpeechToText(Transcript(text="hello", confidence=1.0)),
        ),
        omni=binding(
            "openclaw", StubOmniSession((TextSegment(sequence=0, text="too long"),))
        ),
        tts=binding("primary-tts", StubTextToSpeech(())),
        tts_fallback=binding("fallback-tts", fallback),
        limits=PipelineLimits(max_response_characters=3),
    )

    with pytest.raises(ProviderError) as raised:
        _ = [
            event
            async for event in pipeline.execute(
                AudioInput(codec="opus", data=b"audio"), context
            )
        ]

    assert raised.value.code == "RESPONSE_LIMIT_EXCEEDED"
    assert raised.value.retryable is False
    assert fallback.received_text == []


@pytest.mark.asyncio
async def test_audio_chunk_limit_stops_request() -> None:
    context = RequestContext(conversation_id="conversation-1", request_id="request-1")
    segments = (
        TextSegment(sequence=0, text="First."),
        TextSegment(sequence=1, text="Second."),
    )
    chunks = (
        AudioChunk(request_id=context.request_id, sequence=0, data=b"first"),
        AudioChunk(request_id=context.request_id, sequence=1, data=b"second"),
    )
    pipeline = VoicePipeline(
        stt=binding(
            "primary-stt",
            StubSpeechToText(Transcript(text="hello", confidence=1.0)),
        ),
        omni=binding("openclaw", StubOmniSession(segments)),
        tts=binding("primary-tts", StubTextToSpeech(chunks)),
        limits=PipelineLimits(max_audio_chunks=1),
    )
    stream = pipeline.execute(AudioInput(codec="opus", data=b"audio"), context)
    await anext(stream)
    await anext(stream)
    first_audio = await anext(stream)

    with pytest.raises(ProviderError) as raised:
        await anext(stream)

    assert isinstance(first_audio, SpokenAudio)
    assert raised.value.code == "RESPONSE_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_active_request_limit_rejects_concurrent_execution() -> None:
    first_context = RequestContext(
        conversation_id="conversation-1",
        request_id="request-1",
    )
    second_context = RequestContext(
        conversation_id="conversation-2",
        request_id="request-2",
    )
    blocking_tts = BlockingTextToSpeech()
    pipeline = VoicePipeline(
        stt=binding(
            "primary-stt",
            StubSpeechToText(Transcript(text="hello", confidence=1.0)),
        ),
        omni=binding(
            "openclaw", StubOmniSession((TextSegment(sequence=0, text="Hello."),))
        ),
        tts=binding("primary-tts", blocking_tts),
        limits=PipelineLimits(max_active_requests=1),
    )

    async def collect_first() -> list[PipelineEvent]:
        return [
            event
            async for event in pipeline.execute(
                AudioInput(codec="opus", data=b"first"), first_context
            )
        ]

    first_execution = asyncio.create_task(collect_first())
    await asyncio.wait_for(blocking_tts.entered.wait(), timeout=1.0)

    with pytest.raises(ProviderError) as raised:
        _ = [
            event
            async for event in pipeline.execute(
                AudioInput(codec="opus", data=b"second"), second_context
            )
        ]

    assert raised.value.code == "CONCURRENCY_LIMIT"
    await pipeline.cancel(first_context.request_id)
    blocking_tts.release.set()
    await asyncio.wait_for(first_execution, timeout=1.0)
