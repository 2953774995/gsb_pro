import os

from minigit import objects
from minigit.index import build_tree, read_index
from minigit.repo import find_repo

from conftest import write


def test_hash_is_stable_and_content_addressed(repo):
    h1 = objects.hash_object(objects.BLOB, b"hello")
    h2 = objects.hash_object(objects.BLOB, b"hello")
    assert h1 == h2
    assert len(h1) == 40
    assert objects.hash_object(objects.BLOB, b"world") != h1


def test_write_read_roundtrip(repo):
    oid = objects.write_object(repo, objects.BLOB, b"payload")
    obj_type, data = objects.read_object(repo, oid)
    assert obj_type == objects.BLOB
    assert data == b"payload"
    # On-disk layout: 2-char fanout dir + 38-char name.
    path = os.path.join(repo.objects_dir, oid[:2], oid[2:])
    assert os.path.isfile(path)


def test_blob_dedup_same_content(repo):
    a = objects.write_object(repo, objects.BLOB, b"same")
    b = objects.write_object(repo, objects.BLOB, b"same")
    assert a == b
    stored = []
    for fanout in os.listdir(repo.objects_dir):
        stored.extend(os.listdir(os.path.join(repo.objects_dir, fanout)))
    assert stored == [a[2:]]


def test_two_files_same_content_share_one_blob(repo, run):
    write(repo.root, "a.txt", "identical")
    write(repo.root, "dir/b.txt", "identical")
    assert run("add", ".") == 0
    entries = read_index(repo)
    assert entries["a.txt"].oid == entries["dir/b.txt"].oid
    count = sum(len(files) for _, _, files in os.walk(repo.objects_dir))
    assert count == 1  # exactly one blob object


def test_tree_entries_sorted_deterministically(repo):
    entries = [
        objects.TreeEntry(objects.MODE_FILE, "b.txt", "0" * 40),
        objects.TreeEntry(objects.MODE_FILE, "a.txt", "1" * 40),
        objects.TreeEntry(objects.MODE_TREE, "sub", "2" * 40),
    ]
    payload1 = objects.serialize_tree(entries)
    payload2 = objects.serialize_tree(list(reversed(entries)))
    assert payload1 == payload2
    parsed = objects.parse_tree(payload1)
    assert [e.name for e in parsed] == ["a.txt", "b.txt", "sub"]
    assert parsed[2].is_tree


def test_tree_build_order_independent(repo, run):
    # Add files in two different orders in two repos; tree hashes must match.
    write(repo.root, "x/1.txt", "one")
    write(repo.root, "y/2.txt", "two")
    write(repo.root, "top.txt", "top")
    assert run("add", "top.txt") == 0
    assert run("add", "y/2.txt") == 0
    assert run("add", "x/1.txt") == 0
    tree1 = build_tree(repo, read_index(repo))

    other = os.path.join(repo.root, "..", "other")
    os.makedirs(other, exist_ok=True)
    from minigit.repo import init_repo
    repo2, _ = init_repo(other)
    cwd = os.getcwd()
    try:
        os.chdir(other)
        write(other, "x/1.txt", "one")
        write(other, "y/2.txt", "two")
        write(other, "top.txt", "top")
        from minigit.cli import main
        assert main(["add", "x/1.txt"]) == 0
        assert main(["add", "y/2.txt"]) == 0
        assert main(["add", "top.txt"]) == 0
        tree2 = build_tree(repo2, read_index(repo2))
    finally:
        os.chdir(cwd)
    assert tree1 == tree2


def test_commit_object_roundtrip(repo):
    payload = b"tree " + b"0" * 40 + b"\nauthor A <a@b> 1 +0000\n\nmsg\n"
    oid = objects.write_object(repo, objects.COMMIT, payload)
    obj_type, data = objects.read_object(repo, oid)
    assert obj_type == objects.COMMIT
    assert data == payload


def test_read_missing_object_raises(repo):
    import pytest
    from minigit.errors import MiniGitError
    with pytest.raises(MiniGitError):
        objects.read_object(repo, "f" * 40)
