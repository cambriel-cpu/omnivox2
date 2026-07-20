from pathlib import Path
from uuid import UUID

import pytest
from omnivox_protocol import (
    AudioCodec,
    AudioEnd,
    AudioFrame,
    AudioStart,
    CancelReason,
    CancelRequest,
    ErrorCode,
    ErrorMessage,
    Ping,
    Pong,
    ProtocolViolation,
    ResponseSegmentMessage,
    TranscriptMessage,
    UtteranceEnd,
    UtteranceStart,
    Wake,
    WireRequest,
    decode_audio_frame,
    decode_client_message,
    decode_heartbeat,
    decode_hello,
    encode_audio_frame,
    encode_error_message,
)
from omnivox_skull_simulator import SimulatorState, SimulatorStateError, SkullSimulator

FIXTURES = Path(__file__).parent / "fixtures" / "protocol"
REQUEST_ID = UUID("00000000-0000-4000-8000-000000000003")
CONVERSATION_ID = UUID("00000000-0000-4000-8000-000000000002")
FINAL_CONTROL_SEQUENCE = 2
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")


def simulator() -> SkullSimulator:
    return SkullSimulator(
        device_id="servo-skull-primary",
        client_version="test-build",
        capabilities=("barge-in", "opus-input", "opus-output"),
    )


def assert_state(skull: SkullSimulator, expected: SimulatorState) -> None:
    assert skull.state is expected


def thinking_simulator() -> SkullSimulator:
    skull = simulator()
    skull.connect()
    skull.accept_welcome((FIXTURES / "welcome.json").read_bytes().rstrip(b"\n"))
    skull.wake(CONVERSATION_ID, REQUEST_ID)
    skull.begin_utterance()
    skull.audio(b"input", end_of_stream=True)
    skull.end_utterance()
    return skull


def test_simulator_runs_handshake_and_sequenced_audio_lifecycle() -> None:
    skull = simulator()

    hello_frame = skull.connect()

    assert_state(skull, SimulatorState.CONNECTING)
    assert decode_hello(hello_frame).device_id == "servo-skull-primary"

    skull.accept_welcome((FIXTURES / "welcome.json").read_bytes().rstrip(b"\n"))
    assert_state(skull, SimulatorState.IDLE)

    wake = decode_client_message(skull.wake(CONVERSATION_ID, REQUEST_ID))
    start = decode_client_message(skull.begin_utterance())
    first = decode_audio_frame(skull.audio(b"first"))
    final = decode_audio_frame(skull.audio(b"final", end_of_stream=True))
    end = decode_client_message(skull.end_utterance())

    assert isinstance(wake, Wake)
    assert wake.request.sequence == 0
    assert isinstance(start, UtteranceStart)
    assert start.request.sequence == 1
    assert first.request_id == REQUEST_ID
    assert first.sequence == 0
    assert first.end_of_stream is False
    assert final.request_id == REQUEST_ID
    assert final.sequence == 1
    assert final.end_of_stream is True
    assert isinstance(end, UtteranceEnd)
    assert end.request.sequence == FINAL_CONTROL_SEQUENCE
    assert end.final_audio_sequence == 1
    assert_state(skull, SimulatorState.THINKING)


def test_simulator_rejects_audio_outside_listening_state() -> None:
    skull = simulator()

    with pytest.raises(SimulatorStateError, match="listening"):
        skull.audio(b"ambient audio")


def test_simulator_rejects_unnegotiated_server_capability() -> None:
    skull = SkullSimulator(
        device_id="servo-skull-primary",
        client_version="test-build",
        capabilities=("opus-input",),
    )
    skull.connect()

    with pytest.raises(SimulatorStateError, match="capability"):
        skull.accept_welcome((FIXTURES / "welcome.json").read_bytes().rstrip(b"\n"))


def test_simulator_emits_cancel_and_returns_to_idle() -> None:
    skull = simulator()
    skull.connect()
    skull.accept_welcome((FIXTURES / "welcome.json").read_bytes().rstrip(b"\n"))
    skull.wake(CONVERSATION_ID, REQUEST_ID)

    message = decode_client_message(skull.cancel(CancelReason.USER))

    assert isinstance(message, CancelRequest)
    assert message.reason is CancelReason.USER
    assert message.request.sequence == 1
    assert_state(skull, SimulatorState.IDLE)


def test_simulator_consumes_ordered_gateway_response() -> None:
    skull = thinking_simulator()

    transcript = skull.receive_gateway_control(
        (FIXTURES / "transcript.json").read_bytes().rstrip(b"\n")
    )
    segment = skull.receive_gateway_control(
        (FIXTURES / "response-segment.json").read_bytes().rstrip(b"\n")
    )
    audio_start = skull.receive_gateway_control(
        (FIXTURES / "audio-start.json").read_bytes().rstrip(b"\n")
    )

    assert isinstance(transcript, TranscriptMessage)
    assert isinstance(segment, ResponseSegmentMessage)
    assert isinstance(audio_start, AudioStart)
    assert_state(skull, SimulatorState.SPEAKING)

    first = skull.receive_gateway_audio(
        encode_audio_frame(
            AudioFrame(
                request_id=REQUEST_ID,
                sequence=0,
                payload=b"first output",
                codec=AudioCodec.OPUS,
            )
        )
    )
    final = skull.receive_gateway_audio(
        encode_audio_frame(
            AudioFrame(
                request_id=REQUEST_ID,
                sequence=1,
                payload=b"final output",
                codec=AudioCodec.OPUS,
                end_of_stream=True,
            )
        )
    )
    audio_end = skull.receive_gateway_control(
        (FIXTURES / "audio-end.json").read_bytes().rstrip(b"\n")
    )

    assert first.sequence == 0
    assert final.end_of_stream is True
    assert isinstance(audio_end, AudioEnd)
    assert_state(skull, SimulatorState.IDLE)


def test_simulator_rejects_out_of_order_gateway_control() -> None:
    skull = thinking_simulator()

    with pytest.raises(ProtocolViolation, match="sequence") as raised:
        skull.receive_gateway_control(
            (FIXTURES / "response-segment.json").read_bytes().rstrip(b"\n")
        )

    assert raised.value.code == "INVALID_MESSAGE"


def test_simulator_rejects_gateway_audio_for_another_request() -> None:
    skull = thinking_simulator()
    skull.receive_gateway_control(
        (FIXTURES / "transcript.json").read_bytes().rstrip(b"\n")
    )
    skull.receive_gateway_control(
        (FIXTURES / "response-segment.json").read_bytes().rstrip(b"\n")
    )
    skull.receive_gateway_control(
        (FIXTURES / "audio-start.json").read_bytes().rstrip(b"\n")
    )
    stale = encode_audio_frame(
        AudioFrame(
            request_id=TRACE_ID,
            sequence=0,
            payload=b"stale output",
            codec=AudioCodec.OPUS,
        )
    )

    with pytest.raises(ProtocolViolation, match="request"):
        skull.receive_gateway_audio(stale)


def test_simulator_replies_to_ping_without_changing_state() -> None:
    skull = simulator()
    skull.connect()
    skull.accept_welcome((FIXTURES / "welcome.json").read_bytes().rstrip(b"\n"))

    response = skull.reply_to_heartbeat(
        (FIXTURES / "ping.json").read_bytes().rstrip(b"\n")
    )

    assert decode_heartbeat(response) == Pong(nonce="heartbeat-0001")
    assert decode_heartbeat(
        (FIXTURES / "ping.json").read_bytes().rstrip(b"\n")
    ) == Ping(nonce="heartbeat-0001")
    assert_state(skull, SimulatorState.IDLE)


def test_simulator_accepts_correlated_terminal_error() -> None:
    skull = thinking_simulator()
    error = ErrorMessage(
        request=WireRequest(CONVERSATION_ID, REQUEST_ID, sequence=0),
        code=ErrorCode.STT_UNAVAILABLE,
        message="Speech recognition is temporarily unavailable.",
        retryable=True,
        trace_id=TRACE_ID,
    )

    received = skull.receive_gateway_error(encode_error_message(error))

    assert received == error
    assert_state(skull, SimulatorState.UNAVAILABLE)
