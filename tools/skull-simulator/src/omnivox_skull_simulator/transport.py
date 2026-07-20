"""Deterministic, content-free transport fault injection."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameDelivery:
    """Content-free outcome for one attempted frame transmission."""

    index: int
    byte_count: int
    dropped: bool


class DeterministicLink:
    """Drop configured frame indexes without delay, retry, or renumbering."""

    def __init__(self, *, drop_frame_indexes: tuple[int, ...] = ()) -> None:
        if any(type(index) is not int or index < 0 for index in drop_frame_indexes):
            message = "drop frame indexes must be non-negative integers"
            raise ValueError(message)
        if len(drop_frame_indexes) != len(set(drop_frame_indexes)):
            message = "drop frame indexes must be unique"
            raise ValueError(message)
        self._drop_frame_indexes = frozenset(drop_frame_indexes)
        self._deliveries: list[FrameDelivery] = []

    @property
    def deliveries(self) -> tuple[FrameDelivery, ...]:
        """Return content-free delivery outcomes in attempted order."""
        return tuple(self._deliveries)

    def transmit(self, frame: bytes) -> bytes | None:
        """Forward one frame byte-for-byte unless its index is configured to drop."""
        if not isinstance(frame, bytes):
            message = "transport frame must be bytes"
            raise TypeError(message)
        index = len(self._deliveries)
        dropped = index in self._drop_frame_indexes
        self._deliveries.append(
            FrameDelivery(
                index=index,
                byte_count=len(frame),
                dropped=dropped,
            )
        )
        return None if dropped else frame
