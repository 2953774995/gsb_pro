import io

import pytest

from linebus.protocol import (
    DEFAULT_MAX_COMMAND_SIZE,
    CommandTooLargeError,
    ProtocolError,
    encode_error,
    encode_event,
    encode_publish,
    encode_simple,
    encode_subscribe,
    encode_unsubscribe,
    read_frame,
    topic_matches,
    validate_topic,
)


def parse(data, limit=DEFAULT_MAX_COMMAND_SIZE):
    return read_frame(io.BytesIO(data), limit)


def test_empty_payload_roundtrip():
    frame = parse(b"PUBLISH quality/camera-1 0\n")
    assert frame.parts == ("PUBLISH", "quality/camera-1", "0")
    assert frame.payload == b""
    assert encode_publish("quality/camera-1", b"") == b"PUBLISH quality/camera-1 0\n"


def test_payload_with_spaces_tabs_newlines_nul_roundtrip():
    payload = b"space tab\there \n cr\r nul\0 end"
    frame = parse(encode_publish("q", payload))
    assert frame.payload == payload
    assert frame.parts == ("PUBLISH", "q", str(len(payload)))
    assert parse(encode_event(7, "q", payload)).payload == payload


def test_cr_lf_header_and_control_commands():
    assert parse(b"PING\r\n").parts == ("PING",)
    assert encode_simple("ping") == b"PING\n"
    assert encode_subscribe("q") == b"SUBSCRIBE q\n"
    assert encode_unsubscribe("q") == b"UNSUBSCRIBE q\n"


def test_unexpected_eof():
    with pytest.raises(ProtocolError):
        parse(b"PUBLISH q 5\nab")
    with pytest.raises(ProtocolError):
        parse(b"PUBLISH q bad\n")
    stream = io.BytesIO(b"SUBSCRIBE q\nextra\n")
    first = read_frame(stream)
    assert first.parts == ("SUBSCRIBE", "q")
    assert read_frame(stream).parts == ("extra",)


def test_oversized_command_payload_returns_size_error_and_drains():
    payload = b"x" * DEFAULT_MAX_COMMAND_SIZE
    stream = io.BytesIO(encode_publish("q", payload) + b"PING\n")
    with pytest.raises(CommandTooLargeError):
        read_frame(stream)
    assert read_frame(stream).parts == ("PING",)


def test_oversized_header():
    topic = "q" + "a" * DEFAULT_MAX_COMMAND_SIZE
    with pytest.raises(CommandTooLargeError):
        parse(encode_subscribe(topic))


def test_topic_validation_and_wildcards():
    assert validate_topic("quality/camera-1") == "quality/camera-1"
    assert validate_topic("quality/*", allow_wildcard=True)
    for invalid in ["with space", "tab\t", "newline\n", "nul\0", "*", "a/*/b", "*/x", "x//*"]:
        with pytest.raises(ProtocolError):
            validate_topic(invalid)
        with pytest.raises(ProtocolError):
            validate_topic(invalid, allow_wildcard=True)
    with pytest.raises(ProtocolError):
        validate_topic("star*")
    assert topic_matches("quality/*", "quality/camera1")
    assert topic_matches("quality/*", "quality")
    assert not topic_matches("quality/*", "other/camera1")


def test_error_frame_text_can_contain_spaces():
    frame = parse(encode_error("queue full retry later"))
    assert frame.parts == ("ERR", "queue", "full", "retry", "later")
