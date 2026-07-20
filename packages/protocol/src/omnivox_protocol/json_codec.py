"""Shared strict JSON helpers for protocol control frames."""

import json
from collections.abc import Mapping
from typing import Any

from omnivox_protocol.errors import ProtocolViolation


def encode_control_object(value: Mapping[str, object], *, max_bytes: int) -> bytes:
    """Encode a canonical compact control object within a byte limit."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > max_bytes:
        raise ProtocolViolation(
            code="PAYLOAD_TOO_LARGE",
            message="control frame exceeds size limit",
        )
    return encoded


def decode_control_object(frame: bytes, *, max_bytes: int) -> dict[str, Any]:
    """Decode one bounded UTF-8 object while rejecting duplicate fields."""
    if len(frame) > max_bytes:
        raise ProtocolViolation(
            code="PAYLOAD_TOO_LARGE",
            message="control frame exceeds size limit",
        )
    try:
        text = frame.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_object_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolViolation(
            code="INVALID_MESSAGE",
            message="control frame is not valid JSON",
        ) from error
    if not isinstance(value, dict):
        raise ProtocolViolation(
            code="INVALID_MESSAGE",
            message="control frame must be a JSON object",
        )
    return value


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolViolation(
                code="INVALID_MESSAGE",
                message="control frame contains duplicate fields",
            )
        value[key] = item
    return value
