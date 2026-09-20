"""LZ77 tokenization: correctness of matches and window bound."""

import random

from zipmini.lz77 import compress, expand, WINDOW_SIZE, MAX_MATCH


def roundtrip(data):
    return expand(compress(data))


def test_empty():
    assert roundtrip(b"") == b""


def test_single_byte():
    assert roundtrip(b"x") == b"x"


def test_no_matches_all_literals():
    data = bytes(range(256))
    tokens = compress(data)
    assert all(isinstance(t, int) for t in tokens)
    assert roundtrip(data) == data


def test_repetition_uses_matches():
    data = b"abc" * 100
    tokens = compress(data)
    matches = [t for t in tokens if not isinstance(t, int)]
    assert matches
    assert all(d <= WINDOW_SIZE for _l, d in matches)
    assert roundtrip(data) == data


def test_match_length_capped():
    data = b"\x00" * 1000
    tokens = compress(data)
    for token in tokens:
        if not isinstance(token, int):
            length, _distance = token
            assert length <= MAX_MATCH
    assert roundtrip(data) == data


def test_window_limit_respected():
    rng = random.Random(5)
    needle = b"unique-pattern-" + bytes(rng.randrange(256) for _ in range(32))
    filler = bytes(rng.randrange(256) for _ in range(WINDOW_SIZE + 5000))
    data = needle + filler + needle
    tokens = compress(data)
    for t in tokens:
        if not isinstance(t, int):
            assert 1 <= t[1] <= WINDOW_SIZE
    assert roundtrip(data) == data


def test_random_roundtrip():
    rng = random.Random(42)
    data = bytes(rng.randrange(256) for _ in range(50000))
    assert roundtrip(data) == data


def test_mixed_roundtrip():
    rng = random.Random(1)
    parts = []
    for _ in range(20):
        if rng.random() < 0.5:
            parts.append(bytes([rng.randrange(256)]) * rng.randrange(1, 500))
        else:
            parts.append(bytes(rng.randrange(256)
                               for _ in range(rng.randrange(1, 500))))
    data = b"".join(parts)
    assert roundtrip(data) == data
