"""回溯型匹配虚拟机。

执行方式：深度优先回溯，SPLIT 指令按"优先分支先行"的顺序探索，
因此交替从左到右、贪婪/非贪婪的偏好语义与常见模式引擎一致。

防灾难性回溯：本语法不含反向引用，捕获槽的值不影响控制流，
因此虚拟机状态完全由 (pc, pos) 决定。对已经探索过的 (pc, pos)
状态做记忆化剪枝在语义上与纯回溯严格等价，但能把 (a+)+$ 这类
指数级退化输入降为多项式时间。此外每次指令执行计入步数预算，
超过上限抛 PatternTimeoutError，双保险保证不会卡死进程。
"""

from .compiler import CHAR, CLASS, ANY, BOL, EOL, SAVE, SPLIT, JMP, MATCH
from .compiler import _ITEM_CHAR, _ITEM_RANGE, _ITEM_CODE
from .errors import PatternTimeoutError
from .escapes import class_code_matches


def _class_matches(items, negated, ch, icase):
    matched = False
    for item in items:
        kind = item[0]
        if kind == _ITEM_CHAR:
            if ch == item[1]:
                matched = True
                break
            if icase and item[2] is not None and ch.casefold() == item[2]:
                matched = True
                break
        elif kind == _ITEM_RANGE:
            o = ord(ch)
            if item[1] <= o <= item[2]:
                matched = True
                break
            if icase:
                folded = ch.casefold()
                if len(folded) == 1 and item[1] <= ord(folded) <= item[2]:
                    matched = True
                    break
        else:
            if class_code_matches(item[1], ch):
                matched = True
                break
    return matched != negated


def run(code, n_slots, text, pos, endpos, scanning, require_end,
        icase, multiline, max_steps):
    """从 pos 开始执行程序。

    scanning=True 时依次尝试 pos..endpos 的每个起始位置（search 语义），
    否则只尝试 pos 本身（match/fullmatch 语义）。
    require_end=True 时 MATCH 指令要求当前位置恰为 endpos（fullmatch 语义）。

    返回 (slots, end_pos)；未命中返回 None。
    """
    empty_slots = (-1,) * n_slots
    seen = set()       # 已探索的 (pc, pos)，含探索中与已失败
    stack = []
    steps = 0
    if scanning:
        starts = range(pos, endpos + 1)
    else:
        starts = (pos,)
    for start in starts:
        stack.append((0, start, empty_slots))
        while stack:
            pc, sp, slots = stack.pop()
            while True:
                steps += 1
                if steps > max_steps:
                    raise PatternTimeoutError(steps, max_steps)
                key = (pc, sp)
                if key in seen:
                    break
                seen.add(key)
                op = code[pc]
                tag = op[0]
                if tag == CHAR:
                    if sp < endpos:
                        ch = text[sp]
                        if ch == op[1] or (
                                icase and op[2] is not None
                                and ch.casefold() == op[2]):
                            sp += 1
                            pc += 1
                            continue
                    break
                if tag == CLASS:
                    if sp < endpos and _class_matches(
                            op[1], op[2], text[sp], icase):
                        sp += 1
                        pc += 1
                        continue
                    break
                if tag == ANY:
                    if sp < endpos and text[sp] != "\n":
                        sp += 1
                        pc += 1
                        continue
                    break
                if tag == BOL:
                    if sp == 0 or (multiline and text[sp - 1] == "\n"):
                        pc += 1
                        continue
                    break
                if tag == EOL:
                    if sp == endpos:
                        pc += 1
                        continue
                    if sp < endpos and text[sp] == "\n" and (
                            multiline or sp == endpos - 1):
                        pc += 1
                        continue
                    break
                if tag == SAVE:
                    slot = op[1]
                    slots = slots[:slot] + (sp,) + slots[slot + 1:]
                    pc += 1
                    continue
                if tag == SPLIT:
                    # 非优先分支压栈待回溯，优先分支继续执行
                    stack.append((op[2], sp, slots))
                    pc = op[1]
                    continue
                if tag == JMP:
                    pc = op[1]
                    continue
                # MATCH
                if require_end and sp != endpos:
                    break
                return slots, sp
    return None
