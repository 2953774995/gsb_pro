"""Protocol parser / serializer boundary tests."""

import io

import pytest

from minibroker import protocol
from minibroker.protocol import (
    ProtocolError,
    encode_msg,
    encode_publish,
    parse_msg_header,
    pattern_matches,
    read_exact,
    read_line,
    validate_pattern,
    validate_topic,
)


# -- read_line ---------------------------------------------------------------

def test_read_line_simple():
    assert read_line(io.BytesIO(b"PING\n"), 100) == b"PING"


def test_read_line_empty_line():
    assert read_line(io.BytesIO(b"\n"), 100) == b""


def test_read_line_eof():
    with pytest.raises(EOFError):
        read_line(io.BytesIO(b""), 100)


def test_read_line_exactly_at_limit():
    data = b"x" * 10 + b"\n"
    assert read_line(io.BytesIO(data), 10) == b"x" * 10


def test_read_line_over_limit_raises_and_resyncs():
    stream = io.BytesIO(b"x" * 50 + b"\nPING\n")
    with pytest.raises(ProtocolError):
        read_line(stream, 10)
    # stream must be resynchronised: the next line parses fine
    assert read_line(stream, 10) == b"PING"


def test_read_exact():
    assert read_exact(io.BytesIO(b"abcdef"), 3) == b"abc"


def test_read_exact_eof():
    with pytest.raises(EOFError):
        read_exact(io.BytesIO(b"ab"), 5)


# -- publish frame round trip -------------------------------------------------

def roundtrip(topic, payload):
    frame = encode_publish(topic, payload)
    stream = io.BytesIO(frame)
    header = read_line(stream, 1 << 20)
    parts = protocol.parse_command_line(header)
    assert parts[0] == b"PUBLISH"
    assert parts[1].decode() == topic
    assert int(parts[2]) == len(payload)
    assert read_exact(stream, int(parts[2])) == payload
    assert stream.read() == b""


def test_roundtrip_empty_payload():
    roundtrip("t", b"")


def test_roundtrip_payload_with_spaces_tabs_newlines():
    roundtrip("topic", b"hello world\twith\ttabs\nand\nnewlines\r\n")


def test_roundtrip_binary_payload():
    roundtrip("bin", bytes(range(256)))


def test_roundtrip_unicode_payload():
    payload = "héllo wörld 你好".encode("utf-8")
    roundtrip("t", payload)


# -- MSG frame round trip ------------------------------------------------------

def test_msg_frame_roundtrip():
    frame = encode_msg(42, "news/a", b"pay\nload")
    stream = io.BytesIO(frame)
    seq, topic, length = parse_msg_header(read_line(stream, 1 << 20))
    assert (seq, topic, length) == (42, "news/a", 8)
    assert read_exact(stream, length) == b"pay\nload"


def test_parse_msg_header_malformed():
    with pytest.raises(ProtocolError):
        parse_msg_header(b"MSG notanum topic 3")
    with pytest.raises(ProtocolError):
        parse_msg_header(b"MSG 1 topic -5")
    with pytest.raises(ProtocolError):
        parse_msg_header(b"MSG 1 topic")


# -- topic validation ----------------------------------------------------------

@pytest.mark.parametrize("topic", ["news", "a/b/c", "x.y-z_1", "新闻"])
def test_valid_topics(topic):
    validate_topic(topic)


@pytest.mark.parametrize(
    "topic",
    ["", "has space", "tab\there", "new\nline", "ctrl\x01char", "\x7f", "wild*card"],
)
def test_invalid_topics(topic):
    with pytest.raises(ValueError):
        validate_topic(topic)


def test_topic_too_long():
    with pytest.raises(ValueError):
        validate_topic("x" * 513)


@pytest.mark.parametrize("pattern", ["news/*", "a/b/*", "plain"])
def test_valid_patterns(pattern):
    validate_pattern(pattern)


@pytest.mark.parametrize("pattern", ["/*", "", "a b/*", "*/x", "a/*/b"])
def test_invalid_patterns(pattern):
    with pytest.raises(ValueError):
        validate_pattern(pattern)


# -- wildcard matching ---------------------------------------------------------

@pytest.mark.parametrize(
    "pattern,topic,expected",
    [
        ("news/*", "news/a", True),
        ("news/*", "news/a/b", True),
        ("news/*", "news", False),
        ("news/*", "news/", False),
        ("news/*", "other/a", False),
        ("plain", "plain", True),
        ("plain", "plain/x", False),
        ("plain", "other", False),
    ],
)
def test_pattern_matches(pattern, topic, expected):
    assert pattern_matches(pattern, topic) is expected
