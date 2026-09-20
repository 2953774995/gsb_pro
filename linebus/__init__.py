"""Linebus: a standard-library TCP quality-inspection event bus."""

from .broker import Broker, BrokerError, BrokerShutdown
from .client import (
    LinebusClient,
    LinebusDisconnected,
    LinebusError,
    LinebusProtocolError,
    LinebusServerError,
    Message,
)
from .protocol import CommandTooLargeError, Frame, ProtocolError
from .storage import Event

__all__ = [
    "Broker",
    "BrokerError",
    "BrokerShutdown",
    "CommandTooLargeError",
    "Event",
    "Frame",
    "LinebusClient",
    "LinebusDisconnected",
    "LinebusError",
    "LinebusProtocolError",
    "LinebusServer",
    "LinebusServerError",
    "Message",
    "ProtocolError",
]

__version__ = "1.0.0"


def __getattr__(name):
    if name == "LinebusServer":
        from .server import LinebusServer

        return LinebusServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
