"""Exceptions shared by broker modules."""


class MinibrokerError(Exception):
    """Base class for expected broker-side errors."""


class BrokerError(MinibrokerError):
    """An error that should be returned to the connected client."""


class QueueFullError(BrokerError):
    """Raised when a bounded subscriber queue cannot accept a message."""


class PersistenceError(MinibrokerError):
    """Raised when the append-only file cannot be read or written safely."""
