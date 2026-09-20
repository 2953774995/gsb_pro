"""Exceptions used across cfgvault.

The command-line layer turns :class:`CfgvaultError` instances into a readable
message plus a non-zero exit status.
"""


class CfgvaultError(Exception):
    """Base class for expected user-facing errors."""


class NotARepositoryError(CfgvaultError):
    pass


class InvalidObjectError(CfgvaultError):
    pass


class InvalidReferenceError(CfgvaultError):
    pass


class InvalidStateError(CfgvaultError):
    pass


class InvalidArgumentError(CfgvaultError):
    pass
