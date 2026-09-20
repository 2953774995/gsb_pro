import pytest

from linebus.protocol import (
    CommandTooLargeError,
    ProtocolParseError,
    ProtocolParser,
    encode_command,
    encode_event,
    encode_publish,
)


def test_empty_payload_roundtrip():
    frame = encode_publish("cam/a", b"")
    assert frame == b"PUBLISH cam/a 0\n\n"
    messages = ProtocolParser().feed(frame)
    assert len(messages) == 1
    assert messages[0].command == "PUBLISH"
    assert messages[0].topic == "cam/a"
    assert messages[0].payload == b""


def test_payload_with_spaces_tabs_newlines_and_nul_roundtrip():
    payload = b" pass \t fail \n second line \x00 end"
    topic = "camera line/1"
    frame = encode_publish(topic, payload)
    messages = ProtocolParser().feed(frame)
    assert messages[0].topic == topic
    assert messages[0].payload == payload


def test_parser_accepts_arbitrary_incremental_splits():
    frame = encode_publish("a/b", b"x" * 20) + encode_command("PING")
    parser = ProtocolParser()
    all_messages = []
    for i in range(len(frame)):
        all_messages.extend(parser.feed(frame[i : i + 1]))
    assert [m.command for m in all_messages] == ["PUBLISH", "PING"]


def test_event_parser_roundtrip():
    frame = encode_event(42, "a/b", b"\n1\n")
    message = ProtocolParser().feed(frame)[0]
    assert message.is_event
    assert (message.sequence, message.topic, message.payload) == (42, "a/b", b"\n1\n")


def test_too_large_advertised_payload_rejected():
    with pytest.raises(CommandTooLargeError):
        ProtocolParser(max_command_size=10).feed(b"PUBLISH a 11\n")


def test_too_large_unterminated_command_rejected():
    with pytest.raises(CommandTooLargeError):
        ProtocolParser(max_command_size=10).feed(b"X" * 11)


def test_malformed_binary_topic_is_fatal():
    with pytest.raises(ProtocolParseError):
        ProtocolParser().feed(b"SUBSCRIBE \xff\n")


def test_unknown_command_is_parse_message_not_fatal():
    messages = ProtocolParser().feed(b"NOPE arg\nPING\n")
    assert [m.command for m in messages] == ["NOPE", "PING"]


def test_length_requires_decimal_and_terminator():
    with pytest.raises(ProtocolParseError):
        ProtocolParser().feed(b"PUBLISH a x\n")
    with pytest.raises(ProtocolParseError):
        ProtocolParser().feed(b"PUBLISH a 1\nxy")


def test_multiple_commands_same_buffer():
    frames = (
        encode_command("SUBSCRIBE", "a")
        + encode_publish("a", b"one")
        + encode_command("UNSUBSCRIBE", "a")
    )
    messages = ProtocolParser().feed(frames)
    assert [m.command for m in messages] == ["SUBSCRIBE", "PUBLISH", "UNSUBSCRIBE"]
