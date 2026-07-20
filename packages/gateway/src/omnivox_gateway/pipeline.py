"""Provider-neutral streaming voice pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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

from omnivox_gateway.policy import (
    DEFAULT_PIPELINE_DEADLINES,
    DEFAULT_PIPELINE_LIMITS,
    AsyncioDeadlineRunner,
    DeadlineRunner,
    PipelineDeadlines,
    PipelineLimits,
    PipelineStage,
)
from omnivox_gateway.providers import (
    OmniSession,
    ProviderError,
    SpeechToText,
    TextToSpeech,
)
from omnivox_gateway.text_stream import CachingTextSource


@dataclass(frozen=True, slots=True)
class ProviderBinding[ProviderT_co]:
    """A provider adapter paired with its non-secret diagnostic name."""

    name: str
    provider: ProviderT_co


@dataclass(slots=True)
class _RequestState:
    cancelled: bool = False


@dataclass(slots=True)
class _SynthesisState:
    emitted_segments: int = 0
    next_audio_sequence: int = 0
    cancelled_emitted: bool = False


@dataclass(slots=True)
class _SynthesisRun:
    context: RequestContext
    request_state: _RequestState
    progress: _SynthesisState
    observed_segments: list[TextSegment]


class VoicePipeline:
    """Coordinate one utterance without owning identity or durable state."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        stt: ProviderBinding[SpeechToText],
        omni: ProviderBinding[OmniSession],
        tts: ProviderBinding[TextToSpeech],
        stt_fallback: ProviderBinding[SpeechToText] | None = None,
        tts_fallback: ProviderBinding[TextToSpeech] | None = None,
        deadlines: PipelineDeadlines = DEFAULT_PIPELINE_DEADLINES,
        limits: PipelineLimits = DEFAULT_PIPELINE_LIMITS,
        deadline_runner: DeadlineRunner | None = None,
    ) -> None:
        self._stt = stt
        self._stt_fallback = stt_fallback
        self._omni = omni
        self._tts = tts
        self._tts_fallback = tts_fallback
        self._deadlines = deadlines
        self._limits = limits
        self._deadline_runner = deadline_runner or AsyncioDeadlineRunner()
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
        if len(self._active_requests) >= self._limits.max_active_requests:
            message = "gateway active request limit reached"
            raise ProviderError(
                code="CONCURRENCY_LIMIT",
                message=message,
                retryable=True,
            )
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

        text_source = CachingTextSource(
            self._omni.provider.respond(transcript.text, context),
            deadline_runner=self._deadline_runner,
            deadlines=self._deadlines,
            limits=self._limits,
        )
        synthesis = _SynthesisState()
        synthesis_run = _SynthesisRun(
            context=context,
            request_state=state,
            progress=synthesis,
            observed_segments=text_source.segments,
        )
        try:
            async for event in self._synthesize(
                provider=self._tts,
                text=text_source,
                run=synthesis_run,
            ):
                yield event
        except ProviderError as error:
            if state.cancelled:
                yield Cancelled(context=context)
                return
            if (
                not error.retryable
                or self._tts_fallback is None
                or synthesis.next_audio_sequence > 0
            ):
                raise
            async for event in self._synthesize(
                provider=self._tts_fallback,
                text=text_source.replay(),
                run=synthesis_run,
            ):
                yield event

        if state.cancelled:
            if not synthesis.cancelled_emitted:
                yield Cancelled(context=context)
            return

        while synthesis.emitted_segments < len(text_source.segments):
            segment = text_source.segments[synthesis.emitted_segments]
            yield ResponseText(
                context=context,
                segment=segment,
                provider=self._omni.name,
            )
            synthesis.emitted_segments += 1

        yield Completed(context=context)

    async def _synthesize(
        self,
        *,
        provider: ProviderBinding[TextToSpeech],
        text: AsyncIterator[TextSegment],
        run: _SynthesisRun,
    ) -> AsyncIterator[PipelineEvent]:
        audio_stream = provider.provider.synthesize(text, run.context)
        while True:
            try:
                chunk = await self._deadline_runner.wait(
                    PipelineStage.TTS,
                    lambda: anext(audio_stream),
                    self._deadlines.tts_chunk_seconds,
                )
            except StopAsyncIteration:
                break
            except TimeoutError as error:
                message = "text-to-speech audio chunk deadline exceeded"
                raise ProviderError(
                    code="TTS_TIMEOUT",
                    message=message,
                    retryable=True,
                ) from error

            if run.request_state.cancelled:
                run.progress.cancelled_emitted = True
                yield Cancelled(context=run.context)
                return
            if run.progress.next_audio_sequence >= self._limits.max_audio_chunks:
                message = "text-to-speech response exceeded the audio chunk limit"
                raise ProviderError(
                    code="RESPONSE_LIMIT_EXCEEDED",
                    message=message,
                    retryable=False,
                )
            while run.progress.emitted_segments < len(run.observed_segments):
                segment = run.observed_segments[run.progress.emitted_segments]
                yield ResponseText(
                    context=run.context,
                    segment=segment,
                    provider=self._omni.name,
                )
                run.progress.emitted_segments += 1

            self._validate_audio_chunk(
                chunk,
                run.context,
                run.progress.next_audio_sequence,
            )
            yield SpokenAudio(context=run.context, chunk=chunk, provider=provider.name)
            run.progress.next_audio_sequence += 1

    async def _transcribe(
        self, audio: AudioInput, context: RequestContext
    ) -> tuple[Transcript, str]:
        try:
            transcript = await self._transcribe_once(self._stt, audio, context)
        except ProviderError as error:
            if not error.retryable or self._stt_fallback is None:
                raise
            transcript = await self._transcribe_once(
                self._stt_fallback,
                audio,
                context,
            )
            return transcript, self._stt_fallback.name
        return transcript, self._stt.name

    async def _transcribe_once(
        self,
        binding: ProviderBinding[SpeechToText],
        audio: AudioInput,
        context: RequestContext,
    ) -> Transcript:
        try:
            return await self._deadline_runner.wait(
                PipelineStage.STT,
                lambda: binding.provider.transcribe(audio, context),
                self._deadlines.stt_seconds,
            )
        except TimeoutError as error:
            message = "speech-to-text attempt deadline exceeded"
            raise ProviderError(
                code="STT_TIMEOUT",
                message=message,
                retryable=True,
            ) from error

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
