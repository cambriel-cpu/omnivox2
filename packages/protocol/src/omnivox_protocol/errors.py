"""Protocol-level failures safe to translate into wire errors."""


class ProtocolViolation(Exception):
    """A malformed, unsupported, or oversized device frame."""

    code: str

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
