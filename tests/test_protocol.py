from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest
from omnivox_protocol import (
    MAX_BINARY_FRAME_BYTES,
    MAX_CONTROL_FRAME_BYTES,
    AudioCodec,
    AudioFrame,
    Hello,
    ProtocolViolation,
    decode_audio_frame,
    decode_hello,
    encode_audio_frame,
    encode_hello,
)

FIXTURES = Path(__file__).parent / "fixtures" / "protocol"
REQUEST_ID = UUID("00000000-0000-4000-8000-000000000003")


def test_hello_encoding_matches_canonical_golden_fixture() -> None:
    hello = Hello(
        device_id="servo-skull-primary",
        client_version="9068d4d",
        capabilities=("opus-output", "barge-in", "opus-input"),
    )
    expected = (FIXTURES / "hello.json").read_bytes().rstrip(b"\n")

    assert encode_hello(hello) == expected
    assert decode_hello(expected) == Hello(
        device_id="servo-skull-primary",
        client_version="9068d4d",
        capabilities=("barge-in", "opus-input", "opus-output"),
    )


@pytest.mark.parametrize(
    ("frame", "code"),
    [
        (
            b'{"type":"hello","protocol_version":3,"device_id":"skull",'
            b'"client_version":"abc","capabilities":[]}',
            "PROTOCOL_UNSUPPORTED",
        ),
        (
            b'{"type":"hello","protocol_version":2.0,"device_id":"skull",'
            b'"client_version":"abc","capabilities":[]}',
            "INVALID_MESSAGE",
        ),
        (
            b'{"type":"hello","protocol_version":2,"device_id":"skull",'
            b'"client_version":"abc","capabilities":[],"unexpected":true}',
            "INVALID_MESSAGE",
        ),
        (
            b'{"type":"hello","type":"hello","protocol_version":2,'
            b'"device_id":"skull","client_version":"abc","capabilities":[]}',
            "INVALID_MESSAGE",
        ),
    ],
)
def test_hello_decoding_fails_closed(frame: bytes, code: str) -> None:
    with pytest.raises(ProtocolViolation) as raised:
        decode_hello(frame)

    assert raised.value.code == code


def test_hello_size_limit_is_checked_before_json_parsing() -> None:
    oversized = b"{" + (b"x" * MAX_CONTROL_FRAME_BYTES)

    with pytest.raises(ProtocolViolation) as raised:
        decode_hello(oversized)

    assert raised.value.code == "PAYLOAD_TOO_LARGE"


def test_audio_encoding_matches_binary_golden_fixture() -> None:
    frame = AudioFrame(
        request_id=REQUEST_ID,
        sequence=7,
        payload=b"Opus",
        codec=AudioCodec.OPUS,
        end_of_stream=True,
    )
    expected = bytes.fromhex(
        (FIXTURES / "audio-opus-eos.hex").read_text(encoding="ascii").strip()
    )

    assert encode_audio_frame(frame) == expected
    assert decode_audio_frame(expected) == frame


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda _frame: b"", "INVALID_MESSAGE"),
        (lambda frame: b"XX" + frame[2:], "INVALID_MESSAGE"),
        (lambda frame: frame[:2] + b"\x03" + frame[3:], "PROTOCOL_UNSUPPORTED"),
        (lambda frame: frame[:3] + b"\x80" + frame[4:], "INVALID_MESSAGE"),
        (lambda frame: frame[:5] + b"\x00\x00\x01" + frame[8:], "INVALID_MESSAGE"),
    ],
)
def test_audio_decoding_fails_closed(
    mutation: Callable[[bytes], bytes], code: str
) -> None:
    valid = encode_audio_frame(
        AudioFrame(
            request_id=REQUEST_ID,
            sequence=0,
            payload=b"audio",
            codec=AudioCodec.OPUS,
        )
    )

    with pytest.raises(ProtocolViolation) as raised:
        decode_audio_frame(mutation(valid))

    assert raised.value.code == code


def test_audio_size_limit_includes_header() -> None:
    oversized = AudioFrame(
        request_id=REQUEST_ID,
        sequence=0,
        payload=b"x" * MAX_BINARY_FRAME_BYTES,
        codec=AudioCodec.OPUS,
    )

    with pytest.raises(ProtocolViolation) as raised:
        encode_audio_frame(oversized)

    assert raised.value.code == "PAYLOAD_TOO_LARGE"
