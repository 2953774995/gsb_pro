"""LSB-first bit stream reader/writer used by DEFLATE (RFC 1951).

DEFLATE packs data elements (headers, extra bits) LSB-first: the first
bit of a value goes into the least significant free bit of the current
byte.  Huffman codes, on the other hand, are emitted starting from
their most significant bit.  This module is the single place where
that ordering lives; everything else builds on top of it.
"""


class BitWriter(object):
    """Accumulates bits LSB-first into a byte string."""

    __slots__ = ("buf", "bitbuf", "bitcount")

    def __init__(self):
        self.buf = bytearray()
        self.bitbuf = 0     # bits not yet flushed to buf
        self.bitcount = 0   # number of valid bits in bitbuf

    def write_bits(self, value, nbits):
        """Write the low ``nbits`` bits of ``value``, LSB first."""
        if nbits < 0 or value < 0 or (nbits and value >> nbits):
            raise ValueError("value %r does not fit in %d bits" % (value, nbits))
        self.bitbuf |= value << self.bitcount
        self.bitcount += nbits
        while self.bitcount >= 8:
            self.buf.append(self.bitbuf & 0xFF)
            self.bitbuf >>= 8
            self.bitcount -= 8

    def write_code(self, code, nbits):
        """Write a Huffman code, most significant bit first."""
        # Reverse the code so that write_bits (LSB-first) emits the
        # most significant bit of the code first.
        rev = 0
        c = code
        for _ in range(nbits):
            rev = (rev << 1) | (c & 1)
            c >>= 1
        self.write_bits(rev, nbits)

    def align_to_byte(self):
        """Pad with zero bits up to the next byte boundary."""
        if self.bitcount:
            self.write_bits(0, 8 - self.bitcount)

    def write_raw_bytes(self, data):
        """Append whole bytes; the writer must be byte aligned."""
        if self.bitcount:
            raise ValueError("not byte aligned")
        self.buf += data

    def getvalue(self):
        """Flush (zero-padding the final byte) and return the bytes."""
        self.align_to_byte()
        return bytes(self.buf)


class BitReader(object):
    """Reads bits LSB-first from a byte string.

    Reading past the end of the data yields zero bits; this is useful
    when peeking for Huffman codes near the end of a stream.  Valid
    DEFLATE streams never *consume* bits past the end.
    """

    __slots__ = ("data", "pos", "bitbuf", "bitcount")

    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos        # next byte index to load into bitbuf
        self.bitbuf = 0
        self.bitcount = 0

    def _fill(self, nbits):
        while self.bitcount < nbits:
            if self.pos < len(self.data):
                self.bitbuf |= self.data[self.pos] << self.bitcount
                self.pos += 1
            # past the end: zero bits are shifted in implicitly
            self.bitcount += 8

    def read_bits(self, nbits):
        """Read ``nbits`` bits LSB-first and return them as an int."""
        self._fill(nbits)
        value = self.bitbuf & ((1 << nbits) - 1)
        self.bitbuf >>= nbits
        self.bitcount -= nbits
        return value

    def peek_bits(self, nbits):
        """Return the next ``nbits`` bits without consuming them."""
        self._fill(nbits)
        return self.bitbuf & ((1 << nbits) - 1)

    def drop_bits(self, nbits):
        """Discard ``nbits`` bits (must have been peeked/filled)."""
        self.bitbuf >>= nbits
        self.bitcount -= nbits

    def align_to_byte(self):
        """Discard bits up to the next byte boundary."""
        drop = self.bitcount & 7
        self.bitbuf >>= drop
        self.bitcount -= drop

    def byte_position(self):
        """Current byte offset in the stream (only valid when aligned)."""
        return self.pos - (self.bitcount >> 3)

    def read_bytes(self, n):
        """Read ``n`` whole bytes; aligns to a byte boundary first."""
        self.align_to_byte()
        p = self.byte_position()
        chunk = self.data[p:p + n]
        if len(chunk) < n:
            raise EOFError("unexpected end of bit stream")
        self.pos = p + n
        self.bitbuf = 0
        self.bitcount = 0
        return chunk
