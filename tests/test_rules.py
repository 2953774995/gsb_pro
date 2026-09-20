"""Built-in sensitive-data rules: detection and masking."""

import pytest

import datamask as dm
from datamask.rules import get_rule, list_rules, mask_text


def test_list_rules():
    assert list_rules() == ["bankcard", "email", "idcard", "phone"]


def test_unknown_rule_raises():
    with pytest.raises(KeyError) as ei:
        get_rule("nope")
    assert "unknown rule" in str(ei.value)
    with pytest.raises(KeyError):
        mask_text("x", "nope")


# ------------------------------------------------------------------- phone
@pytest.mark.parametrize(
    "number",
    ["13812345678", "19900001111", "15012345678", "17612345678"],
)
def test_phone_detects_valid_numbers(number):
    rule = get_rule("phone")
    matches = list(rule.finditer("tel:" + number))
    assert len(matches) == 1
    assert matches[0].group(0) == number


@pytest.mark.parametrize(
    "number",
    ["12345678901",   # 12 开头不是有效号段
     "1381234567",    # 只有 10 位
     "23812345678"],  # 2 开头
)
def test_phone_rejects_invalid_numbers(number):
    rule = get_rule("phone")
    assert list(rule.finditer(" " + number + " ")) == []


def test_phone_mask():
    text = "联系电话 13812345678，备用 13900001111。"
    assert mask_text(text, "phone") == "联系电话 138****5678，备用 139****1111。"


# ------------------------------------------------------------------ idcard
def test_idcard_detect_and_mask():
    text = "用户身份证号：11010119900307777X，请核实。"
    rule = get_rule("idcard")
    m = list(rule.finditer(text))
    assert len(m) == 1
    assert m[0].group(0) == "11010119900307777X"
    assert mask_text(text, "idcard") == "用户身份证号：110101********777X，请核实。"


def test_idcard_lowercase_x():
    assert mask_text("id 11010119900307777x", "idcard") == \
        "id 110101********777x"


def test_idcard_rejects_wrong_length():
    rule = get_rule("idcard")
    assert list(rule.finditer(" 1101011990030777 ")) == []   # 17 位
    assert list(rule.finditer(" 11010119900307777A ")) == []  # 非法校验位


# ---------------------------------------------------------------- bankcard
@pytest.mark.parametrize(
    "card,masked",
    [
        ("6222020200112233445", "6222***********3445"),   # 19 位
        ("6222020200112233", "6222********2233"),         # 16 位
        ("62220202001122334", "6222*********2334"),       # 17 位
    ],
)
def test_bankcard_mask_lengths(card, masked):
    assert mask_text("卡号" + card, "bankcard") == "卡号" + masked


def test_bankcard_rejects_short():
    rule = get_rule("bankcard")
    assert list(rule.finditer(" 123456789012345 ")) == []  # 15 位


# ------------------------------------------------------------------- email
def test_email_detect_and_mask():
    text = "邮箱 zhangsan@example.com 或 li.si+tag@sub.domain.org"
    assert mask_text(text, "email") == \
        "邮箱 z***@example.com 或 l***@sub.domain.org"


def test_email_groups():
    rule = get_rule("email")
    m = next(rule.finditer("abc@example.com"))
    assert m.group(1) == "a"
    assert m.group(2) == "bc"
    assert m.group(3) == "@example.com"


def test_email_rejects_invalid():
    rule = get_rule("email")
    assert list(rule.finditer("not-an-email@")) == []
    assert list(rule.finditer("@example.com")) == []


# ------------------------------------------------------------------ combined
def test_mask_leaves_non_sensitive_text_untouched():
    text = "没有敏感信息的工单。"
    for name in list_rules():
        assert mask_text(text, name) == text


def test_multiple_occurrences_all_masked():
    text = "13812345678 和 13900001111"
    assert mask_text(text, "phone") == "138****5678 和 139****1111"


def test_rules_use_own_engine():
    # 规则包必须跑在自研引擎上：Pattern 类型来自 datamask 自身。
    for name in list_rules():
        assert isinstance(get_rule(name).pattern, dm.Pattern)
