"""Large files (several MiB) must add/commit quickly and stay correct."""

import os
import time

from conftest import repo, read_file, run_cli, write_file
from minigit import objects as obj
from minigit.index import load_index

SIZE = 3 * 1024 * 1024  # 3 MiB


def test_large_file_add_and_commit(init_repo):
    payload = os.urandom(SIZE)
    write_file("big.bin", payload)
    start = time.monotonic()
    code, _, err = run_cli("add", "big.bin")
    elapsed = time.monotonic() - start
    assert code == 0, err
    assert elapsed < 30  # must not hang

    idx = load_index(repo())
    mode, sha = idx.entries["big.bin"]
    assert obj.read_blob(repo(), sha) == payload  # byte-exact round trip

    code, _, err = run_cli("commit", "-m", "big")
    assert code == 0, err

    # Re-adding identical content keeps a single object.
    assert run_cli("add", "big.bin")[0] == 0
    assert load_index(repo()).entries["big.bin"][1] == sha
    loose = [
        os.path.join(dp, f)
        for dp, _, fs in os.walk(repo().objects_dir)
        for f in fs if not f.endswith(".tmp")
    ]
    assert repo().object_path(sha) in loose
