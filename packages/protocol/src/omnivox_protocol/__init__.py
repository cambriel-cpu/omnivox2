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
from omnivox_protocol.welcome import (
    ProtocolLimits,
    Welcome,
    decode_welcome,
    encode_welcome,
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
    "ProtocolLimits",
    "ProtocolViolation",
    "RequestContext",
    "ResponseText",
    "SpokenAudio",
    "TextSegment",
    "Transcript",
    "TranscriptReady",
    "Welcome",
    "decode_audio_frame",
    "decode_hello",
    "decode_welcome",
    "encode_audio_frame",
    "encode_hello",
    "encode_welcome",
]
