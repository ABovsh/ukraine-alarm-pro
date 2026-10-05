"""Transport errors."""


class TransportError(Exception):
    """A transport failed to deliver data."""


class RateLimited(TransportError):
    """The server requested a pause before the next HTTP attempt."""

    def __init__(self, retry_after: float):
        super().__init__("HTTP rate limit")
        self.retry_after = retry_after
