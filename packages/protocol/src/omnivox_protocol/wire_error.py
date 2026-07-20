"""Request-scoped, user-safe error codec for protocol v2."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from omnivox_protocol.control import MAX_CONTROL_FRAME_BYTES, PROTOCOL_VERSION
from omnivox_protocol.errors import ProtocolViolation
from omnivox_protocol.interaction import WireRequest
from omnivox_protocol.json_codec import decode_control_object, encode_control_object

_ENVELOPE_FIELDS = {
    "conversation_id",
    "payload",
    "protocol_version",
    "request_id",
    "sequence",
    "type",
}
_PAYLOAD_FIELDS = {"code", "message", "retryable", "trace_id"}
_MAX_SEQUENCE = 0xFFFF_FFFF
_MAX_MESSAGE_LENGTH = 256


class ErrorCode(StrEnum):
    """Closed set of error categories supported by protocol v2."""

    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PROTOCOL_UNSUPPORTED = "PROTOCOL_UNSUPPORTED"
    INVALID_MESSAGE = "INVALID_MESSAGE"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    AUDIO_DEVICE_FAILED = "AUDIO_DEVICE_FAILED"
    STT_UNAVAILABLE = "STT_UNAVAILABLE"
    STT_TIMEOUT = "STT_TIMEOUT"
    OPENCLAW_UNAVAILABLE = "OPENCLAW_UNAVAILABLE"
    OPENCLAW_TIMEOUT = "OPENCLAW_TIMEOUT"
    TTS_UNAVAILABLE = "TTS_UNAVAILABLE"
    TTS_TIMEOUT = "TTS_TIMEOUT"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class ErrorMessage:
    """One request-correlated error safe to show to a user."""

    request: WireRequest
    code: ErrorCode
    message: str
    retryable: bool
    trace_id: UUID


def encode_error_message(error: ErrorMessage) -> bytes:
    """Encode one validated request-scoped error."""
    _validate_error(error)
    return encode_control_object(
        {
            "type": "error",
            "protocol_version": PROTOCOL_VERSION,
            "conversation_id": str(error.request.conversation_id),
            "request_id": str(error.request.request_id),
            "sequence": error.request.sequence,
            "payload": {
                "code": error.code.value,
                "message": error.message,
                "retryable": error.retryable,
                "trace_id": str(error.trace_id),
            },
        },
        max_bytes=MAX_CONTROL_FRAME_BYTES,
    )


def decode_error_message(
    frame: bytes, *, max_frame_bytes: int = MAX_CONTROL_FRAME_BYTES
) -> ErrorMessage:
    """Decode a strict request-scoped error message."""
    value = decode_control_object(frame, max_bytes=max_frame_bytes)
    if set(value) != _ENVELOPE_FIELDS or value["type"] != "error":
        raise _violation("error fields do not match schema")
    version = value["protocol_version"]
    if type(version) is not int:
        raise _violation("protocol version must be an integer")
    if version != PROTOCOL_VERSION:
        raise ProtocolViolation(
            code="PROTOCOL_UNSUPPORTED",
            message="protocol major version is unsupported",
        )

    payload = value["payload"]
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        raise _violation("error payload fields do not match schema")
    try:
        code = ErrorCode(payload["code"])
    except (TypeError, ValueError) as error:
        raise _violation("error code is unsupported") from error

    message = payload["message"]
    retryable = payload["retryable"]
    if not isinstance(message, str) or type(retryable) is not bool:
        raise _violation("error payload values are invalid")
    decoded = ErrorMessage(
        request=WireRequest(
            conversation_id=_canonical_uuid(
                value["conversation_id"], "conversation id"
            ),
            request_id=_canonical_uuid(value["request_id"], "request id"),
            sequence=_sequence(value["sequence"]),
        ),
        code=code,
        message=message,
        retryable=retryable,
        trace_id=_canonical_uuid(payload["trace_id"], "trace id"),
    )
    _validate_error(decoded)
    return decoded


def _validate_error(error: ErrorMessage) -> None:
    request = error.request
    if not isinstance(request.conversation_id, UUID) or not isinstance(
        request.request_id, UUID
    ):
        raise _violation("error request identifiers are invalid")
    _validate_sequence(request.sequence)
    if not isinstance(error.code, ErrorCode):
        raise _violation("error code is unsupported")
    if (
        not isinstance(error.message, str)
        or not 1 <= len(error.message) <= _MAX_MESSAGE_LENGTH
        or not error.message.isprintable()
    ):
        raise _violation("error message is invalid")
    if type(error.retryable) is not bool:
        raise _violation("error retryable flag must be a boolean")
    if not isinstance(error.trace_id, UUID):
        raise _violation("error trace id is invalid")


def _canonical_uuid(value: object, field_name: str) -> UUID:
    if not isinstance(value, str):
        raise _violation(f"{field_name} must be a string")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise _violation(f"{field_name} is invalid") from error
    if str(parsed) != value:
        raise _violation(f"{field_name} is not canonical")
    return parsed


def _sequence(value: object) -> int:
    if type(value) is not int:
        raise _violation("error sequence must be an integer")
    _validate_sequence(value)
    return value


def _validate_sequence(value: int) -> None:
    if type(value) is not int or not 0 <= value <= _MAX_SEQUENCE:
        raise _violation("error sequence is outside the uint32 range")


def _violation(message: str) -> ProtocolViolation:
    return ProtocolViolation(code="INVALID_MESSAGE", message=message)
