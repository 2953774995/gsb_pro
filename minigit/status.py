"""Status computation shared by ``status``, ``commit`` and ``diff``.

The working tree is compared along the three classic Git dimensions:

* staged   -- index differs from the HEAD tree (status code XY[0]);
* worktree -- working file differs from the index entry (XY[1]);
* untracked -- file exists on disk but is neither in HEAD nor the index.

A file deleted from the working tree is reported as ``deleted``; the
``--short`` output uses git-style two-letter codes (``M``, ``A``,
``D``, ``??``).
"""

import os

from . import refs as refs_mod
from .ignore import IgnoreMatcher, walk_files
from .worktree import hash_file

# Canonical status labels (long form), keyed by short XY code.
LONG_LABELS = {
    "M ": "modified",
    "A ": "new file",
    "D ": "deleted",
    "MM": "modified",
    "MD": "modified",
    "AM": "new file",
    "AD": "new file",
}


def compute_status(repo):
    """Return a dict with ``staged``, ``worktree`` and ``untracked`` maps.

    * ``staged``:   ``{path: ("M"/"A"/"D", (index_mode,index_sha)|None,
                             (head_mode,head_sha)|None)}``
    * ``worktree``: ``{path: ("M"/"D", (wt_mode,wt_sha)|None,
                             (index_mode,index_sha)|None)}``
    * ``untracked``: ``{path: None}``
    """
    from .index import load_index

    idx = load_index(repo)
    head_entries = refs_mod.head_tree_entries(repo)
    matcher = IgnoreMatcher.for_repo(repo)
    on_disk = dict(walk_files(repo, matcher))

    staged = {}
    worktree = {}
    untracked = {}

    index_paths = idx.paths()
    head_paths = set(head_entries)

    # ---- staged: index vs HEAD
    for path in sorted(index_paths | head_paths):
        ie = idx.get(path)
        he = head_entries.get(path)
        if ie == he:
            continue
        if he is None and ie is not None:
            code = "A"
        elif ie is None and he is not None:
            code = "D"
        else:
            code = "M"
        staged[path] = (code, ie, he)

    # ---- worktree: disk vs index (index paths only; untracked handled next)
    for path in sorted(index_paths):
        abspath = on_disk.get(path, os.path.join(repo.root, path))
        ie = idx.get(path)
        if not os.path.isfile(abspath):
            worktree[path] = ("D", None, ie)
            continue
        mode, sha = hash_file(repo, abspath)
        wt = (mode, sha)
        if wt != ie:
            worktree[path] = ("M", wt, ie)

    # ---- untracked: on disk, neither in index nor HEAD
    for path in on_disk:
        if path not in index_paths and path not in head_paths:
            untracked[path] = None

    return {"staged": staged, "worktree": worktree, "untracked": untracked}


def short_codes(status):
    """Return git-style ``{path: "XY"}`` codes merging the three maps."""
    codes = {}
    for path, (code, _, _) in status["staged"].items():
        codes[path] = code + " "
    for path, (code, _, _) in status["worktree"].items():
        if path in codes:
            codes[path] = codes[path][0] + code
        else:
            codes[path] = " " + code
    for path in status["untracked"]:
        codes[path] = "??"
    return codes
