"""DEFLATE compression and decompression (RFC 1951).

Supports all three block types: stored (uncompressed), fixed Huffman
and dynamic Huffman.  The compressor runs LZ77 over each block and
picks whichever of the three encodings is smallest, so incompressible
data is stored verbatim instead of growing.
"""

import struct

from .bitstream import BitWriter, BitReader
from . import lz77
from .huffman import (
    MAX_BITS, MAX_CL_BITS, CL_ORDER,
    build_code_lengths, ensure_two_codes, make_encoder, HuffmanDecoder,
    rle_encode_code_lengths,
)

# --- RFC 1951 constant tables -------------------------------------------

# Length codes 257..285: base value and number of extra bits.
LENGTH_BASE = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
               35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258)
LENGTH_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
                3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0)

# Distance codes 0..29: base value and number of extra bits.
DIST_BASE = (1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
             257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
             8193, 12289, 16385, 24577)
DIST_EXTRA = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
              7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13)

NUM_LIT_CODES = 286      # 0..255 literals, 256 end-of-block, 257..285 lengths
NUM_DIST_CODES = 30
NUM_CL_CODES = 19
EOB = 256                # end-of-block symbol

# length (3..258) -> length symbol (257..285)
_LENGTH_SYM = [0] * 259
for _idx in range(29):
    _base = LENGTH_BASE[_idx]
    for _L in range(_base, _base + (1 << LENGTH_EXTRA[_idx])):
        if _L <= 258:
            _LENGTH_SYM[_L] = 257 + _idx
_LENGTH_SYM[258] = 285   # 258 is code 285, not 284 with extra bits


def _dist_sym(d):
    """Map a distance (1..32768) to its symbol (0..29)."""
    lo, hi = 0, 29
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if DIST_BASE[mid] <= d:
            lo = mid
        else:
            hi = mid - 1
    return lo


# Fixed Huffman code lengths (RFC 1951 section 3.2.6).
FIXED_LIT_LENGTHS = tuple(
    [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8)
FIXED_DIST_LENGTHS = tuple([5] * NUM_DIST_CODES)
_FIXED_LIT_ENC = make_encoder(FIXED_LIT_LENGTHS)
_FIXED_DIST_ENC = make_encoder(FIXED_DIST_LENGTHS)

# Compress in chunks of at most this many bytes; one chunk == one block.
# 65535 is the largest payload a single stored block can hold.
BLOCK_SIZE = 65535


class DeflateError(ValueError):
    """Raised when a DEFLATE stream is malformed."""


# --- compression ---------------------------------------------------------

def _write_stored_block(w, chunk, final):
    w.write_bits(1 if final else 0, 1)
    w.write_bits(0, 2)              # BTYPE = 00 (stored)
    w.align_to_byte()
    n = len(chunk)
    w.write_raw_bytes(struct.pack("<HH", n, n ^ 0xFFFF))
    w.write_raw_bytes(chunk)


def _token_stats(tokens):
    """Return (lit_freq, dist_freq, extra_bit_count) for a token list."""
    lit_freq = [0] * NUM_LIT_CODES
    dist_freq = [0] * NUM_DIST_CODES
    extra_bits = 0
    for t in tokens:
        if isinstance(t, int):
            lit_freq[t] += 1
        else:
            length, dist = t
            lsym = _LENGTH_SYM[length]
            lit_freq[lsym] += 1
            extra_bits += LENGTH_EXTRA[lsym - 257]
            dsym = _dist_sym(dist)
            dist_freq[dsym] += 1
            extra_bits += DIST_EXTRA[dsym]
    lit_freq[EOB] += 1
    return lit_freq, dist_freq, extra_bits


def _write_tokens(w, tokens, lit_enc, dist_enc):
    write = w.write_bits
    for t in tokens:
        if isinstance(t, int):
            code, nbits = lit_enc[t]
            write(code, nbits)
        else:
            length, dist = t
            lsym = _LENGTH_SYM[length]
            code, nbits = lit_enc[lsym]
            write(code, nbits)
            idx = lsym - 257
            write(length - LENGTH_BASE[idx], LENGTH_EXTRA[idx])
            dsym = _dist_sym(dist)
            code, nbits = dist_enc[dsym]
            write(code, nbits)
            write(dist - DIST_BASE[dsym], DIST_EXTRA[dsym])
    code, nbits = lit_enc[EOB]
    write(code, nbits)


def _freq_bits(freqs, lengths):
    return sum(f * l for f, l in zip(freqs, lengths) if f and l)


def _write_block(w, chunk, final):
    tokens = lz77.compress(chunk)
    lit_freq, dist_freq, extra_bits = _token_stats(tokens)

    # Size if encoded with the fixed Huffman codes.
    fixed_bits = (3 + extra_bits + _freq_bits(lit_freq, FIXED_LIT_LENGTHS)
                  + _freq_bits(dist_freq, FIXED_DIST_LENGTHS))

    # Size if encoded with dynamic Huffman codes.
    lit_lens = build_code_lengths(lit_freq, MAX_BITS)
    dist_lens = build_code_lengths(dist_freq, MAX_BITS)
    ensure_two_codes(lit_lens)
    ensure_two_codes(dist_lens)
    hlit = max(257, max(i for i, l in enumerate(lit_lens) if l) + 1)
    hdist = max(1, max(i for i, l in enumerate(dist_lens) if l) + 1)
    rle = rle_encode_code_lengths(lit_lens[:hlit] + dist_lens[:hdist])
    cl_freq = [0] * NUM_CL_CODES
    cl_extra = 0
    for sym, _val, ebits in rle:
        cl_freq[sym] += 1
        cl_extra += ebits
    cl_lens = build_code_lengths(cl_freq, MAX_CL_BITS)
    ensure_two_codes(cl_lens)
    hclen = 4
    for k in range(len(CL_ORDER), 4, -1):
        if cl_lens[CL_ORDER[k - 1]]:
            hclen = k
            break
    dynamic_bits = (3 + 5 + 5 + 4 + 3 * hclen + cl_extra + extra_bits
                    + _freq_bits(cl_freq, cl_lens)
                    + _freq_bits(lit_freq, lit_lens)
                    + _freq_bits(dist_freq, dist_lens))

    # Size if stored verbatim (worst-case padding included).
    stored_bits = 3 + 7 + 32 + 8 * len(chunk)

    if stored_bits <= fixed_bits and stored_bits <= dynamic_bits:
        _write_stored_block(w, chunk, final)
        return

    w.write_bits(1 if final else 0, 1)
    if fixed_bits <= dynamic_bits:
        w.write_bits(1, 2)          # BTYPE = 01 (fixed)
        _write_tokens(w, tokens, _FIXED_LIT_ENC, _FIXED_DIST_ENC)
    else:
        w.write_bits(2, 2)          # BTYPE = 10 (dynamic)
        w.write_bits(hlit - 257, 5)
        w.write_bits(hdist - 1, 5)
        w.write_bits(hclen - 4, 4)
        for k in range(hclen):
            w.write_bits(cl_lens[CL_ORDER[k]], 3)
        cl_enc = make_encoder(cl_lens)
        for sym, val, ebits in rle:
            code, nbits = cl_enc[sym]
            w.write_bits(code, nbits)
            if ebits:
                w.write_bits(val, ebits)
        _write_tokens(w, tokens, make_encoder(lit_lens),
                      make_encoder(dist_lens))


def compress(data):
    """Compress ``data`` (bytes) into a raw DEFLATE stream."""
    w = BitWriter()
    n = len(data)
    if n == 0:
        _write_stored_block(w, b"", True)
        return w.getvalue()
    pos = 0
    while pos < n:
        chunk = data[pos:pos + BLOCK_SIZE]
        _write_block(w, chunk, pos + BLOCK_SIZE >= n)
        pos += BLOCK_SIZE
    return w.getvalue()


# --- decompression -------------------------------------------------------

def _decode_compressed_block(reader, lit_dec, dist_dec, out):
    while True:
        sym = lit_dec.decode(reader)
        if sym < 256:
            out.append(sym)
        elif sym == EOB:
            return
        elif sym < 286:
            idx = sym - 257
            length = LENGTH_BASE[idx] + reader.read_bits(LENGTH_EXTRA[idx])
            dsym = dist_dec.decode(reader)
            if dsym >= NUM_DIST_CODES:
                raise DeflateError("invalid distance code %d" % dsym)
            dist = DIST_BASE[dsym] + reader.read_bits(DIST_EXTRA[dsym])
            if dist > len(out):
                raise DeflateError("distance too far back")
            start = len(out) - dist
            if dist >= length:
                out += out[start:start + length]
            else:
                piece = bytes(out[start:])
                out += (piece * (length // dist + 1))[:length]
        else:
            raise DeflateError("invalid literal/length code %d" % sym)


def _read_dynamic_tables(reader):
    hlit = reader.read_bits(5) + 257
    hdist = reader.read_bits(5) + 1
    hclen = reader.read_bits(4) + 4
    if hlit > NUM_LIT_CODES or hdist > NUM_DIST_CODES:
        raise DeflateError("too many literal/distance codes")
    cl_lens = [0] * NUM_CL_CODES
    for k in range(hclen):
        cl_lens[CL_ORDER[k]] = reader.read_bits(3)
    cl_dec = HuffmanDecoder(cl_lens)

    lengths = []
    total = hlit + hdist
    while len(lengths) < total:
        sym = cl_dec.decode(reader)
        if sym < 16:
            lengths.append(sym)
        elif sym == 16:
            if not lengths:
                raise DeflateError("repeat with no previous code length")
            rep = reader.read_bits(2) + 3
            lengths.extend([lengths[-1]] * rep)
        elif sym == 17:
            lengths.extend([0] * (reader.read_bits(3) + 3))
        else:  # 18
            lengths.extend([0] * (reader.read_bits(7) + 11))
    if len(lengths) != total:
        raise DeflateError("code length repeat overflows table")
    lit_lens = lengths[:hlit]
    dist_lens = lengths[hlit:]
    if not lit_lens[EOB]:
        raise DeflateError("missing end-of-block code")
    return HuffmanDecoder(lit_lens), HuffmanDecoder(dist_lens)


def decompress(data, max_length=None):
    """Decompress a raw DEFLATE stream, returning the original bytes."""
    reader = BitReader(data)
    out = bytearray()
    while True:
        final = reader.read_bits(1)
        btype = reader.read_bits(2)
        if btype == 0:                      # stored
            reader.align_to_byte()
            header = reader.read_bytes(4)
            length, nlen = struct.unpack("<HH", header)
            if length != (nlen ^ 0xFFFF):
                raise DeflateError("stored block LEN/NLEN mismatch")
            out += reader.read_bytes(length)
        elif btype == 1:                    # fixed Huffman
            _decode_compressed_block(
                reader,
                HuffmanDecoder(FIXED_LIT_LENGTHS),
                HuffmanDecoder(FIXED_DIST_LENGTHS),
                out)
        elif btype == 2:                    # dynamic Huffman
            lit_dec, dist_dec = _read_dynamic_tables(reader)
            _decode_compressed_block(reader, lit_dec, dist_dec, out)
        else:
            raise DeflateError("invalid block type 3")
        if max_length is not None and len(out) > max_length:
            raise DeflateError("decompressed data exceeds expected size")
        if final:
            break
    return bytes(out)
