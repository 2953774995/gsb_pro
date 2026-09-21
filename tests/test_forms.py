import pytest

from gwadmin.errors import BadRequest
from gwadmin.forms import parse_form, parse_json_body


def test_form_percent_plus_and_repeat_keys():
    assert parse_form(b"a=hello+world&b=%31%32&a=two") == {
        "a": ["hello world", "two"],
        "b": "12",
    }


def test_form_rejects_bad_percent_encoding():
    with pytest.raises(BadRequest):
        parse_form(b"a=%zz")


def test_json_parser_rejects_invalid_json():
    assert parse_json_body(b'{"ok": true}') == {"ok": True}
    with pytest.raises(BadRequest):
        parse_json_body(b"{bad")
    with pytest.raises(BadRequest):
        parse_json_body(b"")
