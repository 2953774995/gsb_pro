"""Huffman tree construction edge cases and canonical code rules."""

import random

from zipmini.bitstream import BitWriter, BitReader
from zipmini.huffman import (
    build_code_lengths, ensure_two_codes, canonical_codes, make_encoder,
    HuffmanDecoder, rle_encode_code_lengths,
)


def kraft(lengths):
    """Kraft sum in units of 2^-max_len; a complete code sums to 1<<max."""
    mx = max((l for l in lengths if l), default=0)
    return sum(1 << (mx - l) for l in lengths if l), mx


def test_equal_frequencies():
    lengths = build_code_lengths([1, 1, 1, 1])
    assert lengths == [2, 2, 2, 2]


def test_two_symbols():
    lengths = build_code_lengths([5, 95])
    assert lengths == [1, 1]


def test_single_symbol_gets_length_one():
    lengths = build_code_lengths([0, 0, 7, 0])
    assert lengths == [0, 0, 1, 0]


def test_empty_alphabet():
    assert build_code_lengths([0, 0, 0]) == [0, 0, 0]


def test_skewed_frequencies_stay_optimal():
    # Classic Huffman depths for 1,1,2,4,8,16,32: 6,6,5,4,3,2,2
    lengths = build_code_lengths([1, 1, 2, 4, 8, 16, 32])
    assert lengths == [6, 6, 5, 4, 3, 2, 1] or sorted(lengths) == sorted(
        [6, 6, 5, 4, 3, 2, 1])
    s, mx = kraft(lengths)
    assert s == (1 << mx)


def test_length_limit_fibonacci():
    # Fibonacci frequencies produce maximally deep Huffman trees
    # (depth ~ n), far beyond the 15-bit DEFLATE limit.
    fib = [1, 1]
    for _ in range(38):
        fib.append(fib[-1] + fib[-2])
    lengths = build_code_lengths(fib, max_bits=15)
    assert max(lengths) <= 15
    s, mx = kraft(lengths)
    assert s == (1 << mx)          # still a complete, valid code
    assert all(l > 0 for l in lengths)


def test_length_limit_random():
    rng = random.Random(7)
    for _ in range(50):
        freqs = [rng.randrange(0, 100000) for _ in range(286)]
        lengths = build_code_lengths(freqs, max_bits=15)
        assert max(lengths) <= 15
        nonzero = [l for l in lengths if l]
        if len(nonzero) >= 2:
            s, mx = kraft(lengths)
            assert s == (1 << mx)


def test_canonical_code_assignment():
    # RFC 1951 example: lengths by symbol, same length ordered by symbol.
    lengths = [3, 3, 3, 3, 3, 2, 4, 4]
    codes = canonical_codes(lengths)
    assert codes[5] == 0b00          # shortest code first
    assert codes[0] == 0b010
    assert codes[1] == 0b011
    assert codes[2] == 0b100
    assert codes[3] == 0b101
    assert codes[4] == 0b110
    assert codes[6] == 0b1110
    assert codes[7] == 0b1111


def test_ensure_two_codes():
    lengths = [0, 0, 1, 0]
    ensure_two_codes(lengths)
    assert sum(1 for l in lengths if l) == 2
    assert all(l <= 1 for l in lengths)
    lengths = [0] * 4
    ensure_two_codes(lengths)
    assert sum(1 for l in lengths if l) == 2


def test_encode_decode_roundtrip():
    rng = random.Random(99)
    freqs = [rng.randrange(0, 5000) for _ in range(286)]
    freqs[256] = max(freqs[256], 1)
    lengths = build_code_lengths(freqs)
    enc = make_encoder(lengths)
    dec = HuffmanDecoder(lengths)
    symbols = [s for s, f in enumerate(freqs) for _ in range(min(f, 3))]
    rng.shuffle(symbols)
    w = BitWriter()
    for s in symbols:
        code, n = enc[s]
        w.write_bits(code, n)
    r = BitReader(w.getvalue())
    for s in symbols:
        assert dec.decode(r) == s


def test_rle_encode_zero_runs():
    lengths = [0] * 20 + [5, 5, 5, 5, 5, 5, 5, 5] + [0] * 130
    rle = rle_encode_code_lengths(lengths)
    # Reconstruct the sequence from the RLE symbols.
    out = []
    prev = 0
    for sym, val, _bits in rle:
        if sym == 16:
            out.extend([prev] * (val + 3))
        elif sym == 17:
            out.extend([0] * (val + 3))
        elif sym == 18:
            out.extend([0] * (val + 11))
        else:
            out.append(sym)
            prev = sym
    assert out == lengths
    # Long zero runs must use symbol 18, medium runs 17, repeats 16.
    syms = {s for s, _v, _b in rle}
    assert 18 in syms and 16 in syms


def test_rle_short_runs_use_literals():
    lengths = [0, 0, 3, 3, 0]
    rle = rle_encode_code_lengths(lengths)
    assert all(s < 16 for s, _v, _b in rle)
