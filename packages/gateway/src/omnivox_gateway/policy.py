"""Deterministic deadline and resource policies for the voice pipeline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class PipelineStage(StrEnum):
    """Pipeline stages with independently enforced deadlines."""

    STT = "stt"
    OPENCLAW = "openclaw"
    TTS = "tts"


@dataclass(frozen=True, slots=True)
class PipelineDeadlines:
    """Per-attempt and per-segment deadlines in seconds."""

    stt_seconds: float = 10.0
    openclaw_segment_seconds: float = 30.0
    tts_chunk_seconds: float = 10.0


@dataclass(frozen=True, slots=True)
class PipelineLimits:
    """Resource ceilings applied to each gateway pipeline."""

    max_active_requests: int = 32
    max_text_segments: int = 128
    max_response_characters: int = 16_000
    max_audio_chunks: int = 512


class DeadlineRunner(Protocol):
    """Run awaitables with an injectable stage deadline."""

    async def wait[ResultT](
        self,
        stage: PipelineStage,
        operation: Callable[[], Awaitable[ResultT]],
        timeout_seconds: float,
    ) -> ResultT:
        """Await one operation or raise ``TimeoutError``."""
        ...


class AsyncioDeadlineRunner:
    """Production deadline runner backed by the asyncio monotonic clock."""

    async def wait[ResultT](
        self,
        stage: PipelineStage,
        operation: Callable[[], Awaitable[ResultT]],
        timeout_seconds: float,
    ) -> ResultT:
        """Await one operation until its configured deadline."""
        del stage
        async with asyncio.timeout(timeout_seconds):
            return await operation()


DEFAULT_PIPELINE_DEADLINES = PipelineDeadlines()
DEFAULT_PIPELINE_LIMITS = PipelineLimits()
