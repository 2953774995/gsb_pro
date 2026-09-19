"""Exceptions used across minigit.

Every user-facing failure raises :class:`MiniGitError` (or a subclass);
the CLI layer catches it, prints a clear message and exits non-zero.
"""


class MiniGitError(Exception):
    """Base class for all minigit errors."""


class NotARepositoryError(MiniGitError):
    """Raised when a command is used outside a ``.minigit`` repository."""


class UnknownCommandError(MiniGitError):
    """Raised for an unknown sub-command."""


class UsageError(MiniGitError):
    """Raised when required arguments are missing or invalid."""


class ObjectNotFoundError(MiniGitError):
    """Raised when a commit/object reference cannot be resolved."""


class RefNotFoundError(MiniGitError):
    """Raised when a branch reference does not exist."""


class PathError(MiniGitError):
    """Raised for invalid/unsafe file paths."""
