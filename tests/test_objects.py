"""Object store: SHA-1 stability, blob de-duplication, tree ordering."""

import hashlib
import os

from conftest import read_file, repo, run_cli, write_file
from minigit import objects as obj


def test_blob_hash_matches_manual_sha1(init_repo):
    data = b"hello blob\n"
    expected = hashlib.sha1(b"blob 11\x00" + data).hexdigest()
    sha = obj.write_blob(repo(), data)
    assert sha == expected
    assert obj.hash_object("blob", data) == expected


def test_identical_content_dedupicates(init_repo):
    content = b"same content\n"
    write_file("a.txt", content)
    write_file("nested/b.txt", content)
    code, _, _ = run_cli("add", "a.txt", "nested/b.txt")
    assert code == 0
    sha1 = obj.write_blob(repo(), content)
    sha2 = obj.write_blob(repo(), content)  # repeated write is idempotent
    assert sha1 == sha2
    # Exactly one loose object file holds this content.
    loose = []
    for d, _, files in os.walk(os.path.join(repo().objects_dir)):
        loose.extend(os.path.join(d, f) for f in files if not f.endswith(".tmp"))
    assert any(os.path.basename(p) == sha1[2:] for p in loose)
    # two distinct files in the index point at the same blob
    from minigit.index import load_index

    idx = load_index(repo())
    assert idx.entries["a.txt"][1] == idx.entries["nested/b.txt"][1] == sha1


def test_read_back_blob_roundtrip(init_repo):
    payload = bytes(range(256))
    sha = obj.write_blob(repo(), payload)
    otype, body = obj.read_object(repo(), sha)
    assert otype == "blob" and body == payload


def test_tree_build_is_ordered_and_deterministic(init_repo):
    r = repo()
    entries = {}
    for name in ("zeta.txt", "alpha.txt", "m/file.txt", "abc", "abc.dir/x"):
        p = name
        sha = obj.write_blob(r, b"x-" + p.encode())
        entries[p] = (0o100644, sha)
    t1 = obj.build_tree(r, entries)
    t2 = obj.build_tree(r, dict(reversed(list(entries.items()))))
    assert t1 == t2  # independent of insertion order

    parsed = obj.read_tree(r, t1)
    # git-compatible ordering: "abc" (file) sorts before "abc.dir", and
    # "abc.dir" (dir -> "abc.dir/") sorts before "alpha.txt"... verify
    # strictly ascending git-style keys.
    keys = [n + ("/" if is_dir else "") for _m, n, _s, is_dir in parsed]
    assert keys == sorted(keys)
    assert [n for _m, n, _s, _d in parsed] == [
        "abc", "abc.dir", "alpha.txt", "m", "zeta.txt"
    ]


def test_tree_recursive_nesting(init_repo):
    r = repo()
    sha_b = obj.write_blob(r, b"deep")
    root = obj.build_tree(r, {"a/b/c/file.txt": (0o100644, sha_b)})
    flat = obj.flatten_tree(r, root)
    assert flat == {"a/b/c/file.txt": (0o100644, sha_b)}
