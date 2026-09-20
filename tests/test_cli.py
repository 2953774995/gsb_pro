import io
import time

from linebus.cli import EventPrinter, run_repl
from tests.testutil import attach_pair


def test_repl_ping_publish_stats_flush(server):
    client = attach_pair(server)
    commands = io.StringIO(
        "ping\n"
        "publish q/one hello world\n"
        "stats\n"
        "flush\n"
        "help\n"
        "bad command here\n"
        "quit\n"
    )
    output = io.StringIO()
    assert run_repl(client, commands, output) == 0
    text = output.getvalue()
    assert "PONG" in text
    assert "PUBLISHED 1" in text
    assert "published_events=1" in text
    assert "FLUSHED" in text
    assert "commands:" in text
    assert "ERR unknown or malformed command" in text
    client.close()


def test_event_printer_prints_realtime_event(server):
    publisher = attach_pair(server)
    subscriber = attach_pair(server)
    publisher.publish("q/cli", b"line\nwith\ttab")
    subscriber.subscribe("q/cli")

    output = io.StringIO()
    printer = EventPrinter(subscriber, output)
    printer.start()
    time.sleep(0.2)
    printer.stop()
    text = output.getvalue()
    assert "EVENT seq=1" in text
    assert "topic=q/cli" in text
    assert "payload=b'line\\nwith\\ttab'" in text
    publisher.close()
    subscriber.close()
