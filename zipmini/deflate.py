"""Raw DEFLATE compression/decompression (RFC 1951), implemented from scratch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .bitstream import BitReader, BitWriter
from .huffman import canonical_decoder, canonical_encoder, length_limited_code_lengths

MIN_MATCH = 3
MAX_MATCH = 258
MAX_WINDOW = 32768
END_OF_BLOCK = 256
MAX_LIT_SYMBOLS = 286
MAX_DIST_SYMBOLS = 30

LENGTH_BASE = (3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258)
LENGTH_EXTRA = (0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0)
DIST_BASE = (1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577)
DIST_EXTRA = (0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13)
CL_ORDER = (16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15)


@dataclass
class Token:
    """One LZ77 output event.

    A literal has ``literal`` in 0..255 and zero length/distance.  A match has
    ``literal == -1`` and a valid length/distance pair.
    """

    literal: int = -1
    length: int = 0
    distance: int = 0

    @property
    def is_match(self) -> bool:
        return self.length != 0


def _hash3(data: bytes, pos: int) -> int:
    # Multiplicative mixing gives a better spread than xor alone.
    return ((data[pos] * 65537) ^ (data[pos + 1] * 257) ^ data[pos + 2]) & 0xFFFF


def _common_length(data: bytes, pos: int, candidate: int, limit: int) -> int:
    j = 0
    # Compare in chunks while retaining strict, overlap-safe semantics.
    while j + 16 <= limit and data[pos + j:pos + j + 16] == data[candidate + j:candidate + j + 16]:
        j += 16
    while j < limit and data[pos + j] == data[candidate + j]:
        j += 1
    return j


def lz77_compress(
    data: bytes,
    max_chain: int = 128,
    nice_length: int = 128,
    insert_all: bool = True,
    good_length: int = 8,
) -> List[Token]:
    """Greedy LZ77 using a 3-byte hash chain over a 32 KiB window.

    ``max_chain`` bounds how many chain links are followed per position,
    ``nice_length`` stops the search early once a match is long enough, and
    ``insert_all=False`` skips hashing positions covered by a match (faster,
    slightly worse ratio -- the classic fast-vs-slow deflate trade-off).
    Following a good match the chain budget is quartered (zlib's good-match
    heuristic): long matches usually mean the neighbourhood is repetitive.
    """
    n = len(data)
    tokens: List[Token] = []
    if n < MIN_MATCH:
        tokens.extend(Token(literal=value) for value in data)
        return tokens

    head = [-1] * 65536
    prev = [-1] * MAX_WINDOW
    mask = MAX_WINDOW - 1
    append = tokens.append
    pos = 0
    previous_length = 0

    while pos < n:
        if pos > n - MIN_MATCH:
            append(Token(literal=data[pos]))
            pos += 1
            continue

        chain_budget = max_chain >> 2 if previous_length >= good_length else max_chain

        # Inlined 3-byte multiplicative hash; this is the hottest loop.
        hash_value = ((data[pos] * 65537) ^ (data[pos + 1] * 257) ^ data[pos + 2]) & 0xFFFF
        best_len = MIN_MATCH - 1
        best_dist = 0
        candidate = head[hash_value]
        searched = 0
        limit = n - pos
        if limit > MAX_MATCH:
            limit = MAX_MATCH

        while (
            candidate >= 0
            and searched < chain_budget
            and best_len < limit
            and pos - candidate <= MAX_WINDOW
        ):
            # The last-byte filter skips most chain links without comparing.
            if data[candidate + best_len] == data[pos + best_len]:
                j = 0
                while j + 16 <= limit and data[pos + j:pos + j + 16] == data[candidate + j:candidate + j + 16]:
                    j += 16
                while j < limit and data[pos + j] == data[candidate + j]:
                    j += 1
                if j > best_len:
                    best_len = j
                    best_dist = pos - candidate
                    if best_len >= nice_length:
                        break
            searched += 1
            candidate = prev[candidate & mask]

        prev[pos & mask] = head[hash_value]
        head[hash_value] = pos

        previous_length = best_len if best_dist else 0
        if best_dist:
            append(Token(length=best_len, distance=best_dist))
            next_pos = pos + best_len
            if insert_all:
                insert_end = next_pos
                max_insert = n - MIN_MATCH + 1
                if insert_end > max_insert:
                    insert_end = max_insert
                for insert_pos in range(pos + 1, insert_end):
                    insert_hash = ((data[insert_pos] * 65537) ^ (data[insert_pos + 1] * 257) ^ data[insert_pos + 2]) & 0xFFFF
                    prev[insert_pos & mask] = head[insert_hash]
                    head[insert_hash] = insert_pos
            pos = next_pos
        else:
            append(Token(literal=data[pos]))
            pos += 1

    return tokens


def _build_length_table() -> List[int]:
    table = [0] * (MAX_MATCH + 1)
    for index in range(29):
        base = LENGTH_BASE[index]
        span = 1 << LENGTH_EXTRA[index]
        for length in range(base, base + span):
            table[length] = 257 + index
    return table


def _build_distance_table() -> List[int]:
    table = [0] * (MAX_WINDOW + 1)
    for index in range(30):
        base = DIST_BASE[index]
        span = 1 << DIST_EXTRA[index]
        for distance in range(base, base + span):
            table[distance] = index
    return table


_LENGTH_SYMBOL = _build_length_table()
_DISTANCE_SYMBOL = _build_distance_table()


def length_code(length: int) -> Tuple[int, int]:
    if not MIN_MATCH <= length <= MAX_MATCH:
        raise ValueError(f"invalid match length {length}")
    symbol = _LENGTH_SYMBOL[length]
    return symbol, length - LENGTH_BASE[symbol - 257]


def distance_code(distance: int) -> Tuple[int, int]:
    if not 1 <= distance <= MAX_WINDOW:
        raise ValueError(f"invalid match distance {distance}")
    symbol = _DISTANCE_SYMBOL[distance]
    return symbol, distance - DIST_BASE[symbol]


def _fixed_lengths() -> Tuple[List[int], List[int]]:
    literal = [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8
    distance = [5] * MAX_DIST_SYMBOLS
    return literal, distance


def store_deflate(data: bytes, final: bool = True) -> bytes:
    """Encode one or more stored DEFLATE blocks."""
    bw = BitWriter()
    if not data:
        bw.write(1 if final else 0, 1)
        bw.write(0, 2)
        bw.align()
        bw.write(0, 16)
        bw.write(0xFFFF, 16)
        return bw.finish()

    offset = 0
    while offset < len(data):
        chunk = data[offset:offset + 65535]
        offset += len(chunk)
        bw.write(1 if final and offset == len(data) else 0, 1)
        bw.write(0, 2)
        bw.align()
        bw.write(len(chunk), 16)
        bw.write(len(chunk) ^ 0xFFFF, 16)
        bw.buf.extend(chunk)
    return bytes(bw.buf)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def _token_frequencies(tokens: Sequence[Token]) -> Tuple[List[int], List[int], int]:
    """Count literal/length and distance symbol frequencies.

    Returns ``(lit_freq, dist_freq, extra_bits)`` where ``extra_bits`` is the
    total number of extra bits the matches will occupy.
    """
    lit_freq = [0] * MAX_LIT_SYMBOLS
    dist_freq = [0] * MAX_DIST_SYMBOLS
    extra_bits = 0
    length_symbol = _LENGTH_SYMBOL
    distance_symbol = _DISTANCE_SYMBOL
    for token in tokens:
        if token.is_match:
            lsym = length_symbol[token.length]
            dsym = distance_symbol[token.distance]
            lit_freq[lsym] += 1
            dist_freq[dsym] += 1
            extra_bits += LENGTH_EXTRA[lsym - 257] + DIST_EXTRA[dsym]
        else:
            lit_freq[token.literal] += 1
    lit_freq[END_OF_BLOCK] += 1
    return lit_freq, dist_freq, extra_bits


def _force_two_symbols(freqs: List[int]) -> None:
    """Give a frequency table at least two non-zero symbols, in place.

    A Huffman tree with a single leaf cannot be represented canonically with
    a complete code; some inflaters reject such trees.  Bumping a zero-count
    neighbour to one keeps the emitted tree complete at negligible cost.
    """
    used = [symbol for symbol, freq in enumerate(freqs) if freq > 0]
    if len(used) >= 2:
        return
    if not used:
        freqs[0] = 1
        freqs[1] = 1
    elif used[0] == 0:
        freqs[1] = 1
    else:
        freqs[0] = 1


def _rle_code_lengths(lengths: Sequence[int]) -> List[Tuple[int, int, int]]:
    """Run-length encode a code-length sequence per RFC 1951 3.2.7.

    Returns a list of ``(symbol, extra_value, extra_bits)`` triples where
    symbol is 0..18 (16/17/18 are the repeat codes).
    """
    result: List[Tuple[int, int, int]] = []
    i = 0
    n = len(lengths)
    while i < n:
        value = lengths[i]
        run = 1
        while i + run < n and lengths[i + run] == value:
            run += 1
        i += run
        if value == 0:
            while run >= 11:
                take = min(run, 138)
                result.append((18, take - 11, 7))
                run -= take
            if run >= 3:
                result.append((17, run - 3, 3))
                run = 0
            while run:
                result.append((0, 0, 0))
                run -= 1
        else:
            result.append((value, 0, 0))
            run -= 1
            while run >= 3:
                take = min(run, 6)
                result.append((16, take - 3, 2))
                run -= take
            while run:
                result.append((value, 0, 0))
                run -= 1
    return result


def _write_symbol(bw: BitWriter, encoder: dict, symbol: int) -> None:
    length, code = encoder[symbol]
    bw.write(code, length)


def _write_tokens(bw: BitWriter, tokens: Sequence[Token], lit_enc: dict, dist_enc: dict) -> None:
    # Unpack dicts into flat lists: list indexing beats dict lookups here.
    # (288 entries: the fixed table also defines the unused symbols 286-287.)
    lit_code = [0] * 288
    lit_len = [0] * 288
    for symbol, (length, code) in lit_enc.items():
        lit_code[symbol] = code
        lit_len[symbol] = length
    dist_code = [0] * MAX_DIST_SYMBOLS
    dist_len = [0] * MAX_DIST_SYMBOLS
    for symbol, (length, code) in dist_enc.items():
        dist_code[symbol] = code
        dist_len[symbol] = length

    length_symbol = _LENGTH_SYMBOL
    distance_symbol = _DISTANCE_SYMBOL
    write = bw.write
    for token in tokens:
        if token.is_match:
            lsym = length_symbol[token.length]
            write(lit_code[lsym], lit_len[lsym])
            write(token.length - LENGTH_BASE[lsym - 257], LENGTH_EXTRA[lsym - 257])
            dsym = distance_symbol[token.distance]
            write(dist_code[dsym], dist_len[dsym])
            write(token.distance - DIST_BASE[dsym], DIST_EXTRA[dsym])
        else:
            write(lit_code[token.literal], lit_len[token.literal])
    write(lit_code[END_OF_BLOCK], lit_len[END_OF_BLOCK])


def _fixed_encoders() -> Tuple[dict, dict, List[int], List[int]]:
    lit_lengths, dist_lengths = _fixed_lengths()
    return canonical_encoder(lit_lengths), canonical_encoder(dist_lengths), lit_lengths, dist_lengths


def _dynamic_plan(lit_freq: List[int], dist_freq: List[int], extra_bits: int):
    """Compute dynamic-Huffman tables and the exact encoded bit cost."""
    lit_freq = list(lit_freq)
    dist_freq = list(dist_freq)
    _force_two_symbols(lit_freq)
    _force_two_symbols(dist_freq)

    lit_lengths = length_limited_code_lengths(lit_freq)
    dist_lengths = length_limited_code_lengths(dist_freq)

    # Trim trailing zero lengths, keeping the RFC 1951 minimums (257 / 1).
    hlit = max(257, max(i for i, l in enumerate(lit_lengths) if l) + 1)
    hdist = max(1, max(i for i, l in enumerate(dist_lengths) if l) + 1)
    combined = lit_lengths[:hlit] + dist_lengths[:hdist]

    rle = _rle_code_lengths(combined)
    cl_freq = [0] * 19
    rle_extra_bits = 0
    for symbol, _extra, ebits in rle:
        cl_freq[symbol] += 1
        rle_extra_bits += ebits
    _force_two_symbols(cl_freq)
    cl_lengths = length_limited_code_lengths(cl_freq, max_bits=7)

    hclen = 4
    for index, symbol in enumerate(CL_ORDER):
        if cl_lengths[symbol]:
            hclen = max(hclen, index + 1)

    data_bits = sum(f * l for f, l in zip(lit_freq, lit_lengths))
    data_bits += sum(f * l for f, l in zip(dist_freq, dist_lengths))
    header_bits = 3 + 5 + 5 + 4 + 3 * hclen
    header_bits += sum(f * l for f, l in zip(cl_freq, cl_lengths)) + rle_extra_bits
    total_bits = header_bits + data_bits + extra_bits

    plan = {
        "lit_lengths": lit_lengths,
        "dist_lengths": dist_lengths,
        "cl_lengths": cl_lengths,
        "hlit": hlit,
        "hdist": hdist,
        "hclen": hclen,
        "rle": rle,
        "bits": total_bits,
    }
    return plan


def _write_dynamic_block(bw: BitWriter, tokens: Sequence[Token], final: bool, plan: dict) -> None:
    bw.write(1 if final else 0, 1)
    bw.write(2, 2)
    bw.write(plan["hlit"] - 257, 5)
    bw.write(plan["hdist"] - 1, 5)
    bw.write(plan["hclen"] - 4, 4)
    cl_lengths = plan["cl_lengths"]
    for symbol in CL_ORDER[: plan["hclen"]]:
        bw.write(cl_lengths[symbol], 3)

    cl_enc = canonical_encoder(cl_lengths)
    for symbol, extra, ebits in plan["rle"]:
        _write_symbol(bw, cl_enc, symbol)
        if ebits:
            bw.write(extra, ebits)

    lit_enc = canonical_encoder(plan["lit_lengths"])
    dist_enc = canonical_encoder(plan["dist_lengths"])
    _write_tokens(bw, tokens, lit_enc, dist_enc)


def _write_fixed_block(bw: BitWriter, tokens: Sequence[Token], final: bool) -> None:
    lit_enc, dist_enc, _lit_len, _dist_len = _fixed_encoders()
    bw.write(1 if final else 0, 1)
    bw.write(1, 2)
    _write_tokens(bw, tokens, lit_enc, dist_enc)


def _fixed_cost_bits(lit_freq: List[int], dist_freq: List[int], extra_bits: int) -> int:
    lit_lengths, dist_lengths = _fixed_lengths()
    bits = 3 + extra_bits
    bits += sum(f * l for f, l in zip(lit_freq, lit_lengths))
    bits += sum(f * l for f, l in zip(dist_freq, dist_lengths))
    return bits


def _stored_size(data: bytes) -> int:
    blocks = max(1, (len(data) + 65534) // 65535)
    return len(data) + 5 * blocks


def deflate(data: bytes, level: int = 6) -> bytes:
    """Compress ``data`` into a raw DEFLATE stream (RFC 1951).

    Picks the cheapest of stored, fixed-Huffman and dynamic-Huffman
    encodings, so incompressible input never grows beyond a few bytes of
    stored-block overhead.
    """
    if not data:
        # An empty fixed block (BFINAL + EOB) is 2 bytes, cheaper than stored.
        bw = BitWriter()
        bw.write(1, 1)
        bw.write(1, 2)
        bw.write(0, 7)  # end-of-block, fixed code 0000000
        return bw.finish()

    # (max_chain, nice_length, insert_all) per level, zlib-flavoured.
    _LEVELS = {
        1: (4, 8, False),
        2: (8, 16, False),
        3: (16, 32, False),
        4: (16, 16, True),
        5: (32, 32, True),
        6: (64, 64, True),
        7: (96, 96, True),
        8: (128, 128, True),
        9: (256, 258, True),
    }
    max_chain, nice_length, insert_all = _LEVELS.get(level, _LEVELS[6])
    tokens = lz77_compress(data, max_chain=max_chain, nice_length=nice_length,
                           insert_all=insert_all, good_length=8)

    lit_freq, dist_freq, extra_bits = _token_frequencies(tokens)
    fixed_bits = _fixed_cost_bits(lit_freq, dist_freq, extra_bits)
    plan = _dynamic_plan(lit_freq, dist_freq, extra_bits)
    stored_bits = _stored_size(data) * 8

    best = min(fixed_bits, plan["bits"], stored_bits)
    if best == stored_bits:
        return store_deflate(data)

    bw = BitWriter()
    if best == fixed_bits:
        _write_fixed_block(bw, tokens, final=True)
    else:
        _write_dynamic_block(bw, tokens, final=True, plan=plan)
    return bw.finish()


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def _decode_symbol(reader: BitReader, table: List[int], length_table: List[int], max_bits: int) -> int:
    if max_bits == 0:
        raise ValueError("Huffman code needed but no codes were defined")
    index = reader.peek_bits(max_bits)
    symbol = table[index]
    if symbol < 0:
        raise ValueError("invalid Huffman code in DEFLATE stream")
    reader.drop(length_table[index])
    return symbol


def _inflate_tokens(reader: BitReader, lit_dec, dist_dec, out: bytearray) -> None:
    lit_table, lit_len_table, lit_max = lit_dec
    dist_table, dist_len_table, dist_max = dist_dec
    while True:
        symbol = _decode_symbol(reader, lit_table, lit_len_table, lit_max)
        if symbol < 256:
            out.append(symbol)
        elif symbol == END_OF_BLOCK:
            return
        elif symbol < MAX_LIT_SYMBOLS:
            index = symbol - 257
            length = LENGTH_BASE[index] + reader.read_bits(LENGTH_EXTRA[index])
            dsym = _decode_symbol(reader, dist_table, dist_len_table, dist_max)
            if dsym >= MAX_DIST_SYMBOLS:
                raise ValueError("invalid distance symbol in DEFLATE stream")
            distance = DIST_BASE[dsym] + reader.read_bits(DIST_EXTRA[dsym])
            if distance > len(out):
                raise ValueError("match distance reaches before start of output")
            start = len(out) - distance
            if distance >= length:
                out += out[start:start + length]
            else:
                # Overlapping copy: the source period repeats.
                chunk = bytes(out[start:])
                repeats, rem = divmod(length, distance)
                out += chunk * repeats
                out += chunk[:rem]
        else:
            raise ValueError("invalid literal/length symbol in DEFLATE stream")


def _read_dynamic_tables(reader: BitReader):
    hlit = reader.read_bits(5) + 257
    hdist = reader.read_bits(5) + 1
    hclen = reader.read_bits(4) + 4

    cl_lengths = [0] * 19
    for symbol in CL_ORDER[:hclen]:
        cl_lengths[symbol] = reader.read_bits(3)
    cl_dec = canonical_decoder(cl_lengths, max_table_bits=7)

    lengths: List[int] = []
    total = hlit + hdist
    while len(lengths) < total:
        symbol = _decode_symbol(reader, *cl_dec)
        if symbol < 16:
            lengths.append(symbol)
        elif symbol == 16:
            if not lengths:
                raise ValueError("repeat code 16 with no previous length")
            repeat = reader.read_bits(2) + 3
            lengths.extend([lengths[-1]] * repeat)
        elif symbol == 17:
            lengths.extend([0] * (reader.read_bits(3) + 3))
        elif symbol == 18:
            lengths.extend([0] * (reader.read_bits(7) + 11))
        else:
            raise ValueError("invalid code-length symbol in DEFLATE stream")
        if len(lengths) > total:
            raise ValueError("too many code lengths in dynamic block header")

    lit_lengths = lengths[:hlit]
    dist_lengths = lengths[hlit:]
    if not any(lit_lengths):
        raise ValueError("dynamic block with empty literal/length tree")
    lit_dec = canonical_decoder(lit_lengths)
    dist_dec = canonical_decoder(dist_lengths) if any(dist_lengths) else ([], [], 0)
    return lit_dec, dist_dec


def inflate(data: bytes, expected_size: int | None = None) -> bytes:
    """Decompress a raw DEFLATE stream.

    If ``expected_size`` is given, the output length is verified against it.
    """
    reader = BitReader(data)
    out = bytearray()
    while True:
        final = reader.read_bits(1)
        btype = reader.read_bits(2)
        if btype == 0:
            reader.align()
            length = reader.read_bits(16)
            nlength = reader.read_bits(16)
            if length != (nlength ^ 0xFFFF):
                raise ValueError("stored block LEN/NLEN mismatch")
            for _ in range(length):
                out.append(reader.read_bits(8))
        elif btype == 1:
            lit_lengths, dist_lengths = _fixed_lengths()
            lit_dec = canonical_decoder(lit_lengths)
            dist_dec = canonical_decoder(dist_lengths)
            _inflate_tokens(reader, lit_dec, dist_dec, out)
        elif btype == 2:
            lit_dec, dist_dec = _read_dynamic_tables(reader)
            _inflate_tokens(reader, lit_dec, dist_dec, out)
        else:
            raise ValueError("reserved DEFLATE block type 3")
        if final:
            break
    if expected_size is not None and len(out) != expected_size:
        raise ValueError(
            f"inflated size {len(out)} does not match expected {expected_size}"
        )
    return bytes(out)
