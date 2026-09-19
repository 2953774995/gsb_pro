"""minimq - a minimal in-memory message queue with on-disk persistence.

Public API:
    Broker(data_dir=...)
    broker.create_topic(name, ...)
    broker.publish(topic, message)
    broker.subscribe(topic, group) -> Consumer
    consumer.poll(max_messages)
    consumer.ack(offset) / consumer.consume(offset)

Only the Python standard library is used.
"""

from .errors import MqError
from .broker import Broker
from .consumer import Consumer, Message
from .topic import Topic
from .storage import LogStorage
from .retention import RetentionPolicy

__all__ = [
    "Broker",
    "Consumer",
    "Message",
    "Topic",
    "LogStorage",
    "RetentionPolicy",
    "MqError",
]

__version__ = "0.1.0"
