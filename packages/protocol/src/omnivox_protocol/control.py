"""Strict JSON control-frame codecs for protocol v2."""

import json
import re
from dataclasses import dataclass
from typing import Any

from omnivox_protocol.errors import ProtocolViolation

PROTOCOL_VERSION = 2
MAX_CONTROL_FRAME_BYTES = 16_384
_MAX_DEVICE_ID_LENGTH = 64
_MAX_CLIENT_VERSION_LENGTH = 128
_MAX_CAPABILITIES = 32
_MAX_CAPABILITY_LENGTH = 64
_ASCII_PRINTABLE_MIN = 32
_ASCII_PRINTABLE_MAX = 126
_HELLO_FIELDS = {
    "capabilities",
    "client_version",
    "device_id",
    "protocol_version",
    "type",
}
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True, slots=True)
class Hello:
    """First control message sent by an authenticated device."""

    device_id: str
    client_version: str
    capabilities: tuple[str, ...]


def encode_hello(hello: Hello) -> bytes:
    """Encode a validated hello using the canonical JSON representation."""
    _validate_hello(hello)
    value = {
        "type": "hello",
        "protocol_version": PROTOCOL_VERSION,
        "device_id": hello.device_id,
        "client_version": hello.client_version,
        "capabilities": sorted(hello.capabilities),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_CONTROL_FRAME_BYTES:
        raise _violation("PAYLOAD_TOO_LARGE", "control frame exceeds size limit")
    return encoded


def decode_hello(
    frame: bytes, *, max_frame_bytes: int = MAX_CONTROL_FRAME_BYTES
) -> Hello:
    """Decode a hello frame and reject every non-v2 or unknown field."""
    if len(frame) > max_frame_bytes:
        raise _violation("PAYLOAD_TOO_LARGE", "control frame exceeds size limit")

    value = _decode_object(frame)
    if set(value) != _HELLO_FIELDS:
        raise _violation("INVALID_MESSAGE", "hello fields do not match schema")
    protocol_version = value["protocol_version"]
    if type(protocol_version) is not int:
        raise _violation("INVALID_MESSAGE", "protocol version must be an integer")
    if protocol_version != PROTOCOL_VERSION:
        raise _violation(
            "PROTOCOL_UNSUPPORTED", "protocol major version is unsupported"
        )
    if value["type"] != "hello":
        raise _violation("INVALID_MESSAGE", "first message must be hello")

    device_id = value["device_id"]
    client_version = value["client_version"]
    capabilities = value["capabilities"]
    if not isinstance(device_id, str) or not isinstance(client_version, str):
        raise _violation("INVALID_MESSAGE", "hello identity fields must be strings")
    if not isinstance(capabilities, list) or not all(
        isinstance(capability, str) for capability in capabilities
    ):
        raise _violation("INVALID_MESSAGE", "capabilities must be a string array")

    hello = Hello(
        device_id=device_id,
        client_version=client_version,
        capabilities=tuple(sorted(capabilities)),
    )
    _validate_hello(hello)
    return hello


def _decode_object(frame: bytes) -> dict[str, Any]:
    try:
        text = frame.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_object_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _violation(
            "INVALID_MESSAGE", "control frame is not valid JSON"
        ) from error
    if not isinstance(value, dict):
        raise _violation("INVALID_MESSAGE", "control frame must be a JSON object")
    return value


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _violation(
                "INVALID_MESSAGE", "control frame contains duplicate fields"
            )
        value[key] = item
    return value


def _validate_hello(hello: Hello) -> None:
    if (
        not 1 <= len(hello.device_id) <= _MAX_DEVICE_ID_LENGTH
        or _IDENTIFIER.fullmatch(hello.device_id) is None
    ):
        raise _violation("INVALID_MESSAGE", "device id is invalid")
    if not 1 <= len(hello.client_version) <= _MAX_CLIENT_VERSION_LENGTH or not all(
        _ASCII_PRINTABLE_MIN <= ord(character) <= _ASCII_PRINTABLE_MAX
        for character in hello.client_version
    ):
        raise _violation("INVALID_MESSAGE", "client version is invalid")
    if len(hello.capabilities) > _MAX_CAPABILITIES or len(
        set(hello.capabilities)
    ) != len(hello.capabilities):
        raise _violation("INVALID_MESSAGE", "capabilities are invalid")
    if any(
        not 1 <= len(capability) <= _MAX_CAPABILITY_LENGTH
        or _IDENTIFIER.fullmatch(capability) is None
        for capability in hello.capabilities
    ):
        raise _violation("INVALID_MESSAGE", "capability identifier is invalid")


def _violation(code: str, message: str) -> ProtocolViolation:
    return ProtocolViolation(code=code, message=message)
