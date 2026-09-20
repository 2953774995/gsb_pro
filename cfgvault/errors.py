"""Exception types used by cfgvault."""


class CfgvaultError(Exception):
    """Base class for user-facing cfgvault errors."""


class NotInitializedError(CfgvaultError):
    """Raised when a command is run outside a cfgvault repository."""


class InvalidReferenceError(CfgvaultError):
    """Raised when a snapshot, branch, or object reference is invalid."""


class IgnoredPathError(CfgvaultError):
    """Raised when an explicitly requested path cannot be used."""
