"""zipmini: a minimal zip tool with a from-scratch DEFLATE codec."""

from . import bitstream, huffman, lz77, deflate, zipcontainer  # noqa: F401

__version__ = "0.1.0"
