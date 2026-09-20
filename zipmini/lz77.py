"""LZ77 matching over a 32KB sliding window using hash chains.

Each position's 3-byte prefix is hashed into a bucket; buckets hold a
linked list (via the ``prev`` array) of recent positions with the same
hash, most recent first.  Match search walks the chain from the most
recent position, which finds close (cheap-to-encode) matches first.
"""

MIN_MATCH = 3
MAX_MATCH = 258
WINDOW_SIZE = 32768
HASH_BITS = 15
HASH_SIZE = 1 << HASH_BITS


def _hash3(data, i):
    return ((data[i] << 10) ^ (data[i + 1] << 5) ^ data[i + 2]) & (HASH_SIZE - 1)


def compress(data, max_chain=128, nice_length=128, lazy=True):
    """Tokenize ``data`` into a list of LZ77 tokens.

    A token is either an int (a literal byte value 0..255) or a
    ``(length, distance)`` match tuple with 3 <= length <= 258 and
    1 <= distance <= 32768.
    """
    n = len(data)
    head = [-1] * HASH_SIZE
    prev = [-1] * n
    tokens = []
    append = tokens.append

    def insert(p):
        if p + MIN_MATCH <= n:
            h = _hash3(data, p)
            prev[p] = head[h]
            head[h] = p

    def longest_match(i):
        if i + MIN_MATCH > n:
            return 0, 0
        j = head[_hash3(data, i)]
        best_len = MIN_MATCH - 1
        best_dist = 0
        limit = i - WINDOW_SIZE
        if limit < 0:
            limit = 0
        max_len = n - i
        if max_len > MAX_MATCH:
            max_len = MAX_MATCH
        chain = max_chain
        while j >= limit and chain > 0 and best_len < max_len:
            # Quick reject: a better match must extend past best_len.
            if data[j + best_len] == data[i + best_len]:
                l = 0
                while l < max_len and data[j + l] == data[i + l]:
                    l += 1
                if l > best_len:
                    best_len = l
                    best_dist = i - j
                    if l >= nice_length:
                        break
            j = prev[j]
            chain -= 1
        if best_len >= MIN_MATCH:
            return best_len, best_dist
        return 0, 0

    i = 0
    while i < n:
        mlen, mdist = longest_match(i)
        if lazy and mlen and mlen < nice_length and i + 1 < n:
            # Lazy evaluation: emit a literal if the next position
            # produces a strictly longer match.
            insert(i)
            nlen2, _ndist2 = longest_match(i + 1)
            if nlen2 > mlen:
                append(data[i])
                i += 1
                continue
            append((mlen, mdist))
            for p in range(i + 1, i + mlen):
                insert(p)
            i += mlen
        elif mlen:
            append((mlen, mdist))
            for p in range(i, i + mlen):
                insert(p)
            i += mlen
        else:
            append(data[i])
            insert(i)
            i += 1
    return tokens


def expand(tokens):
    """Rebuild the original data from a token list (inverse of compress)."""
    out = bytearray()
    for t in tokens:
        if isinstance(t, int):
            out.append(t)
        else:
            length, dist = t
            start = len(out) - dist
            if start < 0:
                raise ValueError("match distance beyond start of data")
            if dist >= length:
                out += out[start:start + length]
            else:
                piece = out[start:]
                piece = (piece * (length // dist + 1))[:length]
                out += piece
    return bytes(out)
