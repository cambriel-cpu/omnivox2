"""Provider-neutral streaming voice pipeline."""

from collections.abc import AsyncIterator
from dataclasses import dataclass

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

from omnivox_gateway.providers import (
    OmniSession,
    ProviderError,
    SpeechToText,
    TextToSpeech,
)


@dataclass(frozen=True, slots=True)
class ProviderBinding[ProviderT_co]:
    """A provider adapter paired with its non-secret diagnostic name."""

    name: str
    provider: ProviderT_co


@dataclass(slots=True)
class _RequestState:
    cancelled: bool = False


class VoicePipeline:
    """Coordinate one utterance without owning identity or durable state."""

    def __init__(
        self,
        *,
        stt: ProviderBinding[SpeechToText],
        omni: ProviderBinding[OmniSession],
        tts: ProviderBinding[TextToSpeech],
        stt_fallback: ProviderBinding[SpeechToText] | None = None,
    ) -> None:
        self._stt = stt
        self._stt_fallback = stt_fallback
        self._omni = omni
        self._tts = tts
        self._active_requests: dict[str, _RequestState] = {}

    async def cancel(self, request_id: str) -> None:
        """Cancel an active request and forward cancellation exactly once."""
        state = self._active_requests.get(request_id)
        if state is None or state.cancelled:
            return
        state.cancelled = True
        await self._omni.provider.cancel(request_id)

    async def execute(
        self, audio: AudioInput, context: RequestContext
    ) -> AsyncIterator[PipelineEvent]:
        """Stream correlated stage results for one request."""
        state = _RequestState()
        self._active_requests[context.request_id] = state
        try:
            async for event in self._execute_active(audio, context, state):
                yield event
        finally:
            active_state = self._active_requests.get(context.request_id)
            if active_state is state:
                del self._active_requests[context.request_id]

    async def _execute_active(
        self,
        audio: AudioInput,
        context: RequestContext,
        state: _RequestState,
    ) -> AsyncIterator[PipelineEvent]:
        transcript, stt_name = await self._transcribe(audio, context)
        if state.cancelled:
            yield Cancelled(context=context)
            return
        yield TranscriptReady(context=context, transcript=transcript, provider=stt_name)

        observed_segments: list[TextSegment] = []
        emitted_segment_count = 0

        async def response_text() -> AsyncIterator[TextSegment]:
            async for segment in self._omni.provider.respond(transcript.text, context):
                if state.cancelled:
                    return
                observed_segments.append(segment)
                yield segment

        expected_audio_sequence = 0
        async for chunk in self._tts.provider.synthesize(response_text(), context):
            if state.cancelled:
                yield Cancelled(context=context)
                return
            while emitted_segment_count < len(observed_segments):
                segment = observed_segments[emitted_segment_count]
                yield ResponseText(
                    context=context,
                    segment=segment,
                    provider=self._omni.name,
                )
                emitted_segment_count += 1

            self._validate_audio_chunk(chunk, context, expected_audio_sequence)
            yield SpokenAudio(context=context, chunk=chunk, provider=self._tts.name)
            expected_audio_sequence += 1

        if state.cancelled:
            yield Cancelled(context=context)
            return

        while emitted_segment_count < len(observed_segments):
            segment = observed_segments[emitted_segment_count]
            yield ResponseText(
                context=context,
                segment=segment,
                provider=self._omni.name,
            )
            emitted_segment_count += 1

        yield Completed(context=context)

    async def _transcribe(
        self, audio: AudioInput, context: RequestContext
    ) -> tuple[Transcript, str]:
        try:
            transcript = await self._stt.provider.transcribe(audio, context)
        except ProviderError as error:
            if not error.retryable or self._stt_fallback is None:
                raise
            transcript = await self._stt_fallback.provider.transcribe(audio, context)
            return transcript, self._stt_fallback.name
        return transcript, self._stt.name

    @staticmethod
    def _validate_audio_chunk(
        chunk: AudioChunk, context: RequestContext, expected_sequence: int
    ) -> None:
        if (
            chunk.request_id != context.request_id
            or chunk.sequence != expected_sequence
        ):
            message = "stale audio returned by text-to-speech provider"
            raise ProviderError(
                code="STALE_PROVIDER_OUTPUT",
                message=message,
                retryable=False,
            )
