from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from omnivox_gateway.pipeline import ProviderBinding, VoicePipeline
from omnivox_gateway.providers import ProviderError
from omnivox_protocol import (
    AudioChunk,
    AudioInput,
    Completed,
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

    async def respond(
        self, transcript: str, context: RequestContext
    ) -> AsyncIterator[TextSegment]:
        self.calls.append((transcript, context))
        for segment in self.segments:
            yield segment

    async def cancel(self, request_id: str) -> None:
        del request_id


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
