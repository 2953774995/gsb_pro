"""Custom exceptions for tinytpl."""


class TplError(Exception):
    """Base error raised for all tinytpl failures.

    Carries an optional template name and line number so error messages
    can point at the exact source of the problem.
    """

    def __init__(self, message, line=None, template=None):
        self.message = message
        self.line = line
        self.template = template
        parts = []
        if template is not None:
            parts.append(str(template))
        if line is not None:
            parts.append("line %s" % line)
        if parts:
            full = "%s: %s" % (": ".join(parts), message)
        else:
            full = message
        super().__init__(full)


class TemplateNotFound(TplError):
    """Raised when a loader cannot find a requested template."""

    def __init__(self, name):
        super().__init__("template not found: %r" % name)
        self.name = name
