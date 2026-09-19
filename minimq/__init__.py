"""minimq: a mini in-memory message queue with persistence.

Standard library only.
"""

from .broker import Broker, Consumer, Message
from .errors import MqError

__all__ = ["Broker", "Consumer", "Message", "MqError"]
__version__ = "0.1.0"
