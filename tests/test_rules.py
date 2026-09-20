"""内置敏感信息规则包测试：四类规则的命中与脱敏结果。"""

import pytest

from datamask import PatternError
from datamask.rules import RULES, detect, get_rule, mask


def test_rules_registry():
    assert set(RULES) == {"mobile", "idcard", "bankcard", "email"}


def test_mobile_detect_and_mask():
    text = "客户手机 13812345678，备用 19900001111"
    hits = detect(text, "mobile")
    assert [h["text"] for h in hits] == ["13812345678", "19900001111"]
    assert mask(text, "mobile") == "客户手机 138****5678，备用 199****1111"


def test_mobile_rejects_bad_prefix():
    assert detect("12345678901", "mobile") == []   # 12x 不是合法号段
    assert detect("1381234567", "mobile") == []    # 只有 10 位


def test_idcard_detect_and_mask():
    text = "身份证号 11010119900307123X 请核实"
    hits = detect(text, "idcard")
    assert hits[0]["text"] == "11010119900307123X"
    assert hits[0]["groups"] == ("110101", "19900307", "123X")
    assert mask(text, "idcard") == "身份证号 110101********123X 请核实"


def test_idcard_lowercase_x():
    assert detect("11010119900307123x", "idcard") != []


def test_bankcard_detect_and_mask():
    text = "卡号 6222021234567890123"
    hits = detect(text, "bankcard")
    assert hits[0]["text"] == "6222021234567890123"
    # 19 位：前 4 + 11 个 * + 后 4
    assert mask(text, "bankcard") == "卡号 6222***********0123"


def test_bankcard_16_digits():
    assert mask("卡 6222021234567890", "bankcard") == "卡 6222********7890"


def test_email_detect_and_mask():
    text = "邮箱 alice.w+tag@gmail.com 备用"
    hits = detect(text, "email")
    assert hits[0]["text"] == "alice.w+tag@gmail.com"
    assert mask(text, "email") == "邮箱 a***@gmail.com 备用"


def test_mask_all_rules_together():
    text = ("手机13812345678 身份证11010119900307123X "
            "卡号6222021234567890123 邮箱bob@example.com")
    masked = mask(text, "all")
    assert masked == ("手机138****5678 身份证110101********123X "
                      "卡号6222***********0123 邮箱b***@example.com")


def test_mask_default_is_all_rules():
    assert mask("打 13812345678") == mask("打 13812345678", "all")


def test_mask_multiple_names_list():
    text = "手机13812345678 邮箱bob@example.com"
    assert mask(text, ["mobile"]) == "手机138****5678 邮箱bob@example.com"
    assert mask(text, ["mobile", "email"]) == "手机138****5678 邮箱b***@example.com"


def test_mask_no_hit_returns_original():
    assert mask("没有敏感信息", "all") == "没有敏感信息"


def test_unknown_rule_raises():
    with pytest.raises(PatternError) as excinfo:
        mask("text", "nope")
    assert "unknown rule" in str(excinfo.value)
    with pytest.raises(PatternError):
        get_rule("nope")


def test_detect_sorted_by_position():
    text = "邮箱a@b.com 手机13812345678"
    hits = detect(text)
    assert [h["rule"] for h in hits] == ["email", "mobile"]
    assert hits[0]["span"] < hits[1]["span"]


def test_rule_object_api():
    rule = RULES["mobile"]
    m = rule.search("电话13812345678")
    assert m.group(1) == "138"
    assert rule.mask("电话13812345678") == "电话138****5678"
