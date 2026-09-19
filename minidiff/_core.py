"""Sequence alignment.

Given two sequences ``x`` and ``y``, :func:`align` returns a shortest edit
script made of ``(kind, i, j, value)`` tuples:

* ``("equal", i, j, value)``   -- ``x[i] == y[j]``
* ``("delete", i, None, value)`` -- element only in ``x``
* ``("insert", None, j, value)`` -- element only in ``y``

Two strategies are combined:

1. **Myers' greedy snake algorithm with O(d^2) frontier tracking**
   (``_myers``).  Edit scripts for typical file edits have a small edit
   distance ``d``; Myers then runs in near-linear time because it follows
   the diagonal "snakes" of equal elements directly.

2. **Hirschberg's linear-space LCS** (``_hirschberg``) as a guaranteed
   O(n*m)-time / O(min(n, m))-space fallback when the edit distance turns
   out to be large (e.g. comparing two fully unrelated files), so memory
   never grows quadratically.

Both are hand-written dynamic programming -- no ``difflib`` is involved.
"""


def align(x, y):
    """Return a shortest edit script aligning sequences *x* and *y*."""
    if x and y and set(x).isdisjoint(y):
        # No common element at all: the LCS is empty, so the shortest
        # script is trivially "delete x, insert y".
        script = [("delete", i, None, x[i]) for i in range(len(x))]
        script += [("insert", None, j, y[j]) for j in range(len(y))]
        return script

    n, m = len(x), len(y)
    # Myers keeps one frontier row per edit-distance round.  Cap the work
    # budget; pathological inputs (edit distance comparable to n+m) fall
    # back to Hirschberg, which has a guaranteed small memory footprint.
    budget = max(64, (n + m) // 4)
    try:
        return _myers(x, y, budget)
    except _BudgetExceeded:
        return _hirschberg(x, 0, n, y, 0, m)


class _BudgetExceeded(Exception):
    pass


def _myers(a, b, budget):
    """Shortest edit script with Myers' greedy frontier algorithm.

    A complete frontier snapshot is kept per edit round so the path can be
    reconstructed.  Raises :class:`_BudgetExceeded` when more than
    *budget* edit rounds are required (callers then use Hirschberg, whose
    memory usage is always linear).
    """
    n, m = len(a), len(b)
    max_round = min(n + m, budget)
    shift = n + m + 1
    sentinel = -(n + m) - 1
    frontier = [sentinel] * (2 * (n + m) + 4)
    # Paper sentinel: diagonal 1 is reachable at x=0 before round 0.
    frontier[1 + shift] = 0
    traces = []
    found = None
    for round_d in range(max_round + 1):
        cur = frontier.copy()
        reached = None
        for k in range(-round_d, round_d + 1, 2):
            if k == -round_d or (
                    k != round_d
                    and frontier[k - 1 + shift]
                    < frontier[k + 1 + shift]):
                x = frontier[k + 1 + shift]  # down move (insertion)
            else:
                x = frontier[k - 1 + shift] + 1  # right move (deletion)
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            cur[k + shift] = x
            if reached is None and x >= n and y >= m:
                reached = k
        frontier = cur
        traces.append(frontier.copy())
        if reached is not None:
            found = (round_d, reached)
            break
    if found is None:
        raise _BudgetExceeded
    return _myers_backtrack(a, b, traces, found, shift)


def _myers_backtrack(a, b, traces, found, shift):
    n, m = len(a), len(b)
    round_d, k = found
    x, y = n, m
    ops = []
    for d in range(round_d, 0, -1):
        prev = traces[d - 1]
        if k == -d or (k != d
                       and prev[k - 1 + shift] < prev[k + 1 + shift]):
            prev_k = k + 1  # insertion (move down)
            prev_x = prev[prev_k + shift]
            prev_y = prev_x - prev_k
            entry_x, entry_y = prev_x, prev_y + 1
            insertion = True
        else:
            prev_k = k - 1  # deletion (move right)
            prev_x = prev[prev_k + shift]
            prev_y = prev_x - prev_k
            entry_x, entry_y = prev_x + 1, prev_y
            insertion = False
        while x > entry_x and y > entry_y:
            x -= 1
            y -= 1
            ops.append(("equal", x, y, a[x]))
        if insertion:
            ops.append(("insert", None, prev_y, b[prev_y]))
        else:
            ops.append(("delete", prev_x, None, a[prev_x]))
        x, y, k = prev_x, prev_y, prev_k
    while x > 0 and y > 0:
        x -= 1
        y -= 1
        ops.append(("equal", x, y, a[x]))
    ops.reverse()
    return ops


def _hirschberg(x, lo1, hi1, y, lo2, hi2):
    """Linear-space LCS edit script via divide-and-conquer recursion."""
    if lo1 == hi1:
        return [("insert", None, j, y[j]) for j in range(lo2, hi2)]
    if lo2 == hi2:
        return [("delete", i, None, x[i]) for i in range(lo1, hi1)]

    # Strip a common prefix.
    p1, p2 = lo1, lo2
    while p1 < hi1 and p2 < hi2 and x[p1] == y[p2]:
        p1 += 1
        p2 += 1
    head = ([("equal", k, k + (lo2 - lo1), x[k])
             for k in range(lo1, p1)] if p1 > lo1 else [])
    if p1 == hi1:
        return head + [("insert", None, j, y[j])
                       for j in range(p2, hi2)]
    if p2 == hi2:
        return head + [("delete", i, None, x[i])
                       for i in range(p1, hi1)]

    # Strip a common suffix (cannot overlap the stripped prefix).
    s1, s2 = hi1 - 1, hi2 - 1
    while s1 >= p1 and s2 >= p2 and x[s1] == y[s2]:
        s1 -= 1
        s2 -= 1
    tail_start1, tail_start2 = s1 + 1, s2 + 1

    middle = []
    if p1 < tail_start1 or p2 < tail_start2:
        n1 = tail_start1 - p1
        n2 = tail_start2 - p2
        if n1 == 1:
            target = x[p1]
            match = next((j for j in range(p2, tail_start2)
                          if y[j] == target), None)
            if match is None:
                middle.append(("delete", p1, None, target))
                middle.extend(("insert", None, j, y[j])
                              for j in range(p2, tail_start2))
            else:
                middle.extend(("insert", None, j, y[j])
                              for j in range(p2, match))
                middle.append(("equal", p1, match, target))
                middle.extend(("insert", None, j, y[j])
                              for j in range(match + 1, tail_start2))
        elif n2 == 1:
            target = y[p2]
            match = next((i for i in range(p1, tail_start1)
                          if x[i] == target), None)
            if match is None:
                middle.extend(("delete", i, None, x[i])
                              for i in range(p1, tail_start1))
                middle.append(("insert", None, p2, target))
            else:
                middle.extend(("delete", i, None, x[i])
                              for i in range(p1, match))
                middle.append(("equal", match, p2, target))
                middle.extend(("delete", i, None, x[i])
                              for i in range(match + 1, tail_start1))
        else:
            k = p1 + n1 // 2
            forward = _lcs_row(x, p1, k, y, p2, tail_start2)
            backward = _lcs_row_rev(x, k, tail_start1, y, p2, tail_start2)
            best_t, best_score = 0, -1
            for t in range(n2 + 1):
                score = forward[t] + backward[t]
                if score > best_score:
                    best_score, best_t = score, t
            split2 = p2 + best_t
            middle = _hirschberg(x, p1, k, y, p2, split2)
            middle += _hirschberg(x, k, tail_start1, y, split2, tail_start2)

    tail = [
        ("equal", i, j, x[i])
        for i, j in zip(range(tail_start1, hi1),
                        range(tail_start2, hi2))
    ] if tail_start1 < hi1 else []

    return head + middle + tail


def _lcs_row(x, lo1, hi1, y, lo2, hi2):
    """F[t] = LCS length of x[lo1:hi1] and y[lo2:lo2+t]."""
    n2 = hi2 - lo2
    prev = [0] * (n2 + 1)
    cur = [0] * (n2 + 1)
    for i in range(lo1, hi1):
        xi = x[i]
        for t in range(n2):
            if xi == y[lo2 + t]:
                cur[t + 1] = prev[t] + 1
            else:
                left, up = cur[t], prev[t + 1]
                cur[t + 1] = left if left >= up else up
        prev, cur = cur, prev
    return prev


def _lcs_row_rev(x, lo1, hi1, y, lo2, hi2):
    """R[t] = LCS length of x[lo1:hi1] and y[lo2+t:hi2]."""
    n2 = hi2 - lo2
    prev = [0] * (n2 + 1)
    cur = [0] * (n2 + 1)
    for i in range(hi1 - 1, lo1 - 1, -1):
        xi = x[i]
        for t in range(n2 - 1, -1, -1):
            if xi == y[lo2 + t]:
                cur[t] = prev[t + 1] + 1
            else:
                right, down = cur[t + 1], prev[t]
                cur[t] = right if right >= down else down
        prev, cur = cur, prev
    return prev
