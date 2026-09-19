def test_dbg(harness):
    raw = harness.raw_client()
    raw.send(b"PUBLISH news 5\nhello")
    print("reply:", raw.read_reply())
