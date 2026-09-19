"""Exception hierarchy shared by the broker server and the client SDK."""


class BrokerError(Exception):
    """Base class for every minibroker error."""


class ProtocolError(BrokerError):
    """Raised when a peer sends bytes that violate the wire protocol."""


class ServerError(BrokerError):
    """An ``ERR ...`` reply returned by the broker server."""


class BrokerShutdown(BrokerError):
    """Raised (or delivered as ``BYE``) when the broker shuts down."""
