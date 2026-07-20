"""Bounded, replayable OpenClaw response text."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from omnivox_protocol import TextSegment

from omnivox_gateway.policy import (
    DeadlineRunner,
    PipelineDeadlines,
    PipelineLimits,
    PipelineStage,
)
from omnivox_gateway.providers import ProviderError


class CachingTextSource:
    """Cache bounded response text so one TTS fallback can replay it."""

    def __init__(
        self,
        source: AsyncIterator[TextSegment],
        *,
        deadline_runner: DeadlineRunner,
        deadlines: PipelineDeadlines,
        limits: PipelineLimits,
    ) -> None:
        self._source = source
        self._deadline_runner = deadline_runner
        self._deadlines = deadlines
        self._limits = limits
        self._character_count = 0
        self.segments: list[TextSegment] = []

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TextSegment:
        try:
            segment = await self._deadline_runner.wait(
                PipelineStage.OPENCLAW,
                lambda: anext(self._source),
                self._deadlines.openclaw_segment_seconds,
            )
        except TimeoutError as error:
            message = "OpenClaw response segment deadline exceeded"
            raise ProviderError(
                code="OPENCLAW_TIMEOUT",
                message=message,
                retryable=False,
            ) from error

        character_count = self._character_count + len(segment.text)
        if (
            len(self.segments) >= self._limits.max_text_segments
            or character_count > self._limits.max_response_characters
        ):
            message = "OpenClaw response exceeded the configured resource limit"
            raise ProviderError(
                code="RESPONSE_LIMIT_EXCEEDED",
                message=message,
                retryable=False,
            )
        self._character_count = character_count
        self.segments.append(segment)
        return segment

    def replay(self) -> ReplayTextSource:
        """Replay cached segments, then continue the original source."""
        return ReplayTextSource(self)


class ReplayTextSource:
    """One replay cursor over a caching text source."""

    def __init__(self, source: CachingTextSource) -> None:
        self._source = source
        self._index = 0

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TextSegment:
        if self._index < len(self._source.segments):
            segment = self._source.segments[self._index]
        else:
            segment = await anext(self._source)
        self._index += 1
        return segment
