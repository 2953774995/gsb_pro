"""Custom exception hierarchy for minimq."""


class MqError(Exception):
    """Base class for every minimq error.

    All expected error conditions (unknown topic, duplicate ack,
    oversized message, ...) raise ``MqError`` with a descriptive message.
    """


class TopicNotFoundError(MqError):
    """Raised when an operation references a topic that does not exist."""


class TopicExistsError(MqError):
    """Raised when creating a topic that is already present."""


class ConsumerGroupError(MqError):
    """Raised for consumer group / ack related problems."""


class MessageTooLargeError(MqError):
    """Raised when a published message exceeds the configured size limit."""
