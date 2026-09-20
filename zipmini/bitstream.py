"""Little-endian bit primitives used by raw DEFLATE.

DEFLATE stores the bit stream LSB first inside each byte.  Huffman codes, in
contrast, are described MSB first.  Huffman code values are therefore bit
reversed before being handed to :class:`BitWriter`; :class:`BitReader` peeks
enough LSB-ordered bits for a reversed-code lookup table.
"""

from __future__ import annotations


class BitWriter:
    __slots__ = ("buf", "current", "nbits")

    def __init__(self) -> None:
        self.buf = bytearray()
        self.current = 0
        self.nbits = 0

    def write(self, value: int, width: int) -> None:
        if width < 0:
            raise ValueError("width must be non-negative")
        if width == 0:
            return
        if value < 0 or value >= (1 << width):
            raise ValueError(f"value {value} does not fit in {width} bits")
        self.current |= value << self.nbits
        self.nbits += width
        while self.nbits >= 8:
            self.buf.append(self.current & 0xFF)
            self.current >>= 8
            self.nbits -= 8

    def align(self) -> None:
        """Pad to the next byte with zero bits."""
        if self.nbits:
            self.buf.append(self.current & 0xFF)
            self.current = 0
            self.nbits = 0

    def finish(self) -> bytes:
        self.align()
        return bytes(self.buf)

    def byte_length(self) -> int:
        return len(self.buf) + (1 if self.nbits else 0)

    @property
    def aligned(self) -> bool:
        return self.nbits == 0


class BitReader:
    __slots__ = ("data", "pos", "bitbuf", "bitcount")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.bitbuf = 0
        self.bitcount = 0

    def _ensure(self, count: int) -> None:
        while self.bitcount < count:
            if self.pos >= len(self.data):
                raise EOFError("unexpected end of DEFLATE bit stream")
            self.bitbuf |= self.data[self.pos] << self.bitcount
            self.bitcount += 8
            self.pos += 1

    def read_bits(self, count: int) -> int:
        if count < 0:
            raise ValueError("count must be non-negative")
        if count == 0:
            return 0
        self._ensure(count)
        value = self.bitbuf & ((1 << count) - 1)
        self.bitbuf >>= count
        self.bitcount -= count
        return value

    def peek_bits(self, count: int) -> int:
        """Peek LSB-first bits, zero-padding the final partial byte.

        Canonical table lookups fetch the maximum code length.  RFC 1951
        permits padding after the final block, so missing final bits are
        treated as zero; actual symbols are still distinguished by the
        canonical table unless the stream is truncated before their code.
        """
        try:
            self._ensure(count)
        except EOFError:
            if self.bitcount == 0:
                raise
        return self.bitbuf & ((1 << count) - 1)

    def drop(self, count: int) -> None:
        if count > self.bitcount:
            raise ValueError("cannot drop bits which have not been peeked")
        self.bitbuf >>= count
        self.bitcount -= count

    def align(self) -> None:
        # bitcount can contain whole bytes already consumed from ``data``.
        # Move the read position back to the byte containing the next unread
        # bit; zero padding inside that byte is discarded by resetting state.
        if self.bitcount:
            self.pos -= self.bitcount // 8
        self.bitbuf = 0
        self.bitcount = 0

    @property
    def aligned(self) -> bool:
        return self.bitcount == 0

    def at_end(self) -> bool:
        return self.pos >= len(self.data) and self.bitcount == 0

    @property
    def available_bits(self) -> int:
        return self.bitcount + 8 * (len(self.data) - self.pos)
