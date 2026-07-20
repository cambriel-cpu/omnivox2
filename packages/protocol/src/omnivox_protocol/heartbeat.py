"""Connection-scoped ping and pong codecs for protocol v2."""

from dataclasses import dataclass
from typing import assert_never

from omnivox_protocol.control import MAX_CONTROL_FRAME_BYTES, PROTOCOL_VERSION
from omnivox_protocol.errors import ProtocolViolation
from omnivox_protocol.json_codec import decode_control_object, encode_control_object

_HEARTBEAT_FIELDS = {"nonce", "protocol_version", "type"}
_MAX_NONCE_LENGTH = 64
_ASCII_PRINTABLE_MIN = 32
_ASCII_PRINTABLE_MAX = 126


@dataclass(frozen=True, slots=True)
class Ping:
    """Gateway or device liveness probe."""

    nonce: str


@dataclass(frozen=True, slots=True)
class Pong:
    """Liveness response carrying the probe's exact nonce."""

    nonce: str


type Heartbeat = Ping | Pong


def encode_heartbeat(heartbeat: Heartbeat) -> bytes:
    """Encode one validated connection-scoped heartbeat."""
    if isinstance(heartbeat, Ping):
        message_type = "ping"
    elif isinstance(heartbeat, Pong):
        message_type = "pong"
    else:
        assert_never(heartbeat)
    _validate_nonce(heartbeat.nonce)
    return encode_control_object(
        {
            "type": message_type,
            "protocol_version": PROTOCOL_VERSION,
            "nonce": heartbeat.nonce,
        },
        max_bytes=MAX_CONTROL_FRAME_BYTES,
    )


def decode_heartbeat(
    frame: bytes, *, max_frame_bytes: int = MAX_CONTROL_FRAME_BYTES
) -> Heartbeat:
    """Decode a strict ping or pong control frame."""
    value = decode_control_object(frame, max_bytes=max_frame_bytes)
    if set(value) != _HEARTBEAT_FIELDS:
        raise _violation("heartbeat fields do not match schema")
    version = value["protocol_version"]
    if type(version) is not int:
        raise _violation("protocol version must be an integer")
    if version != PROTOCOL_VERSION:
        raise ProtocolViolation(
            code="PROTOCOL_UNSUPPORTED",
            message="protocol major version is unsupported",
        )
    nonce = value["nonce"]
    if not isinstance(nonce, str):
        raise _violation("heartbeat nonce must be a string")
    _validate_nonce(nonce)
    if value["type"] == "ping":
        return Ping(nonce=nonce)
    if value["type"] == "pong":
        return Pong(nonce=nonce)
    raise _violation("heartbeat type is unsupported")


def _validate_nonce(nonce: str) -> None:
    if (
        not isinstance(nonce, str)
        or not 1 <= len(nonce) <= _MAX_NONCE_LENGTH
        or not all(
            _ASCII_PRINTABLE_MIN <= ord(character) <= _ASCII_PRINTABLE_MAX
            for character in nonce
        )
    ):
        raise _violation("heartbeat nonce is invalid")


def _violation(message: str) -> ProtocolViolation:
    return ProtocolViolation(code="INVALID_MESSAGE", message=message)
