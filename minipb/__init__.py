"""minipb: 一个迷你版 Protocol Buffers。

用法:
    minipb compile schema.mpb -o schema_pb.py
"""

from .errors import DecodeError, EncodeError, SchemaError

__all__ = ["DecodeError", "EncodeError", "SchemaError"]
__version__ = "0.1.0"
