"""Shared protocol types for Omni Vox 2."""

from omnivox_protocol.audio import (
    AUDIO_HEADER_BYTES,
    MAX_BINARY_FRAME_BYTES,
    AudioCodec,
    AudioFrame,
    decode_audio_frame,
    encode_audio_frame,
)
from omnivox_protocol.control import (
    MAX_CONTROL_FRAME_BYTES,
    PROTOCOL_VERSION,
    Hello,
    decode_hello,
    encode_hello,
)
from omnivox_protocol.errors import ProtocolViolation
from omnivox_protocol.models import (
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

__all__ = [
    "AUDIO_HEADER_BYTES",
    "MAX_BINARY_FRAME_BYTES",
    "MAX_CONTROL_FRAME_BYTES",
    "PROTOCOL_VERSION",
    "AudioChunk",
    "AudioCodec",
    "AudioFrame",
    "AudioInput",
    "Cancelled",
    "Completed",
    "Hello",
    "PipelineEvent",
    "ProtocolViolation",
    "RequestContext",
    "ResponseText",
    "SpokenAudio",
    "TextSegment",
    "Transcript",
    "TranscriptReady",
    "decode_audio_frame",
    "decode_hello",
    "encode_audio_frame",
    "encode_hello",
]
