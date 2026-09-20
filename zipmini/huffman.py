"""Huffman coding for DEFLATE: length-limited code construction,
canonical code assignment (RFC 1951 section 3.2.2) and decoding.
"""

from .bitstream import BitReader

MAX_BITS = 15          # DEFLATE limit for literal/length and distance codes
MAX_CL_BITS = 7        # DEFLATE limit for the code-length alphabet

# Order in which code-length code lengths are stored in a dynamic block.
CL_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)


def build_code_lengths(freqs, max_bits=MAX_BITS):
    """Compute optimal Huffman code lengths limited to ``max_bits``.

    Uses the package-merge algorithm, which produces an optimal
    length-limited prefix code.  Returns a list parallel to ``freqs``;
    unused symbols get length 0.  A single used symbol gets length 1
    (the DEFLATE one-code special case).
    """
    lengths = [0] * len(freqs)
    syms = sorted((f, s) for s, f in enumerate(freqs) if f > 0)
    if not syms:
        return lengths
    if len(syms) == 1:
        lengths[syms[0][1]] = 1
        return lengths

    # Package-merge.  Each item is (weight, tuple-of-symbol-indices).
    leaves = [(f, (s,)) for f, s in syms]
    prev = leaves
    for _ in range(max_bits - 1):
        packaged = []
        for k in range(0, len(prev) - 1, 2):
            w = prev[k][0] + prev[k + 1][0]
            packaged.append((w, prev[k][1] + prev[k + 1][1]))
        prev = sorted(leaves + packaged)
    # The code length of a symbol is the number of times it appears in
    # the first 2n-2 items of the final list.
    for _w, group in prev[:2 * len(syms) - 2]:
        for s in group:
            lengths[s] += 1
    return lengths


def ensure_two_codes(lengths):
    """Force at least two non-zero code lengths (in place).

    Some inflaters (notably old PKZIP-derived ones) misbehave on
    alphabets with zero or one code, so emit at least two 1-bit codes.
    """
    nz = [i for i, l in enumerate(lengths) if l]
    if len(nz) >= 2:
        return
    if len(nz) == 1:
        lengths[nz[0]] = 1
        lengths[1 if nz[0] == 0 else 0] = 1
    else:
        lengths[0] = 1
        lengths[1] = 1


def canonical_codes(lengths):
    """Assign canonical codes: same length ordered by symbol value.

    Returns a list of code values (0 for unused symbols).  Codes are
    plain integers whose most significant bit is transmitted first.
    """
    max_len = max(lengths) if lengths else 0
    bl_count = [0] * (max_len + 1)
    for l in lengths:
        if l:
            bl_count[l] += 1
    next_code = [0] * (max_len + 1)
    code = 0
    for bits in range(1, max_len + 1):
        code = (code + bl_count[bits - 1]) << 1
        next_code[bits] = code
    codes = [0] * len(lengths)
    for sym, l in enumerate(lengths):
        if l:
            codes[sym] = next_code[l]
            next_code[l] += 1
    return codes


def reverse_bits(code, nbits):
    rev = 0
    for _ in range(nbits):
        rev = (rev << 1) | (code & 1)
        code >>= 1
    return rev


def make_encoder(lengths):
    """Build an encoding table: symbol -> (reversed_code, length).

    The reversed code can be handed straight to
    ``BitWriter.write_bits`` (which is LSB-first) to emit the Huffman
    code MSB-first.
    """
    codes = canonical_codes(lengths)
    enc = []
    for sym, l in enumerate(lengths):
        if l:
            enc.append((reverse_bits(codes[sym], l), l))
        else:
            enc.append((0, 0))
    return enc


class HuffmanDecoder(object):
    """Decodes a canonical Huffman code from a BitReader.

    Uses a single-level lookup table indexed by the next ``max_len``
    bits of input (LSB-first, i.e. the reversed code sits in the low
    bits), mapping to (symbol, code_length).
    """

    __slots__ = ("max_len", "table")

    def __init__(self, lengths):
        self.max_len = max(lengths) if lengths else 0
        if self.max_len == 0:
            self.table = None
            return
        codes = canonical_codes(lengths)
        table = {}
        ml = self.max_len
        for sym, l in enumerate(lengths):
            if l:
                base = reverse_bits(codes[sym], l)
                entry = (sym, l)
                for j in range(1 << (ml - l)):
                    table[base | (j << l)] = entry
        self.table = table

    def decode(self, reader):
        if self.table is None:
            raise ValueError("huffman alphabet has no codes")
        peek = reader.peek_bits(self.max_len)
        try:
            sym, l = self.table[peek]
        except KeyError:
            raise ValueError("invalid huffman code in stream")
        reader.drop_bits(l)
        return sym


def rle_encode_code_lengths(lengths):
    """Run-length encode a code-length sequence per RFC 1951.

    Returns a list of (symbol, extra_value, extra_bits) where symbol is
    a literal code length (0..15) or one of the special symbols
    16 (repeat previous 3-6 times), 17 (repeat zero 3-10 times) and
    18 (repeat zero 11-138 times).
    """
    out = []
    i = 0
    n = len(lengths)
    while i < n:
        v = lengths[i]
        run = 1
        while i + run < n and lengths[i + run] == v:
            run += 1
        i += run
        if v == 0:
            while run >= 11:
                take = min(run, 138)
                out.append((18, take - 11, 7))
                run -= take
            if run >= 3:
                out.append((17, run - 3, 3))
                run = 0
            while run > 0:
                out.append((0, 0, 0))
                run -= 1
        else:
            out.append((v, 0, 0))
            run -= 1
            while run >= 3:
                take = min(run, 6)
                out.append((16, take - 3, 2))
                run -= take
            while run > 0:
                out.append((v, 0, 0))
                run -= 1
    return out
