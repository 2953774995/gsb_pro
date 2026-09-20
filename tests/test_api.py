"""Integration tests for the management API endpoints."""

import json
import os

from helpers import request


def get_json(env, path):
    status, headers, body = request(env.connect, "GET", path)
    assert headers["content-type"].startswith("application/json")
    return status, json.loads(body)


def test_status_endpoint(env, app):
    status, data = get_json(env, "/api/status")
    assert status == 200
    assert data["status"] == "ok"
    assert data["version"]
    assert data["uptime_seconds"] >= 0
    assert data["workers"] == 4
    assert isinstance(data["requests_handled"], int)


def test_status_request_counter_increases(env):
    _, before = get_json(env, "/api/status")
    request(env.connect, "GET", "/")
    request(env.connect, "GET", "/notes.txt")
    _, after = get_json(env, "/api/status")
    assert after["requests_handled"] >= before["requests_handled"] + 2


def test_get_config_returns_defaults(env):
    status, data = get_json(env, "/api/config")
    assert status == 200
    assert data["sampling_interval_ms"] == 1000
    assert data["alarm_threshold"] == 80.0


def test_post_config_form(env):
    body = "sampling_interval_ms=250&alarm_threshold=42.5"
    status, _, resp = request(
        env.connect, "POST", "/api/config",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body)
    assert status == 200
    payload = json.loads(resp)
    assert payload["status"] == "ok"
    assert payload["config"]["sampling_interval_ms"] == 250
    assert payload["config"]["alarm_threshold"] == 42.5
    # and it is now the effective config
    _, current = get_json(env, "/api/config")
    assert current["sampling_interval_ms"] == 250


def test_post_config_json(env):
    status, _, resp = request(
        env.connect, "POST", "/api/config",
        headers={"Content-Type": "application/json"},
        body=json.dumps({"device_name": "line-3-gw", "alarm_threshold": 55}))
    assert status == 200
    payload = json.loads(resp)
    assert payload["config"]["device_name"] == "line-3-gw"
    assert payload["config"]["alarm_threshold"] == 55.0


def test_post_config_persisted_to_disk(env, app):
    request(env.connect, "POST", "/api/config",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"sampling_interval_ms": 777}))
    assert os.path.isfile(app.config.path)
    with open(app.config.path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["sampling_interval_ms"] == 777


def test_post_config_invalid_values_return_400(env):
    bad_payloads = [
        ({"sampling_interval_ms": 5}, "application/json"),      # below min
        ({"sampling_interval_ms": "abc"}, "application/json"),  # not a number
        ({"alarm_threshold": -1}, "application/json"),          # below min
        ({"unknown_key": 1}, "application/json"),               # unknown key
        ({"device_name": ""}, "application/json"),              # empty string
        ({}, "application/json"),                               # nothing to do
    ]
    for payload, ctype in bad_payloads:
        status, _, body = request(
            env.connect, "POST", "/api/config",
            headers={"Content-Type": ctype}, body=json.dumps(payload))
        assert status == 400, payload
        assert b"400" in body  # default error page explains the failure


def test_post_config_invalid_json_returns_400(env):
    status, _, body = request(
        env.connect, "POST", "/api/config",
        headers={"Content-Type": "application/json"},
        body="{not valid json")
    assert status == 400


def test_post_config_unsupported_content_type(env):
    status, _, _ = request(
        env.connect, "POST", "/api/config",
        headers={"Content-Type": "text/csv"}, body="a,b")
    assert status == 400


def test_config_survives_app_restart(www_root, tmp_path):
    from gwadmin.app import GwAdminApp, validate_config
    cfg = str(tmp_path / "config.json")
    app1 = GwAdminApp(root=str(www_root), config_path=cfg, workers=2)
    changes, err = validate_config({"sampling_interval_ms": 500})
    assert err is None
    app1.config.update(changes)
    app2 = GwAdminApp(root=str(www_root), config_path=cfg, workers=2)
    assert app2.config.get()["sampling_interval_ms"] == 500
