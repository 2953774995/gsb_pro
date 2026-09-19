"""Form-urlencoded and JSON body parsing."""

import json


def test_form_basic(client):
    resp = client.request(
        "POST",
        "/echo",
        headers=[
            ("Content-Type", "application/x-www-form-urlencoded")
        ],
        body=b"name=alice&age=30",
    )
    assert resp.status == 200
    assert resp.json() == {"name": "alice", "age": "30"}


def test_form_plus_to_space(client):
    resp = client.request(
        "POST",
        "/echo",
        headers=[
            ("Content-Type", "application/x-www-form-urlencoded")
        ],
        body=b"msg=hello+world",
    )
    assert resp.json()["msg"] == "hello world"


def test_form_percent_decoding(client):
    resp = client.request(
        "POST",
        "/echo",
        headers=[
            ("Content-Type", "application/x-www-form-urlencoded")
        ],
        body=b"msg=%E4%BD%A0%E5%A5%BD",
    )
    assert resp.json()["msg"] == "\u4f60\u597d"


def test_form_repeated_keys_become_list(client):
    resp = client.request(
        "POST",
        "/echo",
        headers=[
            ("Content-Type", "application/x-www-form-urlencoded")
        ],
        body=b"tag=a&tag=b&tag=c",
    )
    assert resp.json() == {"tag": ["a", "b", "c"]}


def test_form_empty_value(client):
    resp = client.request(
        "POST",
        "/echo",
        headers=[
            ("Content-Type", "application/x-www-form-urlencoded")
        ],
        body=b"empty=&x=1",
    )
    assert resp.json() == {"empty": "", "x": "1"}


def test_form_charset_parameter_ignored(client):
    resp = client.request(
        "POST",
        "/echo",
        headers=[
            (
                "Content-Type",
                "application/x-www-form-urlencoded; charset=utf-8",
            )
        ],
        body=b"a=b",
    )
    assert resp.status == 200


def test_json_valid(client):
    payload = {"hello": ["world", 1, True, None]}
    resp = client.request(
        "POST",
        "/json/check",
        headers=[("Content-Type", "application/json")],
        body=json.dumps(payload),
    )
    assert resp.status == 200
    assert resp.json() == {"ok": payload}


def test_json_invalid_returns_400(client):
    resp = client.request(
        "POST",
        "/json/check",
        headers=[("Content-Type", "application/json")],
        body=b"{not valid json",
    )
    assert resp.status == 400


def test_json_empty_body_returns_400(client):
    resp = client.request(
        "POST",
        "/json/check",
        headers=[("Content-Type", "application/json")],
        body=b"",
    )
    assert resp.status == 400


def test_empty_body_on_post_is_fine_for_non_json_route(client):
    resp = client.request("POST", "/echo")
    assert resp.status == 200
    assert resp.json() == {}
