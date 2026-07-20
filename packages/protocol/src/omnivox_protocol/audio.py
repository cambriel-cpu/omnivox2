"""Fixed binary audio-frame codec for protocol v2."""

from dataclasses import dataclass
from enum import IntEnum
from struct import Struct
from uuid import UUID

from omnivox_protocol.control import PROTOCOL_VERSION
from omnivox_protocol.errors import ProtocolViolation

MAX_BINARY_FRAME_BYTES = 65_536
AUDIO_HEADER_BYTES = 28
_MAGIC = b"OV"
_END_OF_STREAM = 0x01
_KNOWN_FLAGS = _END_OF_STREAM
_HEADER = Struct("!2sBBB3s16sI")
_MAX_SEQUENCE = 0xFFFF_FFFF


class AudioCodec(IntEnum):
    """Audio codec identifiers supported by protocol v2."""

    OPUS = 1


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """One request-correlated encoded audio frame."""

    request_id: UUID
    sequence: int
    payload: bytes
    codec: AudioCodec
    end_of_stream: bool = False


def encode_audio_frame(
    frame: AudioFrame, *, max_frame_bytes: int = MAX_BINARY_FRAME_BYTES
) -> bytes:
    """Encode one validated audio frame in network byte order."""
    _validate_audio_frame(frame)
    flags = _END_OF_STREAM if frame.end_of_stream else 0
    header = _HEADER.pack(
        _MAGIC,
        PROTOCOL_VERSION,
        flags,
        int(frame.codec),
        b"\x00\x00\x00",
        frame.request_id.bytes,
        frame.sequence,
    )
    encoded = header + frame.payload
    if len(encoded) > max_frame_bytes:
        raise _violation("PAYLOAD_TOO_LARGE", "binary frame exceeds size limit")
    return encoded


def decode_audio_frame(
    frame: bytes, *, max_frame_bytes: int = MAX_BINARY_FRAME_BYTES
) -> AudioFrame:
    """Decode a binary audio frame and fail closed on reserved values."""
    if len(frame) > max_frame_bytes:
        raise _violation("PAYLOAD_TOO_LARGE", "binary frame exceeds size limit")
    if len(frame) < AUDIO_HEADER_BYTES:
        raise _violation("INVALID_MESSAGE", "binary frame header is truncated")

    magic, version, flags, codec_value, reserved, request_bytes, sequence = (
        _HEADER.unpack_from(frame)
    )
    if magic != _MAGIC:
        raise _violation("INVALID_MESSAGE", "binary frame magic is invalid")
    if version != PROTOCOL_VERSION:
        raise _violation(
            "PROTOCOL_UNSUPPORTED", "protocol major version is unsupported"
        )
    if flags & ~_KNOWN_FLAGS:
        raise _violation("INVALID_MESSAGE", "binary frame flags are invalid")
    if reserved != b"\x00\x00\x00":
        raise _violation("INVALID_MESSAGE", "binary frame reserved bytes are nonzero")
    try:
        codec = AudioCodec(codec_value)
    except ValueError as error:
        raise _violation(
            "INVALID_MESSAGE", "binary frame codec is unsupported"
        ) from error

    payload = frame[AUDIO_HEADER_BYTES:]
    end_of_stream = bool(flags & _END_OF_STREAM)
    decoded = AudioFrame(
        request_id=UUID(bytes=request_bytes),
        sequence=sequence,
        payload=payload,
        codec=codec,
        end_of_stream=end_of_stream,
    )
    _validate_audio_frame(decoded)
    return decoded


def _validate_audio_frame(frame: AudioFrame) -> None:
    if not isinstance(frame.request_id, UUID):
        raise _violation("INVALID_MESSAGE", "audio request id is invalid")
    if type(frame.sequence) is not int or not 0 <= frame.sequence <= _MAX_SEQUENCE:
        raise _violation("INVALID_MESSAGE", "audio sequence is invalid")
    if not isinstance(frame.codec, AudioCodec):
        raise _violation("INVALID_MESSAGE", "audio codec is invalid")
    if not isinstance(frame.payload, bytes):
        raise _violation("INVALID_MESSAGE", "audio payload must be bytes")
    if not frame.payload and not frame.end_of_stream:
        raise _violation("INVALID_MESSAGE", "audio payload must not be empty")


def _violation(code: str, message: str) -> ProtocolViolation:
    return ProtocolViolation(code=code, message=message)
