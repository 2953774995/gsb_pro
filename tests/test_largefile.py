"""Large files: multi-MB blobs must add/commit quickly and correctly."""

import time

from conftest import run, write

from minigit.objects import hash_object


def test_large_file_add_and_commit(repo):
    data = (b"0123456789abcdef" * 4096 + b"\n") * 80  # ~5 MB
    assert len(data) > 5 * 1024 * 1024
    write(repo, "big.bin", data)

    start = time.time()
    assert run("add", "big.bin") == 0
    assert run("commit", "-m", "add big file") == 0
    assert time.time() - start < 30  # must not hang

    sha = hash_object("blob", data)
    assert (repo / ".minigit" / "objects" / sha[:2] / sha[2:]).is_file()

    # content survives a checkout round-trip
    run("branch", "other")
    run("checkout", "other")
    assert (repo / "big.bin").read_bytes() == data
