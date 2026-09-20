"""Object store: hashing stability, blob dedup, tree/commit encoding."""

from conftest import list_objects, run, write

from minigit.objects import (
    ObjectStore, build_tree, decode_tree, encode_tree, flatten_tree,
    hash_object, parse_commit, encode_commit,
)


def test_hash_stability(repo):
    h1 = hash_object("blob", b"hello world")
    h2 = hash_object("blob", b"hello world")
    assert h1 == h2
    assert len(h1) == 40
    assert all(c in "0123456789abcdef" for c in h1)
    # different content -> different hash
    assert hash_object("blob", b"hello world!") != h1


def test_write_read_roundtrip(tmp_path):
    store = ObjectStore(str(tmp_path))
    sha = store.write_object("blob", b"some bytes \x00\x01")
    obj_type, data = store.read_object(sha)
    assert obj_type == "blob"
    assert data == b"some bytes \x00\x01"
    # object lives under <2 chars>/<38 chars>
    path = tmp_path / "objects" / sha[:2] / sha[2:]
    assert path.is_file()


def test_blob_dedup_two_files_same_content(repo):
    write(repo, "a.txt", "identical content")
    write(repo, "b.txt", "identical content")
    assert run("add", ".") == 0
    assert len(list_objects(repo)) == 1  # only one blob object


def test_repeated_add_commit_no_duplicate_blob(repo):
    write(repo, "a.txt", "same content")
    assert run("add", "a.txt") == 0
    assert run("commit", "-m", "first") == 0
    # add the identical content again; commit must be rejected (no changes)
    assert run("add", "a.txt") == 0
    assert run("commit", "-m", "second") == 1
    # 1 blob + 1 tree + 1 commit, nothing more
    assert len(list_objects(repo)) == 3


def test_tree_encoding_roundtrip():
    entries = [
        ("100644", "a.txt", "0" * 40),
        ("40000", "dir", "1" * 40),
        ("100755", "run.sh", "2" * 40),
    ]
    assert decode_tree(encode_tree(entries)) == entries


def test_tree_build_order_deterministic(tmp_path):
    store = ObjectStore(str(tmp_path))
    entries1 = {
        "b.txt": ("100644", hash_object("blob", b"b")),
        "a/c.txt": ("100644", hash_object("blob", b"c")),
        "a.txt": ("100644", hash_object("blob", b"a")),
        "a/b/d.txt": ("100644", hash_object("blob", b"d")),
    }
    entries2 = dict(reversed(list(entries1.items())))
    sha1 = build_tree(store, entries1)
    sha2 = build_tree(store, entries2)
    assert sha1 == sha2
    # flattening reproduces the original mapping
    assert flatten_tree(store, sha1) == entries1


def test_commit_encoding_roundtrip():
    data = encode_commit(
        "a" * 40, ["b" * 40],
        "Alice <a@x> 1700000000 +0800", "Alice <a@x> 1700000000 +0800",
        "message line1\nline2")
    commit = parse_commit(data)
    assert commit["tree"] == "a" * 40
    assert commit["parents"] == ["b" * 40]
    assert commit["message"].rstrip("\n") == "message line1\nline2"


def test_root_commit_has_no_parent(repo):
    write(repo, "a.txt", "x")
    run("add", ".")
    run("commit", "-m", "root")
    from conftest import head_sha
    store = ObjectStore(str(repo / ".minigit"))
    commit = parse_commit(store.read_object(head_sha(repo))[1])
    assert commit["parents"] == []
