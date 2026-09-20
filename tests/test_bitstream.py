"""Bit-level I/O: LSB-first packing, cross-byte reads, peek/drop, alignment."""

import pytest

from zipmini.bitstream import BitReader, BitWriter


def test_write_read_single_bits_lsb_first():
    bw = BitWriter()
    # Bits are packed LSB-first: value 1 in 1 bit sets the lowest bit.
    bw.write(1, 1)
    bw.write(0, 1)
    bw.write(1, 1)
    assert bw.finish() == bytes([0b00000101])
    reader = BitReader(bytes([0b00000101]))
    assert reader.read_bits(1) == 1
    assert reader.read_bits(1) == 0
    assert reader.read_bits(1) == 1


def test_multi_bit_value_lsb_order():
    bw = BitWriter()
    bw.write(0b101, 3)  # transmitted low bit first: 1, 0, 1
    assert bw.finish() == bytes([0b00000101])


def test_cross_byte_boundary():
    bw = BitWriter()
    bw.write(0xFF, 8)
    bw.write(0x0F, 4)
    bw.write(0x02, 2)
    data = bw.finish()
    assert data == bytes([0xFF, 0b00001011_00000000 & 0xFF | 0x0F | (0x02 << 4)])
    reader = BitReader(data)
    assert reader.read_bits(8) == 0xFF
    assert reader.read_bits(4) == 0x0F
    assert reader.read_bits(2) == 0x02


def test_roundtrip_random_widths():
    import random

    rng = random.Random(1234)
    values = [(rng.getrandbits(w), w) for w in
              [rng.randint(1, 16) for _ in range(500)]]
    bw = BitWriter()
    for value, width in values:
        bw.write(value, width)
    reader = BitReader(bw.finish())
    for value, width in values:
        assert reader.read_bits(width) == value


def test_peek_and_drop():
    bw = BitWriter()
    bw.write(0b1101, 4)
    bw.write(0b001, 3)
    reader = BitReader(bw.finish())
    assert reader.peek_bits(4) == 0b1101
    # Peeking again gives the same value: nothing consumed.
    assert reader.peek_bits(4) == 0b1101
    reader.drop(4)
    assert reader.read_bits(3) == 0b001


def test_peek_longer_than_stream_zero_pads():
    reader = BitReader(bytes([0x03]))
    # Only 8 bits exist; peeking 16 zero-pads the high bits.
    assert reader.peek_bits(16) == 0x03


def test_align_pads_with_zero_bits():
    bw = BitWriter()
    bw.write(1, 1)
    bw.align()
    bw.write(0xAB, 8)
    assert bw.finish() == bytes([0x01, 0xAB])


def test_reader_align_discards_partial_byte():
    bw = BitWriter()
    bw.write(0xF, 4)
    bw.align()  # writer pads too, so 0xAB starts on a fresh byte
    bw.write(0xAB, 8)
    data = bw.finish()
    reader = BitReader(data)
    assert reader.read_bits(4) == 0xF
    reader.align()
    assert reader.read_bits(8) == 0xAB


def test_reader_align_after_peek():
    # Peeking must not lose bytes: align() rewinds to the first unread bit.
    reader = BitReader(bytes([0xFF, 0xAB, 0xCD]))
    reader.peek_bits(15)
    reader.align()
    assert reader.read_bits(8) == 0xFF
    assert reader.read_bits(8) == 0xAB


def test_read_past_end_raises():
    reader = BitReader(bytes([0x00]))
    reader.read_bits(8)
    with pytest.raises(EOFError):
        reader.read_bits(1)


def test_write_value_out_of_range_raises():
    bw = BitWriter()
    with pytest.raises(ValueError):
        bw.write(8, 3)
    with pytest.raises(ValueError):
        bw.write(-1, 3)


def test_zero_width_write_and_read():
    bw = BitWriter()
    bw.write(0, 0)
    bw.write(0x11, 8)
    assert bw.finish() == bytes([0x11])
    assert BitReader(bytes()).read_bits(0) == 0


def test_byte_length_and_aligned_properties():
    bw = BitWriter()
    assert bw.aligned
    bw.write(1, 1)
    assert not bw.aligned
    assert bw.byte_length() == 1
    bw.write(0x7F, 7)
    assert bw.aligned
    assert bw.byte_length() == 1
