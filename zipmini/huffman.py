"""Canonical Huffman codes and a 15-bit length-limited code-length builder."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

MAX_DEFLATE_BITS = 15


def length_limited_code_lengths(
    frequencies: Sequence[int], max_bits: int = MAX_DEFLATE_BITS
) -> List[int]:
    """Return optimal prefix-code lengths limited to ``max_bits`` bits.

    Uses the package-merge algorithm: run ``max_bits`` coin-collector rounds,
    each round pairing ("packaging") the previous round's cheapest items and
    merging those packages back with the leaf coins.  A symbol's code length
    is the number of times its leaf appears among the cheapest ``2n-2`` items
    of the final round.  Zero-frequency symbols get length zero.
    """
    if max_bits <= 0:
        raise ValueError("max_bits must be positive")

    result = [0] * len(frequencies)
    used = [symbol for symbol, freq in enumerate(frequencies) if freq > 0]
    if not used:
        return result
    if len(used) == 1:
        result[used[0]] = 1
        return result
    if len(used) > (1 << max_bits):
        raise ValueError("alphabet is too large for the requested maximum code length")

    # Items are (weight, tiebreak, leaves) where ``leaves`` is a tuple of the
    # leaf symbols contained in the item.  ``tiebreak`` keeps ordering
    # deterministic: leaves (0) sort before packages (1) of equal weight.
    leaves = sorted(
        (int(frequencies[symbol]), 0, (symbol,)) for symbol in used
    )
    take = 2 * len(used) - 2
    current: List[Tuple[int, int, Tuple[int, ...]]] = list(leaves)

    # The initial leaf list is the first coin denomination, so only
    # max_bits - 1 package/merge rounds are needed for max_bits levels.
    for _round in range(max_bits - 1):
        packages = [
            (current[i][0] + current[i + 1][0], 1, current[i][2] + current[i + 1][2])
            for i in range(0, len(current) - 1, 2)
        ]
        merged = leaves + packages
        merged.sort(key=lambda item: (item[0], item[1]))
        current = merged[:take]

    for _weight, _tie, leaf_symbols in current:
        for symbol in leaf_symbols:
            result[symbol] += 1

    if any(length <= 0 or length > max_bits for length in (result[s] for s in used)):
        raise ValueError("internal error constructing length-limited Huffman code")
    return result


def reverse_bits(value: int, width: int) -> int:
    """Reverse ``width`` bits (DEFLATE transmits Huffman codes MSB-first)."""
    result = 0
    for _ in range(width):
        result = (result << 1) | (value & 1)
        value >>= 1
    return result


def canonical_codes(lengths: Sequence[int]) -> Dict[int, int]:
    """Build normal MSB-first canonical Huffman code values.

    Codes are assigned in order of increasing code length; symbols of equal
    length are ordered by symbol value (RFC 1951 section 3.2.2).
    """
    used = sorted((length, symbol) for symbol, length in enumerate(lengths) if length)
    codes: Dict[int, int] = {}
    if not used:
        return codes

    code = 0
    previous_length = used[0][0]
    for length, symbol in used:
        code <<= length - previous_length
        if code >= (1 << length):
            raise ValueError("oversubscribed Huffman code lengths")
        codes[symbol] = code
        code += 1
        previous_length = length
    return codes


def canonical_encoder(lengths: Sequence[int]) -> Dict[int, Tuple[int, int]]:
    """Return symbol -> (code length, bit-reversed canonical code).

    Reversal is deliberate: canonical Huffman values are specified MSB-first,
    while :class:`zipmini.bitstream.BitWriter` consumes values LSB-first.
    """
    return {
        symbol: (lengths[symbol], reverse_bits(code, lengths[symbol]))
        for symbol, code in canonical_codes(lengths).items()
    }


def canonical_decoder(
    lengths: Sequence[int], max_table_bits: int = MAX_DEFLATE_BITS
) -> Tuple[List[int], List[int], int]:
    """Build lookup tables indexed by reversed, LSB-first received bits.

    Returns ``(symbols, entry_lengths, maximum_length)``.  The bit stream is
    indexed after peeking ``maximum_length`` bits, but only a code's own
    length is consumed.  Slots that no code covers (incomplete trees or
    zero padding after the final block) stay ``-1``/``0``.
    """
    if not lengths:
        return [], [], 0
    maximum = max(lengths)
    if maximum == 0:
        return [], [], 0
    if maximum > max_table_bits:
        raise ValueError("Huffman code is too long for decoder table")

    normal_codes = canonical_codes(lengths)
    table = [-1] * (1 << maximum)
    length_table = [0] * (1 << maximum)
    for symbol, code in normal_codes.items():
        length = lengths[symbol]
        reversed_code = reverse_bits(code, length)
        spread = 1 << (maximum - length)
        for suffix in range(spread):
            index = reversed_code | (suffix << length)
            if table[index] != -1:
                raise ValueError("duplicate Huffman decoder entry")
            table[index] = symbol
            length_table[index] = length
    return table, length_table, maximum
