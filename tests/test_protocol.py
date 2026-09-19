"""Protocol parser / serializer edge cases."""

import io

import pytest

from minibroker.errors import ProtocolError
from minibroker.protocol import (
    CommandReader,
    ReplyReader,
    encode_command,
    error,
    integer,
    message,
    ok,
    pong,
    parse_command_line,
    stats_reply,
    topic_matches,
    validate_subscription_topic,
    validate_topic,
)


def read_commands(blob, max_command_size=1024):
    reader = CommandReader(io.BytesIO(blob), max_command_size=max_command_size)
    cmds = []
    while True:
        cmd = reader.read_command()
        if cmd is None:
            break
        if cmd.name == "PUBLISH":
            reader.read_payload(cmd)
        cmds.append(cmd)
    return cmds


# ---------------------------------------------------------------------- #
# serialization round trips
# ---------------------------------------------------------------------- #
def test_empty_payload_roundtrip():
    frame = encode_command("PUBLISH", "t", payload=b"")
    [cmd] = read_commands(frame)
    assert cmd.name == "PUBLISH"
    assert cmd.args == ["t"]
    assert cmd.payload == b""


def test_payload_with_spaces_tabs_newlines_roundtrip():
    payload = b"a b\tc\nd\r\n x\xff\x00binary"
    frame = encode_command("PUBLISH", "t", payload=payload)
    [cmd] = read_commands(frame)
    assert cmd.payload == payload


def test_two_commands_framed_back_to_back():
    frame = (
        encode_command("PUBLISH", "t", payload=b"hello\nworld")
        + encode_command("PING")
    )
    cmds = read_commands(frame)
    assert [c.name for c in cmds] == ["PUBLISH", "PING"]
    assert cmds[0].payload == b"hello\nworld"


def test_simple_commands_parse():
    assert parse_command_line(b"ping").name == "PING"
    cmd = parse_command_line(b"SUBSCRIBE news/sports")
    assert cmd.name == "SUBSCRIBE" and cmd.args == ["news/sports"]


def test_command_case_insensitive():
    [cmd] = read_commands(b"StAtS\n")
    assert cmd.name == "STATS"


def test_crlf_tolerated():
    [cmd] = read_commands(b"PING\r\n")
    assert cmd.name == "PING"


def test_reply_encoders():
    assert ok() == b"+OK OK\n"
    assert ok("SUBSCRIBED t") == b"+SUBSCRIBED t\n"
    assert error("bad") == b"-ERR bad\n"
    assert pong() == b"+PONG\n"
    assert integer(7) == b":7\n"
    assert message("t", 3, b"ab") == b"MSG t 3 2\nab"
    assert stats_reply([("a", 1), ("b", 2)]) == b"+STATS 2\na=1\nb=2\n"


def test_reply_reader_parses_all_reply_types():
    blob = pong() + integer(5) + ok("FLUSHED") + error("nope") + stats_reply([("x", "1")])
    reader = ReplyReader(io.BytesIO(blob))
    assert reader.read_reply()[0] == "PONG"
    reply = reader.read_reply()
    assert reply == ("INT", 5)
    assert reader.read_reply() == ("OK", "FLUSHED")
    assert reader.read_reply() == ("ERR", "nope")
    kind, stats = reader.read_reply()
    assert kind == "STATS" and stats == {"x": "1"}


def test_message_reply_roundtrip():
    payload = b"line1\nline2\t\x00"
    reader = ReplyReader(io.BytesIO(message("t", 9, payload)))
    assert reader.read_reply() == ("MSG", "t", 9, payload)


# ---------------------------------------------------------------------- #
# malformed input
# ---------------------------------------------------------------------- #
def test_unknown_command():
    with pytest.raises(ProtocolError):
        parse_command_line(b"FOO bar")


def test_wrong_arity():
    with pytest.raises(ProtocolError):
        parse_command_line(b"PING extra")
    with pytest.raises(ProtocolError):
        parse_command_line(b"SUBSCRIBE")
    with pytest.raises(ProtocolError):
        parse_command_line(b"PUBLISH t")


def test_bad_length_field():
    with pytest.raises(ProtocolError):
        parse_command_line(b"PUBLISH t -1")
    with pytest.raises(ProtocolError):
        parse_command_line(b"PUBLISH t abc")


def test_invalid_topics():
    for bad in ["", " ", "a b", "a\tb", "a\nb", "a\x00b", "x\x7f"]:
        with pytest.raises(ProtocolError):
            validate_topic(bad)
        with pytest.raises(ProtocolError):
            encode_command("PUBLISH", bad, payload=b"x")


def test_wildcard_topic_validation():
    validate_subscription_topic("*")
    validate_subscription_topic("news/*")
    with pytest.raises(ProtocolError):
        validate_subscription_topic("*/x")
    with pytest.raises(ProtocolError):
        validate_subscription_topic("a b/*")
    # wildcards are only valid for subscriptions, not publishing
    with pytest.raises(ProtocolError):
        validate_topic("news/*")


def test_topic_matching():
    assert topic_matches("news/*", "news")
    assert topic_matches("news/*", "news/sports")
    assert topic_matches("news/*", "news/sports/local")
    assert not topic_matches("news/*", "newsletter")
    assert topic_matches("*", "anything/at/all")
    assert topic_matches("exact", "exact")
    assert not topic_matches("exact", "other")


def test_oversized_command_line_rejected():
    reader = CommandReader(io.BytesIO(b"PUBLISH t 999999999\n"), max_command_size=16)
    with pytest.raises(ProtocolError):
        reader.read_command()


def test_oversized_payload_rejected():
    frame = b"PUBLISH t 100\n" + b"x" * 100
    reader = CommandReader(io.BytesIO(frame), max_command_size=50)
    cmd = reader.read_command()
    with pytest.raises(ProtocolError):
        reader.read_payload(cmd)


def test_truncated_payload_is_error():
    frame = b"PUBLISH t 5\nabc"
    reader = CommandReader(io.BytesIO(frame))
    cmd = reader.read_command()
    with pytest.raises(ProtocolError):
        reader.read_payload(cmd)


def test_empty_line_is_protocol_error():
    with pytest.raises(ProtocolError):
        read_commands(b"\nPING\n")
