"""Exception types shared by minigit commands."""


class MinigitError(Exception):
    """An expected user-facing repository error."""


class UsageError(MinigitError):
    """Raised for invalid command-line usage."""
