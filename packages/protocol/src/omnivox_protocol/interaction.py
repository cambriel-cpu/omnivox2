"""Typed request-scoped client control messages for protocol v2."""

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never
from uuid import UUID

from omnivox_protocol.control import MAX_CONTROL_FRAME_BYTES, PROTOCOL_VERSION
from omnivox_protocol.errors import ProtocolViolation
from omnivox_protocol.json_codec import decode_control_object, encode_control_object

_ENVELOPE_FIELDS = {
    "conversation_id",
    "payload",
    "protocol_version",
    "request_id",
    "sequence",
    "type",
}
_MAX_SEQUENCE = 0xFFFF_FFFF
_SAMPLE_RATE_HZ = 48_000
_CHANNELS = 1


@dataclass(frozen=True, slots=True)
class WireRequest:
    """Canonical request identifiers and one sender's control sequence."""

    conversation_id: UUID
    request_id: UUID
    sequence: int


@dataclass(frozen=True, slots=True)
class Wake:
    """Local wake-word detection for a new utterance."""

    request: WireRequest


@dataclass(frozen=True, slots=True)
class UtteranceStart:
    """Start of Opus microphone audio for a request."""

    request: WireRequest


@dataclass(frozen=True, slots=True)
class UtteranceEnd:
    """End of microphone audio after a final binary frame."""

    request: WireRequest
    final_audio_sequence: int


class CancelReason(StrEnum):
    """Bounded reason a live request was cancelled."""

    BARGE_IN = "barge_in"
    USER = "user"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class CancelRequest:
    """Idempotent cancellation request."""

    request: WireRequest
    reason: CancelReason


type ClientMessage = Wake | UtteranceStart | UtteranceEnd | CancelRequest


def encode_client_message(message: ClientMessage) -> bytes:
    """Encode one validated request-scoped client control message."""
    if isinstance(message, Wake):
        message_type = "wake"
        payload: dict[str, object] = {}
    elif isinstance(message, UtteranceStart):
        message_type = "utterance_start"
        payload = {
            "codec": "opus",
            "sample_rate_hz": _SAMPLE_RATE_HZ,
            "channels": _CHANNELS,
        }
    elif isinstance(message, UtteranceEnd):
        message_type = "utterance_end"
        _validate_sequence(message.final_audio_sequence, "final audio sequence")
        payload = {"final_audio_sequence": message.final_audio_sequence}
    elif isinstance(message, CancelRequest):
        message_type = "cancel"
        if not isinstance(message.reason, CancelReason):
            raise _violation("cancel reason is invalid")
        payload = {"reason": message.reason.value}
    else:
        assert_never(message)

    _validate_request(message.request)
    value = {
        "type": message_type,
        "protocol_version": PROTOCOL_VERSION,
        "conversation_id": str(message.request.conversation_id),
        "request_id": str(message.request.request_id),
        "sequence": message.request.sequence,
        "payload": payload,
    }
    return encode_control_object(value, max_bytes=MAX_CONTROL_FRAME_BYTES)


def decode_client_message(
    frame: bytes, *, max_frame_bytes: int = MAX_CONTROL_FRAME_BYTES
) -> ClientMessage:
    """Decode a strict request-scoped message sent by a device."""
    value = decode_control_object(frame, max_bytes=max_frame_bytes)
    if set(value) != _ENVELOPE_FIELDS:
        raise _violation("interaction fields do not match schema")
    version = value["protocol_version"]
    if type(version) is not int:
        raise _violation("protocol version must be an integer")
    if version != PROTOCOL_VERSION:
        raise ProtocolViolation(
            code="PROTOCOL_UNSUPPORTED",
            message="protocol major version is unsupported",
        )

    request = WireRequest(
        conversation_id=_canonical_uuid(value["conversation_id"], "conversation id"),
        request_id=_canonical_uuid(value["request_id"], "request id"),
        sequence=_sequence(value["sequence"], "control sequence"),
    )
    payload = value["payload"]
    message_type = value["type"]
    if not isinstance(payload, dict) or not isinstance(message_type, str):
        raise _violation("interaction type and payload are invalid")

    if message_type == "wake":
        _require_payload_fields(payload, set())
        return Wake(request)
    if message_type == "utterance_start":
        _decode_utterance_start(payload)
        return UtteranceStart(request)
    if message_type == "utterance_end":
        _require_payload_fields(payload, {"final_audio_sequence"})
        final_sequence = _sequence(
            payload["final_audio_sequence"], "final audio sequence"
        )
        return UtteranceEnd(request, final_audio_sequence=final_sequence)
    if message_type == "cancel":
        _require_payload_fields(payload, {"reason"})
        try:
            reason = CancelReason(payload["reason"])
        except (TypeError, ValueError) as error:
            raise _violation("cancel reason is invalid") from error
        return CancelRequest(request, reason=reason)
    raise _violation("client message type is unsupported")


def _decode_utterance_start(payload: dict[str, object]) -> None:
    _require_payload_fields(payload, {"channels", "codec", "sample_rate_hz"})
    if (
        payload["codec"] != "opus"
        or type(payload["channels"]) is not int
        or payload["channels"] != _CHANNELS
        or type(payload["sample_rate_hz"]) is not int
        or payload["sample_rate_hz"] != _SAMPLE_RATE_HZ
    ):
        raise _violation("utterance audio format is unsupported")


def _require_payload_fields(payload: dict[str, object], expected: set[str]) -> None:
    if set(payload) != expected:
        raise _violation("message payload fields do not match schema")


def _validate_request(request: WireRequest) -> None:
    if not isinstance(request.conversation_id, UUID) or not isinstance(
        request.request_id, UUID
    ):
        raise _violation("request identifiers are invalid")
    _validate_sequence(request.sequence, "control sequence")


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


def _sequence(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise _violation(f"{field_name} must be an integer")
    _validate_sequence(value, field_name)
    return value


def _validate_sequence(value: int, field_name: str) -> None:
    if not 0 <= value <= _MAX_SEQUENCE:
        raise _violation(f"{field_name} is outside the uint32 range")


def _violation(message: str) -> ProtocolViolation:
    return ProtocolViolation(code="INVALID_MESSAGE", message=message)
