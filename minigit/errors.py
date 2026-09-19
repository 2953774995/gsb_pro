"""Error types for minigit."""


class MiniGitError(Exception):
    """A user-facing error. Carries the process exit code to use."""

    def __init__(self, message, exit_code=1):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
