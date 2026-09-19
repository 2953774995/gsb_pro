"""Custom exceptions for minimq."""


class MqError(Exception):
    """Raised for all minimq operational errors.

    Examples: unknown topic, duplicate ack, ack of an offset that was
    never delivered, oversized messages, invalid names, etc.
    """
