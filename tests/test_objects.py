from __future__ import annotations

import hashlib
import os
import zlib

from cfgvault.index import Index, IndexEntry
from cfgvault.objects import (
    BLOB,
    build_tree,
    flatten_tree,
    read_blob,
    read_object,
    write_blob_bytes,
    write_blob_file,
    write_tree_from_entries,
)
from cfgvault.repo import init_repository


EMPTY_TREE_ID = hashlib.sha1(b"tree\x00").hexdigest()


def test_blob_hash_is_stable_and_content_is_compressed(in_tmp):
    repo = init_repository(str(in_tmp))
    data = b'{"price": 100}'
    expected = hashlib.sha1(b"blob\x00" + data).hexdigest()

    oid = write_blob_bytes(repo, data)
    assert oid == expected

    object_file = repo.objects_dir + "/" + oid[:2] + "/" + oid[2:]
    assert os.path.isfile(object_file)
    stored = open(object_file, "rb").read()
    assert zlib.decompress(stored) == b"blob\x00" + data
    assert read_object(repo, oid, BLOB) == (BLOB, data)


def test_identical_file_contents_deduplicate_to_one_blob(in_tmp):
    repo = init_repository(str(in_tmp))
    data = b"same promotion content\n"
    first = in_tmp / "prices" / "store-a.json"
    second = in_tmp / "prices" / "store-b.json"
    first.parent.mkdir(parents=True)
    first.write_bytes(data)
    second.write_bytes(data)

    oid1, size1 = write_blob_file(repo, str(first))
    oid2, size2 = write_blob_file(repo, str(second))
    assert oid1 == oid2
    assert size1 == size2 == len(data)
    assert read_blob(repo, oid1) == data
    object_files = []
    for base, _, files in os.walk(repo.objects_dir):
        object_files.extend(os.path.join(base, name) for name in files)
    assert len(object_files) == 1


def test_tree_construction_is_order_independent_and_recursive(in_tmp):
    repo = init_repository(str(in_tmp))
    a = write_blob_bytes(repo, b"a")
    b = write_blob_bytes(repo, b"b")
    c = write_blob_bytes(repo, b"c")

    mapping1 = {
        "discount/rules.json": ("100644", a),
        "poster/title.txt": ("100644", b),
        "prices.json": ("100755", c),
    }
    mapping2 = dict(reversed(list(mapping1.items())))
    tree1 = build_tree(repo, mapping1)
    tree2 = build_tree(repo, mapping2)
    assert tree1 == tree2

    flat = flatten_tree(repo, tree1)
    assert list(flat) == ["discount/rules.json", "poster/title.txt", "prices.json"]
    assert flat["prices.json"] == ("100755", c)


def test_empty_tree_has_fixed_hash(in_tmp):
    repo = init_repository(str(in_tmp))
    assert write_tree_from_entries(repo, ()) == EMPTY_TREE_ID
    assert build_tree(repo, Index().blob_map()) == EMPTY_TREE_ID


def test_index_is_stable_and_reproducible(in_tmp):
    repo = init_repository(str(in_tmp))
    blob = write_blob_bytes(repo, b"indexed")
    index = Index([
        IndexEntry("z.txt", "100644", blob),
        IndexEntry("a.txt", "100755", blob),
    ])
    index.write(repo)
    first = open(repo.index_file, "rb").read()
    index.write(repo)
    second = open(repo.index_file, "rb").read()
    assert first == second
    assert first.splitlines() == [
        b"CFGVLTIDX",
        b"1",
        b"100755\t" + blob.encode() + b"\ta.txt",
        b"100644\t" + blob.encode() + b"\tz.txt",
    ]


def test_large_blob_uses_chunked_add_and_round_trip(in_tmp):
    repo = init_repository(str(in_tmp))
    large = in_tmp / "large.json"
    payload = os.urandom(4 * 1024 * 1024)
    large.write_bytes(payload)

    oid, size = write_blob_file(repo, str(large))
    assert size == len(payload)
    assert read_blob(repo, oid) == payload
