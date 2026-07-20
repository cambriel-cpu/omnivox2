"""Deterministic skull-side protocol state machine."""

from enum import StrEnum
from uuid import UUID

from omnivox_protocol import (
    AudioCodec,
    AudioFrame,
    CancelReason,
    CancelRequest,
    Hello,
    ProtocolLimits,
    UtteranceEnd,
    UtteranceStart,
    Wake,
    Welcome,
    WireRequest,
    decode_welcome,
    encode_audio_frame,
    encode_client_message,
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
        self._conversation_id: UUID | None = None
        self._control_sequence = 0
        self._audio_sequence = 0
        self._capturing = False
        self._audio_complete = False

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

    def wake(self, conversation_id: UUID, request_id: UUID) -> bytes:
        """Emit a wake control frame and enter listening state."""
        self._require_state(SimulatorState.IDLE)
        if self._welcome is None or "opus-input" not in self._welcome.capabilities:
            message = "opus input capability was not negotiated"
            raise SimulatorStateError(message)
        self._conversation_id = conversation_id
        self._request_id = request_id
        self._control_sequence = 0
        self._audio_sequence = 0
        self._capturing = False
        self._audio_complete = False
        frame = encode_client_message(Wake(self._wire_request()))
        self._control_sequence += 1
        self._state = SimulatorState.LISTENING
        return frame

    def begin_utterance(self) -> bytes:
        """Emit an utterance-start frame and enable simulated capture."""
        self._require_state(SimulatorState.LISTENING)
        if self._capturing or self._audio_complete:
            message = "utterance capture has already started"
            raise SimulatorStateError(message)
        frame = encode_client_message(UtteranceStart(self._wire_request()))
        self._control_sequence += 1
        self._capturing = True
        return frame

    def audio(self, payload: bytes, *, end_of_stream: bool = False) -> bytes:
        """Encode the next request-correlated audio frame."""
        self._require_state(SimulatorState.LISTENING)
        if not self._capturing:
            message = "audio requires active utterance capture"
            raise SimulatorStateError(message)
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
            self._capturing = False
            self._audio_complete = True
        return frame

    def end_utterance(self) -> bytes:
        """Emit utterance-end after the final binary audio frame."""
        self._require_state(SimulatorState.LISTENING)
        if not self._audio_complete:
            message = "utterance end requires final audio"
            raise SimulatorStateError(message)
        frame = encode_client_message(
            UtteranceEnd(
                self._wire_request(),
                final_audio_sequence=self._audio_sequence - 1,
            )
        )
        self._control_sequence += 1
        self._state = SimulatorState.THINKING
        return frame

    def cancel(self, reason: CancelReason) -> bytes:
        """Emit cancellation for a live request and return to idle."""
        if self._state not in {SimulatorState.LISTENING, SimulatorState.THINKING}:
            message = "cancel requires listening or thinking state"
            raise SimulatorStateError(message)
        frame = encode_client_message(CancelRequest(self._wire_request(), reason))
        self._control_sequence += 1
        self._capturing = False
        self._audio_complete = False
        self._state = SimulatorState.IDLE
        return frame

    def _wire_request(self) -> WireRequest:
        if self._conversation_id is None or self._request_id is None:
            message = "active request identifiers are missing"
            raise SimulatorStateError(message)
        return WireRequest(
            conversation_id=self._conversation_id,
            request_id=self._request_id,
            sequence=self._control_sequence,
        )

    def _require_state(self, expected: SimulatorState) -> None:
        if self._state is not expected:
            message = f"operation requires {expected.value} state"
            raise SimulatorStateError(message)
