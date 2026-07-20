from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest
from omnivox_protocol import (
    MAX_BINARY_FRAME_BYTES,
    MAX_CONTROL_FRAME_BYTES,
    AudioCodec,
    AudioEnd,
    AudioFrame,
    AudioStart,
    CancelReason,
    CancelRequest,
    ClientMessage,
    DeviceState,
    ErrorCode,
    ErrorMessage,
    GatewayMessage,
    Heartbeat,
    Hello,
    Ping,
    Pong,
    ProtocolLimits,
    ProtocolViolation,
    ResponseSegmentMessage,
    StateMessage,
    TranscriptMessage,
    UtteranceEnd,
    UtteranceStart,
    Wake,
    Welcome,
    WireRequest,
    decode_audio_frame,
    decode_client_message,
    decode_error_message,
    decode_gateway_message,
    decode_heartbeat,
    decode_hello,
    decode_welcome,
    encode_audio_frame,
    encode_client_message,
    encode_error_message,
    encode_gateway_message,
    encode_heartbeat,
    encode_hello,
    encode_welcome,
)

FIXTURES = Path(__file__).parent / "fixtures" / "protocol"
REQUEST_ID = UUID("00000000-0000-4000-8000-000000000003")
CONVERSATION_ID = UUID("00000000-0000-4000-8000-000000000002")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")


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


def test_welcome_encoding_matches_canonical_golden_fixture() -> None:
    welcome = Welcome(
        session_id=UUID("00000000-0000-4000-8000-000000000001"),
        capabilities=("opus-output", "barge-in", "opus-input"),
        heartbeat_interval_ms=15_000,
        limits=ProtocolLimits(
            max_binary_frame_bytes=65_536,
            max_control_frame_bytes=16_384,
            max_queue_depth=32,
            max_utterance_ms=30_000,
        ),
    )
    expected = (FIXTURES / "welcome.json").read_bytes().rstrip(b"\n")

    assert encode_welcome(welcome) == expected
    assert decode_welcome(expected) == Welcome(
        session_id=welcome.session_id,
        capabilities=("barge-in", "opus-input", "opus-output"),
        heartbeat_interval_ms=welcome.heartbeat_interval_ms,
        limits=welcome.limits,
    )


def test_welcome_rejects_invalid_capability_identifier() -> None:
    welcome = Welcome(
        session_id=UUID("00000000-0000-4000-8000-000000000001"),
        capabilities=("-invalid",),
        heartbeat_interval_ms=15_000,
        limits=ProtocolLimits(
            max_binary_frame_bytes=65_536,
            max_control_frame_bytes=16_384,
            max_queue_depth=32,
            max_utterance_ms=30_000,
        ),
    )

    with pytest.raises(ProtocolViolation):
        encode_welcome(welcome)


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


@pytest.mark.parametrize(
    ("message", "fixture_name"),
    [
        (
            Wake(WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=0)),
            "wake.json",
        ),
        (
            UtteranceStart(WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=1)),
            "utterance-start.json",
        ),
        (
            UtteranceEnd(
                WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=2),
                final_audio_sequence=1,
            ),
            "utterance-end.json",
        ),
        (
            CancelRequest(
                WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=3),
                reason=CancelReason.BARGE_IN,
            ),
            "cancel.json",
        ),
    ],
)
def test_client_control_matches_golden_fixture(
    message: ClientMessage, fixture_name: str
) -> None:
    expected = (FIXTURES / fixture_name).read_bytes().rstrip(b"\n")

    assert encode_client_message(message) == expected
    assert decode_client_message(expected) == message


@pytest.mark.parametrize(
    "frame",
    [
        (
            b'{"conversation_id":"00000000-0000-4000-8000-000000000002",'
            b'"payload":{},"protocol_version":2,'
            b'"request_id":"00000000-0000-4000-8000-000000000003",'
            b'"sequence":0.0,"type":"wake"}'
        ),
        (
            b'{"conversation_id":"NOT-A-UUID","payload":{},'
            b'"protocol_version":2,'
            b'"request_id":"00000000-0000-4000-8000-000000000003",'
            b'"sequence":0,"type":"wake"}'
        ),
        (
            b'{"conversation_id":"00000000-0000-4000-8000-000000000002",'
            b'"payload":{"extra":true},"protocol_version":2,'
            b'"request_id":"00000000-0000-4000-8000-000000000003",'
            b'"sequence":0,"type":"wake"}'
        ),
    ],
)
def test_client_control_fails_closed(frame: bytes) -> None:
    with pytest.raises(ProtocolViolation) as raised:
        decode_client_message(frame)

    assert raised.value.code == "INVALID_MESSAGE"


@pytest.mark.parametrize(
    ("heartbeat", "fixture_name"),
    [
        (Ping(nonce="heartbeat-0001"), "ping.json"),
        (Pong(nonce="heartbeat-0001"), "pong.json"),
    ],
)
def test_heartbeat_matches_golden_fixture(
    heartbeat: Heartbeat, fixture_name: str
) -> None:
    expected = (FIXTURES / fixture_name).read_bytes().rstrip(b"\n")

    assert encode_heartbeat(heartbeat) == expected
    assert decode_heartbeat(expected) == heartbeat


@pytest.mark.parametrize("nonce", ["", "x" * 65, "line\nbreak", "not-ascii-é"])
def test_heartbeat_rejects_invalid_nonce(nonce: str) -> None:
    with pytest.raises(ProtocolViolation) as raised:
        encode_heartbeat(Ping(nonce=nonce))

    assert raised.value.code == "INVALID_MESSAGE"


def test_heartbeat_fails_closed_on_unknown_fields() -> None:
    frame = (
        b'{"nonce":"heartbeat-0001","protocol_version":2,'
        b'"type":"ping","unexpected":true}'
    )

    with pytest.raises(ProtocolViolation) as raised:
        decode_heartbeat(frame)

    assert raised.value.code == "INVALID_MESSAGE"


def test_error_message_matches_golden_fixture() -> None:
    message = ErrorMessage(
        request=WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=4),
        code=ErrorCode.STT_UNAVAILABLE,
        message="Speech recognition is temporarily unavailable.",
        retryable=True,
        trace_id=TRACE_ID,
    )
    expected = (FIXTURES / "error.json").read_bytes().rstrip(b"\n")

    assert encode_error_message(message) == expected
    assert decode_error_message(expected) == message


@pytest.mark.parametrize(
    "message",
    [
        ErrorMessage(
            request=WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=4),
            code=ErrorCode.STT_UNAVAILABLE,
            message="",
            retryable=True,
            trace_id=TRACE_ID,
        ),
        ErrorMessage(
            request=WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=4),
            code=ErrorCode.STT_UNAVAILABLE,
            message="unsafe\nmessage",
            retryable=True,
            trace_id=TRACE_ID,
        ),
        ErrorMessage(
            request=WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=4),
            code=ErrorCode.STT_UNAVAILABLE,
            message="x" * 257,
            retryable=True,
            trace_id=TRACE_ID,
        ),
    ],
)
def test_error_message_rejects_unsafe_message(message: ErrorMessage) -> None:
    with pytest.raises(ProtocolViolation) as raised:
        encode_error_message(message)

    assert raised.value.code == "INVALID_MESSAGE"


def test_error_message_requires_strict_boolean() -> None:
    frame = (FIXTURES / "error.json").read_bytes().replace(b"true", b"1")

    with pytest.raises(ProtocolViolation) as raised:
        decode_error_message(frame)

    assert raised.value.code == "INVALID_MESSAGE"


@pytest.mark.parametrize(
    ("message", "fixture_name"),
    [
        (
            TranscriptMessage(
                WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=0),
                text="What time is it?",
                confidence=0.98,
            ),
            "transcript.json",
        ),
        (
            ResponseSegmentMessage(
                WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=1),
                text="It is three.",
                segment_sequence=0,
            ),
            "response-segment.json",
        ),
        (
            AudioStart(WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=2)),
            "audio-start.json",
        ),
        (
            AudioEnd(
                WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=3),
                final_audio_sequence=1,
            ),
            "audio-end.json",
        ),
        (
            StateMessage(
                WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=4),
                name=DeviceState.SPEAKING,
            ),
            "state.json",
        ),
    ],
)
def test_gateway_control_matches_golden_fixture(
    message: GatewayMessage, fixture_name: str
) -> None:
    expected = (FIXTURES / fixture_name).read_bytes().rstrip(b"\n")

    assert encode_gateway_message(message) == expected
    assert decode_gateway_message(expected) == message


def test_transcript_allows_omitted_confidence() -> None:
    frame = (
        b'{"conversation_id":"00000000-0000-4000-8000-000000000002",'
        b'"payload":{"text":"Hello"},"protocol_version":2,'
        b'"request_id":"00000000-0000-4000-8000-000000000003",'
        b'"sequence":0,"type":"transcript"}'
    )

    assert decode_gateway_message(frame) == TranscriptMessage(
        WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=0),
        text="Hello",
        confidence=None,
    )


@pytest.mark.parametrize(
    "frame",
    [
        (
            b'{"conversation_id":"00000000-0000-4000-8000-000000000002",'
            b'"payload":{"confidence":true,"text":"Hello"},'
            b'"protocol_version":2,'
            b'"request_id":"00000000-0000-4000-8000-000000000003",'
            b'"sequence":0,"type":"transcript"}'
        ),
        (
            b'{"conversation_id":"00000000-0000-4000-8000-000000000002",'
            b'"payload":{"name":"unknown"},"protocol_version":2,'
            b'"request_id":"00000000-0000-4000-8000-000000000003",'
            b'"sequence":0,"type":"state"}'
        ),
        (
            b'{"conversation_id":"00000000-0000-4000-8000-000000000002",'
            b'"payload":{"segment_sequence":0.0,"text":"Hello"},'
            b'"protocol_version":2,'
            b'"request_id":"00000000-0000-4000-8000-000000000003",'
            b'"sequence":0,"type":"response_segment"}'
        ),
    ],
)
def test_gateway_control_fails_closed(frame: bytes) -> None:
    with pytest.raises(ProtocolViolation) as raised:
        decode_gateway_message(frame)

    assert raised.value.code == "INVALID_MESSAGE"
