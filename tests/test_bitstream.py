"""Bit stream tests: LSB-first packing, MSB-first Huffman codes,
cross-byte-boundary reads/writes."""

import random

import pytest

from zipmini.bitstream import BitWriter, BitReader


def test_single_bits_lsb_first():
    w = BitWriter()
    w.write_bits(1, 1)
    w.write_bits(0, 1)
    w.write_bits(1, 1)
    # bits land in bit positions 0, 1, 2 -> 0b00000101
    assert w.getvalue() == bytes([0b00000101])


def test_multibit_value_lsb_first():
    w = BitWriter()
    w.write_bits(0b110, 3)   # emitted as bits 0, 1, 1
    assert w.getvalue() == bytes([0b00000110])


def test_cross_byte_boundary():
    w = BitWriter()
    w.write_bits(0x1FF, 9)   # 9 one-bits: full byte + 1 bit
    assert w.getvalue() == bytes([0xFF, 0x01])


def test_value_too_large_rejected():
    w = BitWriter()
    with pytest.raises(ValueError):
        w.write_bits(0b100, 2)


def test_huffman_code_is_msb_first():
    w = BitWriter()
    w.write_code(0b10, 2)    # emits bit 1 then bit 0
    assert w.getvalue() == bytes([0b00000001])
    w = BitWriter()
    w.write_code(0b110, 3)   # emits 1, 1, 0
    assert w.getvalue() == bytes([0b00000011])


def test_roundtrip_random():
    rng = random.Random(1234)
    widths = [rng.randrange(0, 17) for _ in range(500)]
    values = [rng.randrange(0, 1 << n) if n else 0 for n in widths]
    w = BitWriter()
    for v, n in zip(values, widths):
        w.write_bits(v, n)
    data = w.getvalue()
    r = BitReader(data)
    for v, n in zip(values, widths):
        assert r.read_bits(n) == v


def test_codes_roundtrip_mixed_with_bits():
    # Interleave plain bits and Huffman-style codes across boundaries.
    w = BitWriter()
    w.write_bits(0b101, 3)
    w.write_code(0b10110, 5)
    w.write_bits(0xFFFF, 16)
    w.write_code(0b0, 1)
    data = w.getvalue()
    r = BitReader(data)
    assert r.read_bits(3) == 0b101
    # Huffman code 10110 arrives MSB first: bits 1,0,1,1,0
    assert [r.read_bits(1) for _ in range(5)] == [1, 0, 1, 1, 0]
    assert r.read_bits(16) == 0xFFFF
    assert r.read_bits(1) == 0


def test_align_and_raw_bytes():
    w = BitWriter()
    w.write_bits(0b11, 2)
    w.align_to_byte()
    w.write_raw_bytes(b"\xde\xad")
    w.write_bits(1, 1)
    data = w.getvalue()
    assert data == bytes([0b11, 0xDE, 0xAD, 0x01])
    r = BitReader(data)
    assert r.read_bits(2) == 0b11
    r.align_to_byte()
    assert r.read_bytes(2) == b"\xde\xad"
    assert r.read_bits(1) == 1


def test_read_past_end_gives_zero():
    r = BitReader(b"\xff")
    assert r.read_bits(8) == 0xFF
    assert r.read_bits(8) == 0


def test_read_bytes_past_end_raises():
    r = BitReader(b"\x00")
    with pytest.raises(EOFError):
        r.read_bytes(4)
