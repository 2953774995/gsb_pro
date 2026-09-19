"""Disconnect handling, protocol errors, shutdown behaviour."""

import socket

import pytest

from minibroker.errors import BrokerShutdown, ServerError
from tests.conftest import RawClient, drain, wait_until


def test_subscriber_disconnect_does_not_affect_others(harness):
    doomed = harness.client()
    survivor = harness.client()
    pub = harness.client()
    doomed.subscribe("t")
    survivor.subscribe("t")
    pub.publish("t", b"before-disconnect")
    assert doomed.next_message(2)[2] == b"before-disconnect"
    assert survivor.next_message(2)[2] == b"before-disconnect"

    doomed.close()
    # broker must keep publishing to the survivor
    for i in range(5):
        pub.publish("t", b"after-%d" % i)
    msgs = drain(survivor, 5)
    assert [m[2] for m in msgs] == [b"after-%d" % i for i in range(5)]
    survivor.close()
    pub.close()


def test_publisher_disconnect_is_clean(harness):
    pub = harness.client()
    pub.publish("t", b"x")
    pub.close()
    probe = harness.client()
    assert probe.ping() is True
    probe.close()


def test_abrupt_socket_close_mid_connection(harness):
    raw = harness.raw_client()
    assert raw.command("PING")[0] == "PONG"
    raw.sock.close()
    probe = harness.client()
    assert probe.ping() is True
    probe.close()


def test_subscriber_reconnect_gets_retained_backlog(aof_path):
    from tests.conftest import BrokerHarness

    h = BrokerHarness(aof_path)
    try:
        sub = h.client()
        pub = h.client()
        sub.subscribe("t")
        pub.publish("t", b"one")
        assert sub.next_message(2)[2] == b"one"
        sub.close()
        pub.publish("t", b"while-away")
        sub2 = h.client()
        sub2.subscribe("t")
        assert sub2.next_message(2)[2] == b"one"
        assert sub2.next_message(2)[2] == b"while-away"
        sub2.close()
        pub.close()
    finally:
        h.stop()


# ---------------------------------------------------------------------- #
# protocol errors over the wire
# ---------------------------------------------------------------------- #
def test_malformed_commands_return_errors(harness):
    raw = harness.raw_client()
    raw.send(b"BOGUS something\n")
    assert raw.read_reply()[0] == "ERR"
    raw.send(b"PING extra-arg\n")
    assert raw.read_reply()[0] == "ERR"
    raw.send(b"PUBLISH  bad 3\nabc")
    assert raw.read_reply()[0] == "ERR"
    raw.send(b"SUBSCRIBE\n")
    assert raw.read_reply()[0] == "ERR"
    raw.send(b"PUBLISH t notanumber\n")
    assert raw.read_reply()[0] == "ERR"
    # connection still works
    raw.send(b"PING\n")
    assert raw.read_reply()[0] == "PONG"
    raw.close()


def test_publish_with_bad_topic_via_client(harness):
    client = harness.client()
    with pytest.raises(Exception):
        client.publish("bad topic", b"x")
    with pytest.raises(Exception):
        client.publish("", b"x")
    client.close()


def test_oversized_command_line_returns_error_and_continues(harness):
    raw = harness.raw_client()
    huge = b"SUBSCRIBE " + b"a" * (2 * 1024 * 1024) + b"\n"
    raw.send(huge)
    reply = raw.read_reply()
    assert reply[0] == "ERR" and "too large" in reply[1]
    raw.close()


def test_oversized_payload_returns_error(harness):
    raw = harness.raw_client()
    # broker default limit is 1 MiB
    raw.send(b"PUBLISH t 2000000\n" + b"x")
    reply = raw.read_reply()
    assert reply[0] == "ERR" and "too large" in reply[1]
    raw.close()


def test_truncated_payload_closes_connection_cleanly(harness):
    raw = harness.raw_client()
    raw.send(b"PUBLISH t 5\nabc")
    reply = raw.read_reply()
    assert reply[0] == "ERR"
    # server closed the socket; further reads show EOF
    raw.sock.settimeout(2)
    assert raw.sock.recv(16) == b""
    raw.close()


def test_garbage_bytes_do_not_crash_broker(harness):
    raw = harness.raw_client()
    raw.send(b"\xff\xfe\x00garbage\n")
    assert raw.read_reply()[0] == "ERR"
    raw.send(b"\n\n\n")
    assert raw.read_reply()[0] == "ERR"
    raw.close()
    probe = harness.client()
    assert probe.ping() is True
    probe.close()


# ---------------------------------------------------------------------- #
# flush / shutdown
# ---------------------------------------------------------------------- #
def test_flush_command(harness):
    pub = harness.client()
    pub.publish("t", b"x")
    pub.flush()
    sub = harness.client()
    sub.subscribe("t")
    assert sub.next_message(timeout=0.2) is None
    sub.close()
    pub.close()


def test_shutdown_notifies_clients_with_bye(harness):
    client = harness.client()
    client.ping()
    admin = harness.client()
    with pytest.raises(BrokerShutdown):
        admin.shutdown()
    with pytest.raises(BrokerShutdown):
        # pending queue empty -> immediately informed by +BYE
        client.next_message(timeout=3)
    assert harness.server.broker.shutdown_event.wait(3)


def test_shutdown_with_pending_subscriber(harness):
    sub = harness.client()
    admin = harness.client()
    sub.subscribe("t")
    admin.publish("t", b"last")
    topic, seq, payload = sub.next_message(2)
    assert payload == b"last"
    admin2 = harness.client()
    with pytest.raises(BrokerShutdown):
        admin2.shutdown()
    with pytest.raises(BrokerShutdown):
        sub.next_message(timeout=3)
    admin.close()
