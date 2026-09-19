import hashlib
import os
import zlib
from pathlib import Path

import pytest

from minigit import index as index_mod
from minigit import objects
from minigit.cli import main


def run(*args, expect=0):
    assert main(list(args)) == expect


def test_blob_hash_matches_sha1_content_address_and_reads_zlib(repo):
    payload = b"hello object\n"
    sha = objects.write_object(repo / ".minigit" / "objects", objects.OBJECT_BLOB, payload)
    expected = hashlib.sha1(b"blob 13\0" + payload).hexdigest()
    assert sha == expected

    stored = repo / ".minigit" / "objects" / sha[:2] / sha[2:]
    assert stored.is_file()
    assert zlib.decompress(stored.read_bytes()) == b"blob 13\0" + payload
    assert objects.read_object(repo / ".minigit" / "objects", sha) == (objects.OBJECT_BLOB, payload)


def test_identical_file_contents_share_one_blob_even_with_different_names(repo):
    Path("a.txt").write_text("same bytes\n")
    Path("b.txt").write_text("same bytes\n")
    sha_a = objects.write_blob_from_path(repo / ".minigit" / "objects", Path("a.txt"))[0]
    sha_b = objects.write_blob_from_path(repo / ".minigit" / "objects", Path("b.txt"))[0]
    assert sha_a == sha_b
    run("add", "a.txt", "b.txt")
    object_files_before = list((repo / ".minigit" / "objects").rglob("*"))
    run("add", "a.txt", "b.txt")
    assert list((repo / ".minigit" / "objects").rglob("*")) == object_files_before


def test_tree_construction_is_recursive_and_path_order_is_deterministic(repo):
    for name in ["z.txt", "a.txt", "d/y.txt", "d/m.txt", "b/nested/x.txt"]:
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"content {name}\n")
    run("add", ".")
    entries = index_mod.read_index(repo / ".minigit" / "index")
    tree_hash_one = objects.write_tree_from_index(repo / ".minigit" / "objects", entries)
    tree_hash_two = objects.write_tree_from_index(repo / ".minigit" / "objects", dict(reversed(list(entries.items()))))
    assert tree_hash_one == tree_hash_two

    root = objects.parse_tree(objects.read_object(repo / ".minigit" / "objects", tree_hash_one, objects.OBJECT_TREE)[1])
    assert [entry.name for entry in root] == ["a.txt", "b", "d", "z.txt"]
    flat = objects.read_tree_flat(repo / ".minigit" / "objects", tree_hash_one)
    assert list(flat) == ["a.txt", "b/nested/x.txt", "d/m.txt", "d/y.txt", "z.txt"]


def test_index_roundtrip_is_binary_stable_and_reproducible(repo):
    entries = {
        "z/file": (objects.FILE_MODE, "a" * 40),
        "a/file": (objects.FILE_MODE, "b" * 40),
    }
    one = index_mod.serialize_index(entries)
    two = index_mod.serialize_index(dict(reversed(list(entries.items()))))
    assert one == two
    index_mod.write_index(repo / ".minigit" / "index", entries)
    assert index_mod.read_index(repo / ".minigit" / "index") == entries


def test_large_file_add_is_streaming_and_fast(repo):
    size = 4 * 1024 * 1024
    with open("large.bin", "wb") as handle:
        for number in range(1024):
            handle.write(bytes([number % 256]) * 4096)
    assert os.path.getsize("large.bin") == size
    run("add", "large.bin")
    index = index_mod.read_index(repo / ".minigit" / "index")
    sha = index["large.bin"][1]
    assert objects.read_blob(repo / ".minigit" / "objects", sha) == Path("large.bin").read_bytes()
