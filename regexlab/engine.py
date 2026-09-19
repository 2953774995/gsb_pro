"""Backtracking matching engine.

Matching is written in continuation-passing style: ``match_node`` tries
to match ``node`` at ``pos`` and, on success, calls ``cont(new_pos,
groups)``. The continuation returns True when the *rest* of the pattern
matched, so a node can try another alternative when its continuation
fails -- that is the backtracking.

``groups`` is a list indexed by capture-group number (index 0 is the
whole match); each entry is None or a ``(start, end)`` tuple. It is
treated as immutable-ish: setting a capture copies the list, so failed
branches never leak captures into their siblings.
"""

from .ast_nodes import (Alternation, AnyChar, CharClass, End, Group, Literal,
                        Predefined, Repeat, Sequence, Start, WordBoundary)

_ASCII_WHITESPACE = frozenset(" \t\n\r\f\v")


def _is_word_char(ch):
    return ch is not None and (ch == "_" or ch.isascii() and ch.isalnum())


def _predefined_matches(kind, ch):
    if ch is None:
        return False
    if kind in ("d", "D"):
        result = "0" <= ch <= "9"
    elif kind in ("w", "W"):
        result = _is_word_char(ch)
    else:  # s / S
        result = ch in _ASCII_WHITESPACE
    return result if kind.islower() else not result


def _class_matches(node, ch):
    if ch is None:
        return False
    code = ord(ch)
    for item in node.items:
        if item[0] == "range":
            if item[1] <= code <= item[2]:
                return not node.negated
        else:  # "pre"
            if _predefined_matches(item[1], ch):
                return not node.negated
    return node.negated


def match_node(node, text, pos, groups, cont):
    """Try to match *node* at *pos*; call *cont* on success.

    Returns True iff some path through this node and its continuation
    succeeds.
    """
    if isinstance(node, Literal):
        if pos < len(text) and text[pos] == node.char:
            return cont(pos + 1, groups)
        return False

    if isinstance(node, AnyChar):
        if pos < len(text) and text[pos] != "\n":
            return cont(pos + 1, groups)
        return False

    if isinstance(node, Predefined):
        ch = text[pos] if pos < len(text) else None
        if _predefined_matches(node.kind, ch):
            return cont(pos + 1, groups)
        return False

    if isinstance(node, CharClass):
        ch = text[pos] if pos < len(text) else None
        if _class_matches(node, ch):
            return cont(pos + 1, groups)
        return False

    if isinstance(node, Sequence):
        return _match_sequence(node.items, 0, text, pos, groups, cont)

    if isinstance(node, Alternation):
        for branch in node.branches:
            if match_node(branch, text, pos, groups, cont):
                return True
        return False

    if isinstance(node, Repeat):
        return _match_repeat(node, 0, text, pos, groups, cont)

    if isinstance(node, Group):
        if node.index is None:
            return match_node(node.child, text, pos, groups, cont)
        start = pos

        def group_cont(new_pos, new_groups):
            updated = list(new_groups)
            updated[node.index] = (start, new_pos)
            return cont(new_pos, updated)

        return match_node(node.child, text, pos, groups, group_cont)

    if isinstance(node, Start):
        if pos == 0:
            return cont(pos, groups)
        return False

    if isinstance(node, End):
        if pos == len(text):
            return cont(pos, groups)
        return False

    if isinstance(node, WordBoundary):
        before = text[pos - 1] if pos > 0 else None
        after = text[pos] if pos < len(text) else None
        boundary = _is_word_char(before) != _is_word_char(after)
        if boundary != node.negated:
            return cont(pos, groups)
        return False

    raise TypeError("unknown AST node: %r" % (node,))


def _match_sequence(items, index, text, pos, groups, cont):
    if index == len(items):
        return cont(pos, groups)

    def rest(new_pos, new_groups):
        return _match_sequence(items, index + 1, text, new_pos,
                               new_groups, cont)

    return match_node(items[index], text, pos, groups, rest)


def _match_repeat(node, count, text, pos, groups, cont):
    if count < node.min:
        # Mandatory repetitions first.
        def mandatory(new_pos, new_groups):
            return _match_repeat(node, count + 1, text, new_pos,
                                 new_groups, cont)

        return match_node(node.child, text, pos, groups, mandatory)

    can_grow = node.max is None or count < node.max

    def grow(new_pos, new_groups):
        # Guard against infinite loops on empty matches (e.g. (a*)*):
        # an empty iteration makes no progress, so stop expanding.
        if new_pos == pos:
            return False
        return _match_repeat(node, count + 1, text, new_pos,
                             new_groups, cont)

    if node.greedy:
        if can_grow and match_node(node.child, text, pos, groups, grow):
            return True
        return cont(pos, groups)
    else:
        if cont(pos, groups):
            return True
        return can_grow and match_node(node.child, text, pos, groups, grow)


def run(ast, group_count, text, start, require_end=False):
    """Attempt a match of *ast* anchored at *start*.

    Returns ``(end_pos, groups)`` on success, or None.
    """
    groups = [None] * (group_count + 1)
    result = []

    if require_end:
        def cont(pos, final_groups):
            if pos == len(text):
                result.append((pos, final_groups))
                return True
            return False
    else:
        def cont(pos, final_groups):
            result.append((pos, final_groups))
            return True

    if match_node(ast, text, start, groups, cont):
        end, final_groups = result[0]
        final_groups = list(final_groups)
        final_groups[0] = (start, end)
        return end, final_groups
    return None
