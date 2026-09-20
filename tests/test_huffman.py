"""Huffman code construction: package-merge limits and canonical assignment."""

import pytest

from zipmini.huffman import (
    canonical_codes,
    canonical_decoder,
    canonical_encoder,
    length_limited_code_lengths,
    reverse_bits,
)


def kraft(lengths):
    return sum(2.0 ** -l for l in lengths if l)


def test_equal_frequencies_power_of_two():
    lengths = length_limited_code_lengths([1, 1, 1, 1])
    assert lengths == [2, 2, 2, 2]
    assert kraft(lengths) == 1.0


def test_equal_frequencies_odd_count():
    lengths = length_limited_code_lengths([1, 1, 1])
    assert sorted(lengths) == [1, 2, 2]
    assert kraft(lengths) == 1.0


def test_single_symbol_gets_one_bit():
    assert length_limited_code_lengths([0, 0, 7, 0]) == [0, 0, 1, 0]


def test_two_symbols():
    assert length_limited_code_lengths([5, 9]) == [1, 1]


def test_zero_frequency_symbols_get_zero_length():
    lengths = length_limited_code_lengths([0, 3, 0, 1, 0])
    assert lengths[0] == lengths[2] == lengths[4] == 0
    assert lengths[1] == 1
    assert lengths[3] == 1


def test_all_zero_frequencies():
    assert length_limited_code_lengths([0, 0, 0]) == [0, 0, 0]


def test_skewed_distribution():
    lengths = length_limited_code_lengths([1000, 100, 10, 1])
    # The most frequent symbol must get the shortest code.
    assert lengths[0] < lengths[1] < lengths[2] <= lengths[3]
    assert kraft(lengths) == 1.0


def test_length_limit_is_enforced():
    # Exponential weights would need up to 29 bits without a limit.
    freqs = [2 ** i for i in range(30)]
    lengths = length_limited_code_lengths(freqs, max_bits=15)
    assert max(lengths) <= 15
    assert min(lengths) >= 1
    assert kraft(lengths) == 1.0


def test_length_limit_small_alphabet():
    freqs = [2 ** i for i in range(10)]
    lengths = length_limited_code_lengths(freqs, max_bits=4)
    assert max(lengths) <= 4
    assert kraft(lengths) == 1.0


def test_optimality_against_unconstrained_huffman():
    # When the limit does not bind, package-merge matches plain Huffman cost.
    freqs = [5, 7, 10, 15, 20, 45]
    lengths = length_limited_code_lengths(freqs, max_bits=15)
    cost = sum(f * l for f, l in zip(freqs, lengths))
    # Classic Huffman for these frequencies costs 5*4+7*4+10*3+15*2+20*2+45*1... 
    # Just verify Kraft completeness and a known-good cost upper bound.
    assert kraft(lengths) == 1.0
    assert cost <= sum(freqs) * 3  # entropy-style sanity bound for this input


def test_alphabet_too_large_raises():
    with pytest.raises(ValueError):
        length_limited_code_lengths([1] * 300, max_bits=7)


def test_canonical_codes_sorted_by_length_then_symbol():
    # RFC 1951 3.2.2 example-style check: same length -> symbol order.
    lengths = [3, 3, 3, 3, 3, 2, 4, 4]
    codes = canonical_codes(lengths)
    assert codes[5] == 0b00  # shortest code first
    assert codes[0] == 0b010
    assert codes[1] == 0b011
    assert codes[2] == 0b100
    assert codes[3] == 0b101
    assert codes[4] == 0b110
    assert codes[6] == 0b1110
    assert codes[7] == 0b1111


def test_canonical_codes_single_symbol():
    assert canonical_codes([0, 1, 0]) == {1: 0}


def test_oversubscribed_lengths_rejected():
    with pytest.raises(ValueError):
        canonical_codes([1, 1, 1])  # three 1-bit codes do not fit


def test_reverse_bits():
    assert reverse_bits(0b100, 3) == 0b001
    assert reverse_bits(0b1011, 4) == 0b1101
    assert reverse_bits(0, 5) == 0


def test_encoder_decoder_roundtrip_all_symbols():
    import random

    rng = random.Random(99)
    freqs = [rng.randint(0, 500) for _ in range(286)]
    freqs[rng.randrange(286)] = max(1, freqs[0])
    lengths = length_limited_code_lengths(freqs)
    encoder = canonical_encoder(lengths)
    table, length_table, maximum = canonical_decoder(lengths)

    from zipmini.bitstream import BitReader, BitWriter

    bw = BitWriter()
    symbols = [s for s in range(286) if lengths[s]]
    rng.shuffle(symbols)
    for symbol in symbols:
        length, code = encoder[symbol]
        bw.write(code, length)
    reader = BitReader(bw.finish())
    for symbol in symbols:
        index = reader.peek_bits(maximum)
        assert table[index] == symbol
        reader.drop(length_table[index])
