"""Provider interfaces and normalized provider failures."""

from collections.abc import AsyncIterator
from typing import Protocol

from omnivox_protocol import (
    AudioChunk,
    AudioInput,
    RequestContext,
    TextSegment,
    Transcript,
)


class ProviderError(Exception):
    """A provider-independent failure safe for coordinator policy decisions."""

    code: str
    retryable: bool

    def __init__(self, *, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class SpeechToText(Protocol):
    """Convert one bounded utterance to a confirmed transcript."""

    async def transcribe(
        self, audio: AudioInput, context: RequestContext
    ) -> Transcript:
        """Return a confirmed transcript for one utterance."""
        ...


class OmniSession(Protocol):
    """Stream response text from the OpenClaw-owned session."""

    def respond(
        self, transcript: str, context: RequestContext
    ) -> AsyncIterator[TextSegment]:
        """Yield ordered response text for one request."""
        ...

    async def cancel(self, request_id: str) -> None:
        """Cancel generation for a request idempotently."""
        ...


class TextToSpeech(Protocol):
    """Stream audio for an asynchronous sequence of text segments."""

    def synthesize(
        self, text: AsyncIterator[TextSegment], context: RequestContext
    ) -> AsyncIterator[AudioChunk]:
        """Yield ordered synthesized audio chunks."""
        ...
