"""storelens: a local analysis tool for chain convenience-store
operations data, implemented with the Python standard library only."""

from .errors import StorelensError
from .engine import Engine, Result

__version__ = "1.0.0"
__all__ = ["Engine", "Result", "StorelensError", "__version__"]
