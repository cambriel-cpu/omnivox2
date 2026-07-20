"""Deterministic, privacy-safe pipeline evaluation reporting."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Protocol

from omnivox_gateway.providers import ProviderError
from omnivox_protocol import (
    AudioInput,
    Cancelled,
    Completed,
    PipelineEvent,
    RequestContext,
    ResponseText,
    SpokenAudio,
    TranscriptReady,
)


class EvaluationOutcome(StrEnum):
    """Terminal outcome recorded by the evaluation harness."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PipelineExecutor(Protocol):
    """Minimal pipeline contract required by the evaluation harness."""

    def execute(
        self, audio: AudioInput, context: RequestContext
    ) -> AsyncIterator[PipelineEvent]:
        """Yield pipeline events for one utterance."""
        ...


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Content-free timing and outcome data for one request."""

    request_id: str
    outcome: EvaluationOutcome
    transcript_ms: float | None
    first_text_ms: float | None
    first_audio_ms: float | None
    total_ms: float
    stt_provider: str | None
    omni_provider: str | None
    tts_provider: str | None
    error_code: str | None

    def as_record(self) -> dict[str, object]:
        """Return a machine-readable record containing no speech content."""
        return {
            "request_id": self.request_id,
            "outcome": self.outcome.value,
            "transcript_ms": self.transcript_ms,
            "first_text_ms": self.first_text_ms,
            "first_audio_ms": self.first_audio_ms,
            "total_ms": self.total_ms,
            "stt_provider": self.stt_provider,
            "omni_provider": self.omni_provider,
            "tts_provider": self.tts_provider,
            "error_code": self.error_code,
        }


class EvaluationRunner:
    """Run one pipeline interaction and reduce it to safe metrics."""

    def __init__(
        self,
        pipeline: PipelineExecutor,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._pipeline = pipeline
        self._clock = clock

    async def run(self, audio: AudioInput, context: RequestContext) -> EvaluationReport:
        """Evaluate one utterance without retaining its audio or text."""
        started_at = self._clock()
        transcript_ms: float | None = None
        first_text_ms: float | None = None
        first_audio_ms: float | None = None
        stt_provider: str | None = None
        omni_provider: str | None = None
        tts_provider: str | None = None
        outcome: EvaluationOutcome | None = None
        error_code: str | None = None

        try:
            async for event in self._pipeline.execute(audio, context):
                elapsed_ms = self._elapsed_ms(started_at)
                if isinstance(event, TranscriptReady) and transcript_ms is None:
                    transcript_ms = elapsed_ms
                    stt_provider = event.provider
                elif isinstance(event, ResponseText) and first_text_ms is None:
                    first_text_ms = elapsed_ms
                    omni_provider = event.provider
                elif isinstance(event, SpokenAudio) and first_audio_ms is None:
                    first_audio_ms = elapsed_ms
                    tts_provider = event.provider
                elif isinstance(event, Completed):
                    outcome = EvaluationOutcome.COMPLETED
                    break
                elif isinstance(event, Cancelled):
                    outcome = EvaluationOutcome.CANCELLED
                    break
        except ProviderError as error:
            outcome = EvaluationOutcome.FAILED
            error_code = error.code

        total_ms = self._elapsed_ms(started_at)
        if outcome is None:
            outcome = EvaluationOutcome.FAILED
            error_code = "INCOMPLETE_PIPELINE"

        return EvaluationReport(
            request_id=context.request_id,
            outcome=outcome,
            transcript_ms=transcript_ms,
            first_text_ms=first_text_ms,
            first_audio_ms=first_audio_ms,
            total_ms=total_ms,
            stt_provider=stt_provider,
            omni_provider=omni_provider,
            tts_provider=tts_provider,
            error_code=error_code,
        )

    def _elapsed_ms(self, started_at: float) -> float:
        return (self._clock() - started_at) * 1000.0
