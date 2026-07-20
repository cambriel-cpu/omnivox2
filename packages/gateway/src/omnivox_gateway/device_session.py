"""In-process gateway enforcement of one device protocol session."""

from enum import StrEnum
from uuid import UUID

from omnivox_protocol import (
    AudioFrame,
    CancelRequest,
    ClientMessage,
    ProtocolLimits,
    ProtocolViolation,
    UtteranceEnd,
    UtteranceStart,
    Wake,
    Welcome,
    WireRequest,
    decode_audio_frame,
    decode_client_message,
    decode_hello,
    encode_welcome,
)


class GatewaySessionState(StrEnum):
    """Bounded gateway states for one authenticated device connection."""

    HANDSHAKE = "handshake"
    IDLE = "idle"
    AWAITING_UTTERANCE = "awaiting_utterance"
    RECEIVING_AUDIO = "receiving_audio"
    AWAITING_END = "awaiting_end"
    THINKING = "thinking"
    CLOSED = "closed"


class GatewayDeviceSession:
    """Validate handshake, request ordering, cancellation, and audio correlation."""

    def __init__(
        self,
        *,
        authenticated_device_id: str,
        session_id: UUID,
        supported_capabilities: tuple[str, ...],
        heartbeat_interval_ms: int,
        limits: ProtocolLimits,
    ) -> None:
        self._authenticated_device_id = authenticated_device_id
        self._session_id = session_id
        self._supported_capabilities = supported_capabilities
        self._heartbeat_interval_ms = heartbeat_interval_ms
        self._limits = limits
        self._state = GatewaySessionState.HANDSHAKE
        self._conversation_id: UUID | None = None
        self._request_id: UUID | None = None
        self._expected_control_sequence = 0
        self._expected_audio_sequence = 0
        self._last_audio_sequence: int | None = None
        self._cancelled_request_id: UUID | None = None

    @property
    def state(self) -> GatewaySessionState:
        """Return the current request/session state."""
        return self._state

    def accept_hello(self, frame: bytes) -> bytes:
        """Bind a valid hello to authenticated identity and return welcome."""
        self._require_state(GatewaySessionState.HANDSHAKE)
        hello = decode_hello(
            frame, max_frame_bytes=self._limits.max_control_frame_bytes
        )
        if hello.device_id != self._authenticated_device_id:
            raise ProtocolViolation(
                code="AUTHENTICATION_FAILED",
                message="device identity does not match credential",
            )
        capabilities = tuple(
            sorted(set(hello.capabilities) & set(self._supported_capabilities))
        )
        welcome = Welcome(
            session_id=self._session_id,
            capabilities=capabilities,
            heartbeat_interval_ms=self._heartbeat_interval_ms,
            limits=self._limits,
        )
        encoded = encode_welcome(welcome)
        self._state = GatewaySessionState.IDLE
        return encoded

    def receive_control(self, frame: bytes) -> ClientMessage:
        """Validate and apply one ordered client control message."""
        self._require_established()
        message = decode_client_message(
            frame,
            max_frame_bytes=self._limits.max_control_frame_bytes,
        )
        if isinstance(message, Wake):
            self._accept_wake(message)
        elif isinstance(message, UtteranceStart):
            self._accept_utterance_start(message)
        elif isinstance(message, UtteranceEnd):
            self._accept_utterance_end(message)
        elif isinstance(message, CancelRequest):
            self._accept_cancel(message)
        return message

    def receive_audio(self, frame: bytes) -> AudioFrame:
        """Validate one ordered audio frame for the active request."""
        self._require_established()
        audio = decode_audio_frame(
            frame,
            max_frame_bytes=self._limits.max_binary_frame_bytes,
        )
        if audio.request_id == self._cancelled_request_id:
            raise ProtocolViolation(
                code="REQUEST_CANCELLED",
                message="audio belongs to a cancelled request",
            )
        if self._state is not GatewaySessionState.RECEIVING_AUDIO:
            raise _invalid("audio is not valid in the current session state")
        if audio.request_id != self._request_id:
            raise _invalid("audio request id does not match active request")
        if audio.sequence != self._expected_audio_sequence:
            raise _invalid("audio sequence is stale, duplicate, or out of order")

        self._last_audio_sequence = audio.sequence
        self._expected_audio_sequence += 1
        if audio.end_of_stream:
            self._state = GatewaySessionState.AWAITING_END
        return audio

    def complete_request(self, request_id: UUID) -> None:
        """Mark a successfully generated request complete and return to idle."""
        self._require_state(GatewaySessionState.THINKING)
        if request_id != self._request_id:
            raise _invalid("completed request id does not match active request")
        self._clear_request()
        self._state = GatewaySessionState.IDLE

    def disconnect(self) -> None:
        """Close the connection without retaining resumable request state."""
        self._clear_request()
        self._state = GatewaySessionState.CLOSED

    def _accept_wake(self, message: Wake) -> None:
        self._require_state(GatewaySessionState.IDLE)
        if message.request.sequence != 0:
            raise _invalid("wake must begin at control sequence zero")
        self._conversation_id = message.request.conversation_id
        self._request_id = message.request.request_id
        self._expected_control_sequence = 1
        self._expected_audio_sequence = 0
        self._last_audio_sequence = None
        self._state = GatewaySessionState.AWAITING_UTTERANCE

    def _accept_utterance_start(self, message: UtteranceStart) -> None:
        self._require_state(GatewaySessionState.AWAITING_UTTERANCE)
        self._verify_request(message.request)
        self._expected_control_sequence += 1
        self._state = GatewaySessionState.RECEIVING_AUDIO

    def _accept_utterance_end(self, message: UtteranceEnd) -> None:
        self._require_state(GatewaySessionState.AWAITING_END)
        self._verify_request(message.request)
        if message.final_audio_sequence != self._last_audio_sequence:
            raise _invalid("utterance end does not match final audio sequence")
        self._expected_control_sequence += 1
        self._state = GatewaySessionState.THINKING

    def _accept_cancel(self, message: CancelRequest) -> None:
        if self._state not in {
            GatewaySessionState.AWAITING_UTTERANCE,
            GatewaySessionState.RECEIVING_AUDIO,
            GatewaySessionState.AWAITING_END,
            GatewaySessionState.THINKING,
        }:
            raise _invalid("cancel is not valid in the current session state")
        self._verify_request(message.request)
        self._cancelled_request_id = message.request.request_id
        self._clear_request()
        self._state = GatewaySessionState.IDLE

    def _verify_request(self, request: WireRequest) -> None:
        if (
            request.conversation_id != self._conversation_id
            or request.request_id != self._request_id
        ):
            raise _invalid("control identifiers do not match active request")
        if request.sequence != self._expected_control_sequence:
            raise _invalid("control sequence is stale, duplicate, or out of order")

    def _require_established(self) -> None:
        if self._state in {GatewaySessionState.HANDSHAKE, GatewaySessionState.CLOSED}:
            raise _invalid("device session is not established")

    def _require_state(self, expected: GatewaySessionState) -> None:
        if self._state is not expected:
            raise _invalid(f"operation requires {expected.value} state")

    def _clear_request(self) -> None:
        self._conversation_id = None
        self._request_id = None
        self._expected_control_sequence = 0
        self._expected_audio_sequence = 0
        self._last_audio_sequence = None


def _invalid(message: str) -> ProtocolViolation:
    return ProtocolViolation(code="INVALID_MESSAGE", message=message)
