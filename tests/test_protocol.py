import io

import pytest

from minibroker import protocol
from minibroker.protocol import (
    CommandTooLarge,
    ProtocolError,
    is_valid_pattern,
    is_valid_topic,
    read_frame,
)


def decode(data, max_command=protocol.DEFAULT_MAX_COMMAND):
    return read_frame(io.BytesIO(data), max_command=max_command)


def test_simple_command_roundtrip():
    tokens, payload = decode(protocol.encode_command("PING"))
    assert tokens == ["PING"]
    assert payload is None


def test_empty_payload_roundtrip():
    tokens, payload = decode(protocol.encode_command("PUBLISH", ["t"], b""))
    assert tokens == ["PUBLISH", "t", "0"]
    assert payload == b""


def test_payload_with_spaces_tabs_newlines_roundtrip():
    original = b"hello world\twith\ttabs\nand\nnewlines\r\n!"
    tokens, payload = decode(protocol.encode_command("PUBLISH", ["t"], original))
    assert tokens[:2] == ["PUBLISH", "t"]
    assert payload == original


def test_binary_payload_roundtrip():
    original = bytes(range(256))
    _, payload = decode(protocol.encode_command("PUBLISH", ["bin"], original))
    assert payload == original


def test_message_frame_roundtrip():
    data = protocol.encode_message(42, "news", b"hi there")
    tokens, payload = decode(data)
    assert tokens == ["MSG", "42", "news", "8"]
    assert payload == b"hi there"


def test_multiple_frames_in_stream():
    data = (protocol.encode_command("PING")
            + protocol.encode_command("PUBLISH", ["t"], b"ab")
            + protocol.encode_command("PING"))
    stream = io.BytesIO(data)
    assert read_frame(stream)[0] == ["PING"]
    assert read_frame(stream) == (["PUBLISH", "t", "2"], b"ab")
    assert read_frame(stream)[0] == ["PING"]


def test_oversized_header_rejected():
    with pytest.raises(CommandTooLarge):
        decode(b"PING " + b"x" * 100 + b"\n", max_command=16)


def test_oversized_payload_rejected():
    frame = protocol.encode_command("PUBLISH", ["t"], b"x" * 100)
    with pytest.raises(CommandTooLarge):
        decode(frame, max_command=32)


def test_header_exactly_at_limit_accepted():
    frame = protocol.encode_command("PING")
    assert len(frame) == 5
    tokens, _ = decode(frame, max_command=4)
    assert tokens == ["PING"]


def test_missing_payload_length_rejected():
    with pytest.raises(ProtocolError):
        decode(b"PUBLISH\n")


def test_invalid_payload_length_rejected():
    with pytest.raises(ProtocolError):
        decode(b"PUBLISH t notanumber\n")


def test_negative_payload_length_rejected():
    with pytest.raises(ProtocolError):
        decode(b"PUBLISH t -3\n")


def test_missing_payload_terminator_rejected():
    with pytest.raises(ProtocolError):
        decode(b"PUBLISH t 3\nabcX")


def test_truncated_payload_raises_eof():
    with pytest.raises(EOFError):
        decode(b"PUBLISH t 10\nabc")


def test_empty_line_rejected():
    with pytest.raises(ProtocolError):
        decode(b"\n")


def test_eof_raises():
    with pytest.raises(EOFError):
        decode(b"")


def test_non_utf8_header_rejected():
    with pytest.raises(ProtocolError):
        decode(b"PING \xff\xfe\n")


@pytest.mark.parametrize("topic", ["", "has space", "tab\ttab", "new\nline",
                                   "wild*card", "\x01ctrl", "del\x7f"])
def test_invalid_topics(topic):
    assert not is_valid_topic(topic)


@pytest.mark.parametrize("topic", ["a", "news", "a/b/c", "foo-bar_1.2"])
def test_valid_topics(topic):
    assert is_valid_topic(topic)


@pytest.mark.parametrize("pattern, ok", [
    ("news", True),
    ("news/*", True),
    ("a/b/*", True),
    ("*", False),
    ("/*", False),
    ("news/*/x", False),
    ("news/* ", False),
    ("", False),
])
def test_pattern_validation(pattern, ok):
    assert is_valid_pattern(pattern) is ok
