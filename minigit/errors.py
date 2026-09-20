"""User-facing errors for minigit."""


class MiniGitError(Exception):
    """An error that should be reported to the user with a non-zero exit code."""
