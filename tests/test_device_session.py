from uuid import UUID

import pytest
from omnivox_gateway.device_session import GatewayDeviceSession, GatewaySessionState
from omnivox_protocol import (
    AudioCodec,
    AudioFrame,
    CancelReason,
    ProtocolLimits,
    ProtocolViolation,
    encode_audio_frame,
)
from omnivox_skull_simulator import SimulatorState, SkullSimulator

DEVICE_ID = "servo-skull-primary"
CONVERSATION_ID = UUID("00000000-0000-4000-8000-000000000002")
REQUEST_ID = UUID("00000000-0000-4000-8000-000000000003")
SESSION_ID = UUID("00000000-0000-4000-8000-000000000001")
NEXT_SESSION_ID = UUID("00000000-0000-4000-8000-000000000004")
LIMITS = ProtocolLimits(
    max_binary_frame_bytes=65_536,
    max_control_frame_bytes=16_384,
    max_queue_depth=32,
    max_utterance_ms=30_000,
)
CAPABILITIES = ("barge-in", "opus-input", "opus-output")


def skull() -> SkullSimulator:
    return SkullSimulator(
        device_id=DEVICE_ID,
        client_version="test-build",
        capabilities=CAPABILITIES,
    )


def gateway(session_id: UUID = SESSION_ID) -> GatewayDeviceSession:
    return GatewayDeviceSession(
        authenticated_device_id=DEVICE_ID,
        session_id=session_id,
        supported_capabilities=CAPABILITIES,
        heartbeat_interval_ms=15_000,
        limits=LIMITS,
    )


def connect(skull_client: SkullSimulator, session: GatewayDeviceSession) -> None:
    skull_client.accept_welcome(session.accept_hello(skull_client.connect()))


def assert_gateway_state(
    session: GatewayDeviceSession, expected: GatewaySessionState
) -> None:
    assert session.state is expected


def test_skull_and_gateway_complete_ordered_utterance() -> None:
    skull_client = skull()
    session = gateway()
    connect(skull_client, session)

    session.receive_control(skull_client.wake(CONVERSATION_ID, REQUEST_ID))
    session.receive_control(skull_client.begin_utterance())
    session.receive_audio(skull_client.audio(b"first"))
    session.receive_audio(skull_client.audio(b"final", end_of_stream=True))
    session.receive_control(skull_client.end_utterance())

    assert_gateway_state(session, GatewaySessionState.THINKING)
    session.complete_request(REQUEST_ID)
    assert_gateway_state(session, GatewaySessionState.IDLE)


def test_gateway_rejects_out_of_order_audio() -> None:
    skull_client = skull()
    session = gateway()
    connect(skull_client, session)
    session.receive_control(skull_client.wake(CONVERSATION_ID, REQUEST_ID))
    session.receive_control(skull_client.begin_utterance())
    out_of_order = encode_audio_frame(
        AudioFrame(
            request_id=REQUEST_ID,
            sequence=1,
            payload=b"skipped zero",
            codec=AudioCodec.OPUS,
        )
    )

    with pytest.raises(ProtocolViolation) as raised:
        session.receive_audio(out_of_order)

    assert raised.value.code == "INVALID_MESSAGE"


def test_gateway_discards_late_audio_after_cancel() -> None:
    skull_client = skull()
    session = gateway()
    connect(skull_client, session)
    session.receive_control(skull_client.wake(CONVERSATION_ID, REQUEST_ID))
    session.receive_control(skull_client.begin_utterance())
    session.receive_control(skull_client.cancel(CancelReason.USER))
    late = encode_audio_frame(
        AudioFrame(
            request_id=REQUEST_ID,
            sequence=0,
            payload=b"late",
            codec=AudioCodec.OPUS,
        )
    )

    with pytest.raises(ProtocolViolation) as raised:
        session.receive_audio(late)

    assert raised.value.code == "REQUEST_CANCELLED"
    assert_gateway_state(session, GatewaySessionState.IDLE)


def test_reconnect_does_not_resume_interrupted_request() -> None:
    skull_client = skull()
    first_session = gateway()
    connect(skull_client, first_session)
    first_session.receive_control(skull_client.wake(CONVERSATION_ID, REQUEST_ID))
    first_session.receive_control(skull_client.begin_utterance())
    stale = skull_client.audio(b"from old session")

    first_session.disconnect()
    skull_client.disconnect()
    next_session = gateway(NEXT_SESSION_ID)
    connect(skull_client, next_session)

    with pytest.raises(ProtocolViolation) as raised:
        next_session.receive_audio(stale)

    assert raised.value.code == "INVALID_MESSAGE"
    assert_gateway_state(next_session, GatewaySessionState.IDLE)
    assert skull_client.state is SimulatorState.IDLE


def test_gateway_binds_hello_to_authenticated_device() -> None:
    other_skull = SkullSimulator(
        device_id="different-skull",
        client_version="test-build",
        capabilities=CAPABILITIES,
    )

    with pytest.raises(ProtocolViolation) as raised:
        gateway().accept_hello(other_skull.connect())

    assert raised.value.code == "AUTHENTICATION_FAILED"
