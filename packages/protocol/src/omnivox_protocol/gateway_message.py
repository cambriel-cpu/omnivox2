"""Typed request-scoped gateway control messages for protocol v2."""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never
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
_MAX_SEQUENCE = 0xFFFF_FFFF
_SAMPLE_RATE_HZ = 48_000
_CHANNELS = 1


@dataclass(frozen=True, slots=True)
class TranscriptMessage:
    """Confirmed transcript sent to a device."""

    request: WireRequest
    text: str
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ResponseSegmentMessage:
    """One ordered OpenClaw response segment sent to a device."""

    request: WireRequest
    text: str
    segment_sequence: int


@dataclass(frozen=True, slots=True)
class AudioStart:
    """Start of an Opus response audio stream."""

    request: WireRequest


@dataclass(frozen=True, slots=True)
class AudioEnd:
    """End of a response audio stream after its final binary frame."""

    request: WireRequest
    final_audio_sequence: int


class DeviceState(StrEnum):
    """Canonical visible state shared by gateway and device."""

    BOOTING = "booting"
    CONNECTING = "connecting"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    UNAVAILABLE = "unavailable"
    RECONNECTING = "reconnecting"


@dataclass(frozen=True, slots=True)
class StateMessage:
    """One correlated visible-state transition."""

    request: WireRequest
    name: DeviceState


type GatewayMessage = (
    TranscriptMessage | ResponseSegmentMessage | AudioStart | AudioEnd | StateMessage
)


def encode_gateway_message(message: GatewayMessage) -> bytes:
    """Encode one validated gateway-to-device control message."""
    if isinstance(message, TranscriptMessage):
        message_type = "transcript"
        _text(message.text)
        payload: dict[str, object] = {"text": message.text}
        if message.confidence is not None:
            _validate_confidence(message.confidence)
            payload["confidence"] = message.confidence
    elif isinstance(message, ResponseSegmentMessage):
        message_type = "response_segment"
        _text(message.text)
        _validate_sequence(message.segment_sequence, "response segment sequence")
        payload = {
            "text": message.text,
            "segment_sequence": message.segment_sequence,
        }
    elif isinstance(message, AudioStart):
        message_type = "audio_start"
        payload = {
            "codec": "opus",
            "sample_rate_hz": _SAMPLE_RATE_HZ,
            "channels": _CHANNELS,
        }
    elif isinstance(message, AudioEnd):
        message_type = "audio_end"
        _validate_sequence(message.final_audio_sequence, "final audio sequence")
        payload = {"final_audio_sequence": message.final_audio_sequence}
    elif isinstance(message, StateMessage):
        message_type = "state"
        if not isinstance(message.name, DeviceState):
            raise _violation("device state is invalid")
        payload = {"name": message.name.value}
    else:
        assert_never(message)

    _validate_request(message.request)
    return encode_control_object(
        {
            "type": message_type,
            "protocol_version": PROTOCOL_VERSION,
            "conversation_id": str(message.request.conversation_id),
            "request_id": str(message.request.request_id),
            "sequence": message.request.sequence,
            "payload": payload,
        },
        max_bytes=MAX_CONTROL_FRAME_BYTES,
    )


def decode_gateway_message(
    frame: bytes, *, max_frame_bytes: int = MAX_CONTROL_FRAME_BYTES
) -> GatewayMessage:
    """Decode one strict gateway-to-device control message."""
    value = decode_control_object(frame, max_bytes=max_frame_bytes)
    if set(value) != _ENVELOPE_FIELDS:
        raise _violation("gateway message fields do not match schema")
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
        raise _violation("gateway message type and payload are invalid")
    return _decode_payload(request, message_type, payload)


def _decode_payload(
    request: WireRequest,
    message_type: str,
    payload: dict[str, object],
) -> GatewayMessage:
    if message_type == "transcript":
        return _decode_transcript(request, payload)
    if message_type == "response_segment":
        _require_payload_fields(payload, {"segment_sequence", "text"})
        text = _text(payload["text"])
        return ResponseSegmentMessage(
            request=request,
            text=text,
            segment_sequence=_sequence(
                payload["segment_sequence"], "response segment sequence"
            ),
        )
    if message_type == "audio_start":
        _decode_audio_start(payload)
        return AudioStart(request=request)
    if message_type == "audio_end":
        _require_payload_fields(payload, {"final_audio_sequence"})
        return AudioEnd(
            request=request,
            final_audio_sequence=_sequence(
                payload["final_audio_sequence"], "final audio sequence"
            ),
        )
    if message_type == "state":
        _require_payload_fields(payload, {"name"})
        name_value = payload["name"]
        if not isinstance(name_value, str):
            raise _violation("device state is invalid")
        try:
            name = DeviceState(name_value)
        except (TypeError, ValueError) as error:
            raise _violation("device state is invalid") from error
        return StateMessage(request=request, name=name)
    raise _violation("gateway message type is unsupported")


def _decode_transcript(
    request: WireRequest, payload: dict[str, object]
) -> TranscriptMessage:
    if set(payload) not in ({"text"}, {"confidence", "text"}):
        raise _violation("transcript payload fields do not match schema")
    text = _text(payload["text"])
    confidence_value = payload.get("confidence")
    if confidence_value is None:
        return TranscriptMessage(request=request, text=text)
    confidence = _confidence(confidence_value)
    return TranscriptMessage(request=request, text=text, confidence=confidence)


def _decode_audio_start(payload: dict[str, object]) -> None:
    _require_payload_fields(payload, {"channels", "codec", "sample_rate_hz"})
    if (
        payload["codec"] != "opus"
        or type(payload["channels"]) is not int
        or payload["channels"] != _CHANNELS
        or type(payload["sample_rate_hz"]) is not int
        or payload["sample_rate_hz"] != _SAMPLE_RATE_HZ
    ):
        raise _violation("response audio format is unsupported")


def _validate_request(request: WireRequest) -> None:
    if not isinstance(request.conversation_id, UUID) or not isinstance(
        request.request_id, UUID
    ):
        raise _violation("request identifiers are invalid")
    _validate_sequence(request.sequence, "control sequence")


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise _violation("message text must be a string")
    return value


def _confidence(value: object) -> float:
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        raise _violation("transcript confidence must be a number")
    confidence = float(value)
    _validate_confidence(confidence)
    return confidence


def _validate_confidence(value: float) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise _violation("transcript confidence is invalid")


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
    if type(value) is not int or not 0 <= value <= _MAX_SEQUENCE:
        raise _violation(f"{field_name} is outside the uint32 range")


def _require_payload_fields(payload: dict[str, object], expected: set[str]) -> None:
    if set(payload) != expected:
        raise _violation("message payload fields do not match schema")


def _violation(message: str) -> ProtocolViolation:
    return ProtocolViolation(code="INVALID_MESSAGE", message=message)
