import socket

import pytest

from minibroker import protocol
from minibroker.client import ServerError


def test_frame_roundtrip_arbitrary_bytes():
    payload = b" spaces \t tabs \r\n newlines \x00 binary \xff end"
    frame = protocol.encode_frame([b"PUBLISH", b"topic/name", payload])
    parsed = protocol.read_frame_from_bytes(frame)
    assert parsed == [b"PUBLISH", b"topic/name", payload]


def test_frame_roundtrip_empty_payload():
    frame = protocol.encode_frame([b"PUBLISH", b"t", b""])
    assert protocol.read_frame_from_bytes(frame) == [b"PUBLISH", b"t", b""]


def test_command_and_reply_codecs():
    assert protocol.encode_command("PING") == b"*1\r\n$4\r\nPING\r\n"
    assert protocol.encode_ok("PONG") == b"+PONG\r\n"
    assert protocol.encode_error("bad") == b"-ERR bad\r\n"
    assert protocol.encode_integer(7) == b":7\r\n"
    pub = protocol.encode_pub(9, b"t", b"x")
    assert protocol.read_frame_from_bytes(pub) == [b"PUB", b"9", b"t", b"x"]


def test_reply_parser_types():
    assert protocol.read_value_from_bytes(b"+PONG\r\n") == b"PONG"
    assert protocol.read_value_from_bytes(b":123\r\n") == 123
    assert protocol.read_value_from_bytes(b"$3\r\nabc\r\n") == b"abc"
    array = protocol.encode_frame([b"STATS", b"topics", b"2"])
    assert protocol.read_value_from_bytes(array) == [b"STATS", b"topics", b"2"]


def test_oversized_frame_rejected():
    frame = protocol.encode_frame([b"PUBLISH", b"t", b"x" * (1024 * 1024)])
    assert len(frame) > 1024 * 1024
    with pytest.raises(protocol.ProtocolError, match="maximum size"):
        protocol.read_frame_from_bytes(frame, max_size=1024 * 1024)


@pytest.mark.parametrize(
    "bad",
    [
        b"NOPE\r\n",
        b"*0\r\n",
        b"*2\r\n$3\r\nabc\r\n",
        b"*1\r\n$3\r\nabc",
        b"*1\r\n$-1\r\n",
        b"*1\r\n$3\r\nab\r\n",
    ],
)
def test_malformed_frames(bad):
    with pytest.raises((protocol.ProtocolError, EOFError)):
        protocol.read_frame_from_bytes(bad)


def test_error_reply_is_server_error_text():
    reply = protocol.read_value_from_bytes(protocol.encode_error("bad topic"))
    assert reply == b"ERR bad topic"


def test_noncanonical_or_signed_headers_rejected():
    bad_frames = [
        b"*01\r\n$1\r\na\r\n",
        b"*1\r\n$+1\r\na\r\n",
        b"*1\r\n$01\r\na\r\n",
    ]
    for frame in bad_frames:
        with pytest.raises(protocol.ProtocolError):
            protocol.read_frame_from_bytes(frame)
