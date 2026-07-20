"""Provider-neutral request and streaming event models."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Identifiers shared across every stage of one utterance."""

    conversation_id: str
    request_id: str


@dataclass(frozen=True, slots=True)
class AudioInput:
    """Bounded encoded utterance presented to a speech recognizer."""

    codec: str
    data: bytes


@dataclass(frozen=True, slots=True)
class Transcript:
    """Confirmed speech-recognition result."""

    text: str
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class TextSegment:
    """One ordered, speakable unit from OpenClaw."""

    sequence: int
    text: str


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """One ordered synthesized-audio unit."""

    request_id: str
    sequence: int
    data: bytes


@dataclass(frozen=True, slots=True)
class TranscriptReady:
    """A confirmed transcript is available."""

    context: RequestContext
    transcript: Transcript
    provider: str


@dataclass(frozen=True, slots=True)
class ResponseText:
    """OpenClaw produced a speakable text segment."""

    context: RequestContext
    segment: TextSegment
    provider: str


@dataclass(frozen=True, slots=True)
class SpokenAudio:
    """A synthesized audio chunk is ready for transport."""

    context: RequestContext
    chunk: AudioChunk
    provider: str


@dataclass(frozen=True, slots=True)
class Completed:
    """The request pipeline completed successfully."""

    context: RequestContext


type PipelineEvent = TranscriptReady | ResponseText | SpokenAudio | Completed
