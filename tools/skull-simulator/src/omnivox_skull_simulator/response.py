"""Gateway-response validation for the hardware-independent skull simulator."""

from enum import StrEnum
from uuid import UUID

from omnivox_protocol import (
    AudioEnd,
    AudioFrame,
    AudioStart,
    ErrorMessage,
    GatewayMessage,
    ProtocolLimits,
    ProtocolViolation,
    ResponseSegmentMessage,
    TranscriptMessage,
    WireRequest,
    decode_audio_frame,
    decode_error_message,
    decode_gateway_message,
)


class GatewayResponseState(StrEnum):
    """Progress of one simulated gateway response."""

    WAITING = "waiting"
    SPEAKING = "speaking"
    COMPLETE = "complete"
    FAILED = "failed"


class GatewayResponseSession:
    """Validate gateway control and audio correlation for one request."""

    def __init__(
        self,
        *,
        conversation_id: UUID,
        request_id: UUID,
        limits: ProtocolLimits,
    ) -> None:
        self._conversation_id = conversation_id
        self._request_id = request_id
        self._limits = limits
        self._state = GatewayResponseState.WAITING
        self._expected_control_sequence = 0
        self._expected_audio_sequence = 0
        self._last_audio_sequence: int | None = None
        self._audio_complete = False

    @property
    def state(self) -> GatewayResponseState:
        """Return current response progress."""
        return self._state

    def receive_control(self, frame: bytes) -> GatewayMessage:
        """Validate one ordered, request-correlated gateway control frame."""
        self._require_live()
        message = decode_gateway_message(
            frame,
            max_frame_bytes=self._limits.max_control_frame_bytes,
        )
        self._verify_request(message.request)
        if isinstance(message, TranscriptMessage):
            if self._state is not GatewayResponseState.WAITING:
                raise _invalid("transcript is not valid after audio starts")
        elif isinstance(message, ResponseSegmentMessage):
            pass
        elif isinstance(message, AudioStart):
            if self._state is not GatewayResponseState.WAITING:
                raise _invalid("audio start is duplicate or out of order")
            self._state = GatewayResponseState.SPEAKING
        elif isinstance(message, AudioEnd):
            self._accept_audio_end(message)
        self._expected_control_sequence += 1
        return message

    def receive_audio(self, frame: bytes) -> AudioFrame:
        """Validate one ordered gateway audio frame."""
        if self._state is not GatewayResponseState.SPEAKING:
            raise _invalid("gateway audio is not valid before audio start")
        if self._audio_complete:
            raise _invalid("gateway audio arrived after end of stream")
        audio = decode_audio_frame(
            frame,
            max_frame_bytes=self._limits.max_binary_frame_bytes,
        )
        if audio.request_id != self._request_id:
            raise _invalid("gateway audio request id does not match active request")
        if audio.sequence != self._expected_audio_sequence:
            message = "gateway audio sequence is stale, duplicate, or out of order"
            raise _invalid(message)
        self._last_audio_sequence = audio.sequence
        self._expected_audio_sequence += 1
        self._audio_complete = audio.end_of_stream
        return audio

    def receive_error(self, frame: bytes) -> ErrorMessage:
        """Validate one correlated terminal gateway error."""
        self._require_live()
        error = decode_error_message(
            frame,
            max_frame_bytes=self._limits.max_control_frame_bytes,
        )
        self._verify_request(error.request)
        self._expected_control_sequence += 1
        self._state = GatewayResponseState.FAILED
        return error

    def _accept_audio_end(self, message: AudioEnd) -> None:
        if self._state is not GatewayResponseState.SPEAKING:
            raise _invalid("audio end is not valid before audio start")
        if not self._audio_complete:
            raise _invalid("audio end requires a final audio frame")
        if message.final_audio_sequence != self._last_audio_sequence:
            raise _invalid("audio end does not match final audio sequence")
        self._state = GatewayResponseState.COMPLETE

    def _verify_request(self, request: WireRequest) -> None:
        if (
            request.conversation_id != self._conversation_id
            or request.request_id != self._request_id
        ):
            raise _invalid("gateway control identifiers do not match active request")
        if request.sequence != self._expected_control_sequence:
            message = "gateway control sequence is stale, duplicate, or out of order"
            raise _invalid(message)

    def _require_live(self) -> None:
        if self._state in {
            GatewayResponseState.COMPLETE,
            GatewayResponseState.FAILED,
        }:
            raise _invalid("gateway response is already terminal")


def _invalid(message: str) -> ProtocolViolation:
    return ProtocolViolation(code="INVALID_MESSAGE", message=message)
