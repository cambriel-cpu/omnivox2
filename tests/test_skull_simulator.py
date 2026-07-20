from pathlib import Path
from uuid import UUID

import pytest
from omnivox_protocol import Hello, decode_audio_frame, decode_hello
from omnivox_skull_simulator import SimulatorState, SimulatorStateError, SkullSimulator

FIXTURES = Path(__file__).parent / "fixtures" / "protocol"
REQUEST_ID = UUID("00000000-0000-4000-8000-000000000003")


def simulator() -> SkullSimulator:
    return SkullSimulator(
        device_id="servo-skull-primary",
        client_version="test-build",
        capabilities=("barge-in", "opus-input", "opus-output"),
    )


def assert_state(skull: SkullSimulator, expected: SimulatorState) -> None:
    assert skull.state is expected


def test_simulator_runs_handshake_and_sequenced_audio_lifecycle() -> None:
    skull = simulator()

    hello_frame = skull.connect()

    assert_state(skull, SimulatorState.CONNECTING)
    assert decode_hello(hello_frame) == Hello(
        device_id="servo-skull-primary",
        client_version="test-build",
        capabilities=("barge-in", "opus-input", "opus-output"),
    )

    skull.accept_welcome((FIXTURES / "welcome.json").read_bytes().rstrip(b"\n"))
    assert_state(skull, SimulatorState.IDLE)

    skull.begin_utterance(REQUEST_ID)
    first = decode_audio_frame(skull.audio(b"first"))
    final = decode_audio_frame(skull.audio(b"final", end_of_stream=True))

    assert first.request_id == REQUEST_ID
    assert first.sequence == 0
    assert first.end_of_stream is False
    assert final.request_id == REQUEST_ID
    assert final.sequence == 1
    assert final.end_of_stream is True
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
