"""POST form / JSON body parsing."""

from conftest import request

FORM_CT = {"Content-Type": "application/x-www-form-urlencoded"}
JSON_CT = {"Content-Type": "application/json"}


def test_form_basic(addr):
    status, _, body = request(addr, "POST", "/submit", headers=FORM_CT,
                              body="a=1&b=2")
    assert status == 200 and body == b"a=1&b=2"


def test_form_plus_and_percent_decoding(addr):
    # '+' becomes space, %XX is decoded: %41='A' %26='&' %3D='='
    status, _, body = request(addr, "POST", "/submit", headers=FORM_CT,
                              body="name=hello+world&sym=%41%26%3D")
    assert status == 200
    assert body == "name=hello world&sym=A&=".encode("utf-8")


def test_form_repeated_keys_aggregate(addr):
    status, _, body = request(addr, "POST", "/submit", headers=FORM_CT,
                              body="tag=x&tag=y&tag=z")
    assert status == 200 and body == b"tag=x,y,z"


def test_form_blank_values(addr):
    status, _, body = request(addr, "POST", "/submit", headers=FORM_CT,
                              body="empty=&full=1")
    assert status == 200 and body == b"empty=&full=1"


def test_form_non_form_content_type(addr):
    # form parsing only applies to urlencoded bodies
    status, _, body = request(addr, "POST", "/submit",
                              headers={"Content-Type": "text/plain"},
                              body="a=1")
    assert status == 200 and body == b""


def test_json_valid(addr):
    status, headers, body = request(addr, "POST", "/json", headers=JSON_CT,
                                    body='{"a": 1, "b": [2, 3]}')
    assert status == 200
    assert body == b'{"got": {"a": 1, "b": [2, 3]}}'
    assert headers["content-type"] == "application/json"


def test_json_invalid_returns_400(addr):
    status, _, body = request(addr, "POST", "/json", headers=JSON_CT,
                              body="{not json")
    assert status == 400
    assert b"400" in body


def test_json_scalar(addr):
    status, _, body = request(addr, "POST", "/json", headers=JSON_CT,
                              body='"just a string"')
    assert status == 200
    assert b"just a string" in body


def test_post_binary_echo(addr):
    payload = bytes(range(256)) * 4
    status, _, body = request(addr, "POST", "/echo",
                              headers={"Content-Type": "application/octet-stream"},
                              body=payload)
    assert status == 200 and body == payload
