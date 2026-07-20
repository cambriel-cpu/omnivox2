"""Gateway welcome codec and negotiated protocol limits."""

import re
from dataclasses import dataclass
from uuid import UUID

from omnivox_protocol.audio import MAX_BINARY_FRAME_BYTES
from omnivox_protocol.control import MAX_CONTROL_FRAME_BYTES, PROTOCOL_VERSION
from omnivox_protocol.errors import ProtocolViolation
from omnivox_protocol.json_codec import decode_control_object, encode_control_object

_WELCOME_FIELDS = {
    "capabilities",
    "heartbeat_interval_ms",
    "limits",
    "protocol_version",
    "session_id",
    "type",
}
_LIMIT_FIELDS = {
    "max_binary_frame_bytes",
    "max_control_frame_bytes",
    "max_queue_depth",
    "max_utterance_ms",
}
_MAX_CAPABILITIES = 32
_MAX_CAPABILITY_LENGTH = 64
_MAX_QUEUE_DEPTH = 32
_MAX_UTTERANCE_MS = 30_000
_MIN_HEARTBEAT_INTERVAL_MS = 1_000
_MAX_HEARTBEAT_INTERVAL_MS = 60_000
_CAPABILITY = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True, slots=True)
class ProtocolLimits:
    """Gateway-enforced limits accepted for one device session."""

    max_binary_frame_bytes: int
    max_control_frame_bytes: int
    max_queue_depth: int
    max_utterance_ms: int


@dataclass(frozen=True, slots=True)
class Welcome:
    """Successful gateway response to a device hello."""

    session_id: UUID
    capabilities: tuple[str, ...]
    heartbeat_interval_ms: int
    limits: ProtocolLimits


def encode_welcome(welcome: Welcome) -> bytes:
    """Encode a validated welcome using canonical JSON."""
    _validate_welcome(welcome)
    value = {
        "type": "welcome",
        "protocol_version": PROTOCOL_VERSION,
        "session_id": str(welcome.session_id),
        "capabilities": sorted(welcome.capabilities),
        "heartbeat_interval_ms": welcome.heartbeat_interval_ms,
        "limits": {
            "max_binary_frame_bytes": welcome.limits.max_binary_frame_bytes,
            "max_control_frame_bytes": welcome.limits.max_control_frame_bytes,
            "max_queue_depth": welcome.limits.max_queue_depth,
            "max_utterance_ms": welcome.limits.max_utterance_ms,
        },
    }
    return encode_control_object(value, max_bytes=MAX_CONTROL_FRAME_BYTES)


def decode_welcome(
    frame: bytes, *, max_frame_bytes: int = MAX_CONTROL_FRAME_BYTES
) -> Welcome:
    """Decode a welcome and reject unknown, oversized, or unsupported data."""
    value = decode_control_object(frame, max_bytes=max_frame_bytes)
    if set(value) != _WELCOME_FIELDS:
        raise _violation("welcome fields do not match schema")
    version = value["protocol_version"]
    if type(version) is not int:
        raise _violation("protocol version must be an integer")
    if version != PROTOCOL_VERSION:
        raise ProtocolViolation(
            code="PROTOCOL_UNSUPPORTED",
            message="protocol major version is unsupported",
        )
    if value["type"] != "welcome":
        raise _violation("gateway handshake response must be welcome")

    session_id = _canonical_uuid(value["session_id"])
    capabilities = value["capabilities"]
    heartbeat_interval_ms = value["heartbeat_interval_ms"]
    limits_value = value["limits"]
    if not isinstance(capabilities, list) or not all(
        isinstance(capability, str) for capability in capabilities
    ):
        raise _violation("capabilities must be a string array")
    if not isinstance(limits_value, dict) or set(limits_value) != _LIMIT_FIELDS:
        raise _violation("welcome limits do not match schema")

    limits = ProtocolLimits(
        max_binary_frame_bytes=_integer(limits_value["max_binary_frame_bytes"]),
        max_control_frame_bytes=_integer(limits_value["max_control_frame_bytes"]),
        max_queue_depth=_integer(limits_value["max_queue_depth"]),
        max_utterance_ms=_integer(limits_value["max_utterance_ms"]),
    )
    welcome = Welcome(
        session_id=session_id,
        capabilities=tuple(sorted(capabilities)),
        heartbeat_interval_ms=_integer(heartbeat_interval_ms),
        limits=limits,
    )
    _validate_welcome(welcome)
    return welcome


def _validate_welcome(welcome: Welcome) -> None:
    if not isinstance(welcome.session_id, UUID):
        raise _violation("session id is invalid")
    if (
        len(welcome.capabilities) > _MAX_CAPABILITIES
        or len(set(welcome.capabilities)) != len(welcome.capabilities)
        or any(
            not capability
            or len(capability) > _MAX_CAPABILITY_LENGTH
            or _CAPABILITY.fullmatch(capability) is None
            for capability in welcome.capabilities
        )
    ):
        raise _violation("capabilities are invalid")
    if not (
        _MIN_HEARTBEAT_INTERVAL_MS
        <= welcome.heartbeat_interval_ms
        <= _MAX_HEARTBEAT_INTERVAL_MS
    ):
        raise _violation("heartbeat interval is invalid")
    limits = welcome.limits
    if not (
        1 <= limits.max_binary_frame_bytes <= MAX_BINARY_FRAME_BYTES
        and 1 <= limits.max_control_frame_bytes <= MAX_CONTROL_FRAME_BYTES
        and 1 <= limits.max_queue_depth <= _MAX_QUEUE_DEPTH
        and 1 <= limits.max_utterance_ms <= _MAX_UTTERANCE_MS
    ):
        raise _violation("protocol limits are invalid")


def _canonical_uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise _violation("session id must be a string")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise _violation("session id is invalid") from error
    if str(parsed) != value:
        raise _violation("session id is not canonical")
    return parsed


def _integer(value: object) -> int:
    if type(value) is not int:
        raise _violation("welcome numeric fields must be integers")
    return value


def _violation(message: str) -> ProtocolViolation:
    return ProtocolViolation(code="INVALID_MESSAGE", message=message)
