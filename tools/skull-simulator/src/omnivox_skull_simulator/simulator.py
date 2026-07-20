"""Deterministic skull-side protocol state machine."""

from enum import StrEnum
from uuid import UUID

from omnivox_protocol import (
    AudioCodec,
    AudioFrame,
    Hello,
    ProtocolLimits,
    Welcome,
    decode_welcome,
    encode_audio_frame,
    encode_hello,
)


class SimulatorState(StrEnum):
    """Hardware-independent subset of the skull state machine."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"


class SimulatorStateError(RuntimeError):
    """An operation attempted outside its valid simulator state."""


class SkullSimulator:
    """Produce deterministic skull protocol frames without physical hardware."""

    def __init__(
        self,
        *,
        device_id: str,
        client_version: str,
        capabilities: tuple[str, ...],
    ) -> None:
        self._hello = Hello(
            device_id=device_id,
            client_version=client_version,
            capabilities=capabilities,
        )
        self._state = SimulatorState.DISCONNECTED
        self._welcome: Welcome | None = None
        self._request_id: UUID | None = None
        self._audio_sequence = 0

    @property
    def state(self) -> SimulatorState:
        """Return the current deterministic simulator state."""
        return self._state

    @property
    def limits(self) -> ProtocolLimits | None:
        """Return negotiated limits after a successful welcome."""
        return None if self._welcome is None else self._welcome.limits

    def connect(self) -> bytes:
        """Begin a device session and return its canonical hello frame."""
        self._require_state(SimulatorState.DISCONNECTED)
        frame = encode_hello(self._hello)
        self._state = SimulatorState.CONNECTING
        return frame

    def accept_welcome(self, frame: bytes) -> None:
        """Accept a valid welcome whose capabilities were offered by the skull."""
        self._require_state(SimulatorState.CONNECTING)
        welcome = decode_welcome(frame)
        unnegotiated = set(welcome.capabilities) - set(self._hello.capabilities)
        if unnegotiated:
            message = "gateway selected an unoffered capability"
            raise SimulatorStateError(message)
        self._welcome = welcome
        self._state = SimulatorState.IDLE

    def begin_utterance(self, request_id: UUID) -> None:
        """Enter listening state for a new request."""
        self._require_state(SimulatorState.IDLE)
        if self._welcome is None or "opus-input" not in self._welcome.capabilities:
            message = "opus input capability was not negotiated"
            raise SimulatorStateError(message)
        self._request_id = request_id
        self._audio_sequence = 0
        self._state = SimulatorState.LISTENING

    def audio(self, payload: bytes, *, end_of_stream: bool = False) -> bytes:
        """Encode the next request-correlated audio frame."""
        self._require_state(SimulatorState.LISTENING)
        if self._welcome is None or self._request_id is None:
            message = "listening state is missing negotiated request data"
            raise SimulatorStateError(message)
        frame = encode_audio_frame(
            AudioFrame(
                request_id=self._request_id,
                sequence=self._audio_sequence,
                payload=payload,
                codec=AudioCodec.OPUS,
                end_of_stream=end_of_stream,
            ),
            max_frame_bytes=self._welcome.limits.max_binary_frame_bytes,
        )
        self._audio_sequence += 1
        if end_of_stream:
            self._state = SimulatorState.THINKING
        return frame

    def _require_state(self, expected: SimulatorState) -> None:
        if self._state is not expected:
            message = f"operation requires {expected.value} state"
            raise SimulatorStateError(message)
