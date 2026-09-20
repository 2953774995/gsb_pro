"""DEFLATE roundtrips plus hand-constructed reference streams (RFC 1951)."""

import random

import pytest

from zipmini.bitstream import BitWriter
from zipmini.deflate import (
    MAX_MATCH,
    Token,
    deflate,
    distance_code,
    inflate,
    length_code,
    lz77_compress,
    store_deflate,
)


# ---------------------------------------------------------------------------
# LZ77 tokenization
# ---------------------------------------------------------------------------

def test_lz77_emits_literals_for_unique_data():
    tokens = lz77_compress(bytes(range(1, 60)))
    assert all(not t.is_match for t in tokens)
    assert bytes(t.literal for t in tokens) == bytes(range(1, 60))


def test_lz77_finds_repeated_pattern():
    data = b"abcdefgh" * 10
    tokens = lz77_compress(data)
    matches = [t for t in tokens if t.is_match]
    assert matches, "expected back-references for a repeated pattern"
    # Reconstruct: literals plus match copies must rebuild the input.
    out = bytearray()
    for t in tokens:
        if t.is_match:
            for _ in range(t.length):
                out.append(out[-t.distance])
        else:
            out.append(t.literal)
    assert bytes(out) == data


def test_lz77_respects_window_and_match_caps():
    data = b"x" * 100000
    tokens = lz77_compress(data)
    for t in tokens:
        if t.is_match:
            assert 3 <= t.length <= MAX_MATCH
            assert 1 <= t.distance <= 32768


def test_length_code_roundtrip():
    from zipmini.deflate import LENGTH_BASE, LENGTH_EXTRA

    for length in range(3, 259):
        symbol, extra = length_code(length)
        index = symbol - 257
        assert 0 <= index < 29
        assert LENGTH_BASE[index] + extra == length
        assert extra < (1 << LENGTH_EXTRA[index])


def test_distance_code_roundtrip():
    from zipmini.deflate import DIST_BASE, DIST_EXTRA

    for distance in list(range(1, 300)) + [1024, 4096, 24577, 32767, 32768]:
        symbol, extra = distance_code(distance)
        assert DIST_BASE[symbol] + extra == distance
        assert extra < (1 << DIST_EXTRA[symbol])


def test_length_code_rejects_out_of_range():
    with pytest.raises(ValueError):
        length_code(2)
    with pytest.raises(ValueError):
        length_code(259)
    with pytest.raises(ValueError):
        distance_code(0)
    with pytest.raises(ValueError):
        distance_code(32769)


# ---------------------------------------------------------------------------
# Hand-constructed reference streams (no library involved in building them)
# ---------------------------------------------------------------------------

def test_inflate_handbuilt_stored_block():
    # BFINAL=1, BTYPE=00 -> first byte 0x01, then LEN=3, NLEN=~3, then data.
    stream = bytes([0x01, 0x03, 0x00, 0xFC, 0xFF]) + b"abc"
    assert inflate(stream) == b"abc"


def test_inflate_handbuilt_stored_empty():
    stream = bytes([0x01, 0x00, 0x00, 0xFF, 0xFF])
    assert inflate(stream) == b""


def test_inflate_handbuilt_fixed_block():
    # Fixed-Huffman block for b"hello", derived by hand:
    #   header bits (LSB-first): BFINAL=1, BTYPE=01 -> 1,1,0
    #   fixed literal codes (MSB-first): h=0x98 e=0x95 l=0x9C l=0x9C o=0x9F
    #   end-of-block 256 -> 7 bits 0000000, then zero padding.
    stream = bytes([203, 72, 205, 201, 201, 7, 0])
    assert inflate(stream) == b"hello"


def test_inflate_handbuilt_dynamic_block():
    # Dynamic block encoding the single byte b"A".
    #
    # Literal/length lengths: symbol 65 ('A') -> 1 bit, symbol 256 -> 1 bit.
    # Distance lengths: one code, symbol 0 -> 1 bit.
    # Length sequence (257 + 1 entries): 0*65, 1, 0*190, 1, 1
    # RLE: 18(54) 1 18(127) 18(41) 1 1   -> CL symbols {18: 3, 1: 3}
    # CL lengths: symbol 1 -> 1, symbol 18 -> 1; canonical codes: 1->0, 18->1.
    bw = BitWriter()
    bw.write(1, 1)          # BFINAL
    bw.write(2, 2)          # BTYPE = dynamic
    bw.write(0, 5)          # HLIT = 257
    bw.write(0, 5)          # HDIST = 1
    bw.write(14, 4)         # HCLEN = 18 code-length codes
    # CL_ORDER = 16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1
    cl_lengths = [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]
    for length in cl_lengths:
        bw.write(length, 3)
    # RLE stream. CL codes: symbol 18 -> bit 1, symbol 1 -> bit 0.
    bw.write(1, 1)          # symbol 18
    bw.write(54, 7)         # 11 + 54 = 65 zero lengths
    bw.write(0, 1)          # symbol 1: length 1 (symbol 65)
    bw.write(1, 1)          # symbol 18
    bw.write(127, 7)        # 11 + 127 = 138 zeros
    bw.write(1, 1)          # symbol 18
    bw.write(41, 7)         # 11 + 41 = 52 zeros (190 total)
    bw.write(0, 1)          # symbol 1: length 1 (symbol 256)
    bw.write(0, 1)          # symbol 1: length 1 (distance symbol 0)
    # Data: literal 'A' has lit code 0 (1 bit); end-of-block has code 1.
    bw.write(0, 1)
    bw.write(1, 1)
    assert inflate(bw.finish()) == b"A"


def test_inflate_rejects_reserved_block_type():
    bw = BitWriter()
    bw.write(1, 1)
    bw.write(3, 2)  # reserved
    with pytest.raises(ValueError):
        inflate(bw.finish())


def test_inflate_rejects_bad_stored_nlen():
    stream = bytes([0x01, 0x03, 0x00, 0x00, 0x00]) + b"abc"
    with pytest.raises(ValueError):
        inflate(stream)


def test_inflate_rejects_truncated_stream():
    with pytest.raises(EOFError):
        inflate(bytes([0x05]))  # fixed block header, then nothing


# ---------------------------------------------------------------------------
# Roundtrips through our own codec
# ---------------------------------------------------------------------------

def _rng_data(seed, size):
    return random.Random(seed).randbytes(size)


@pytest.mark.parametrize("data", [
    b"",
    b"a",
    b"ab",
    b"abc",
    b"hello world",
    b"\x00",
    b"\x00" * 1000,
    b"a" * 100000,
    b"the quick brown fox jumps over the lazy dog. " * 500,
    bytes(range(256)) * 40,
    _rng_data(1, 1),
    _rng_data(2, 100),
    _rng_data(3, 65535),
    _rng_data(4, 65536),
    _rng_data(5, 200000),
], ids=lambda d: f"len{len(d)}")
def test_deflate_roundtrip(data):
    compressed = deflate(data)
    assert inflate(compressed, expected_size=len(data)) == data


def test_deflate_roundtrip_few_mb():
    # A few MB of mixed compressible and incompressible content.
    rng = random.Random(2024)
    chunk = (b"Lorem ipsum dolor sit amet. " * 20000
             + rng.randbytes(1_200_000)
             + b"\x00" * 800_000
             + bytes(range(256)) * 4000)
    assert len(chunk) > 3_000_000
    compressed = deflate(chunk)
    assert inflate(compressed, expected_size=len(chunk)) == chunk


def test_random_data_uses_stored_blocks():
    data = _rng_data(6, 10000)
    compressed = deflate(data)
    # Stored encoding: input plus a 5-byte-per-block overhead, nothing more.
    assert len(compressed) <= len(data) + 10
    assert inflate(compressed) == data


def test_repetitive_data_compresses_well():
    data = b"abcabcabc" * 10000
    compressed = deflate(data)
    assert len(compressed) < len(data) // 100
    assert inflate(compressed) == data


def test_window_boundary_matches():
    # A pattern repeated just under/over the 32 KiB window must roundtrip.
    rng = random.Random(11)
    marker = rng.randbytes(64)
    data = marker + rng.randbytes(32768 - 64) + marker + rng.randbytes(100)
    assert inflate(deflate(data)) == data
    data2 = marker + rng.randbytes(40000) + marker
    assert inflate(deflate(data2)) == data2


def test_store_deflate_multi_block():
    data = _rng_data(7, 70000)  # exceeds one 65535-byte stored block
    stream = store_deflate(data)
    assert inflate(stream) == data


def test_deflate_levels_all_roundtrip():
    data = (b"some repetitive text here. " * 500) + _rng_data(8, 2000)
    for level in (1, 3, 6, 9):
        assert inflate(deflate(data, level=level)) == data
