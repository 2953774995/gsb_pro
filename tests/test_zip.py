"""ZIP container: structure, roundtrips, interop with system zip/unzip, CRC."""

import os
import random
import shutil
import struct
import subprocess
import time

import pytest

from zipmini.archive import (
    CENTRAL_HEADER_SIG,
    EOCD_SIG,
    LOCAL_HEADER_SIG,
    METHOD_DEFLATE,
    METHOD_STORED,
    ZipError,
    ZipReader,
    ZipWriter,
)

HAVE_SYSTEM_TOOLS = shutil.which("zip") and shutil.which("unzip")
needs_system_tools = pytest.mark.skipif(
    not HAVE_SYSTEM_TOOLS, reason="system zip/unzip not available"
)


def _sample_files():
    rng = random.Random(123)
    return {
        "hello.txt": b"hello world, hello world, hello!" * 30,
        "dir/sub/data.bin": rng.randbytes(3000),
        "dir/pattern.txt": b"abc123\n" * 2000,
        "empty.txt": b"",
        "one.txt": b"Z",
    }


def _write_sample(path, files=None, **kwargs):
    with ZipWriter(path, **kwargs) as zw:
        for name, data in (files or _sample_files()).items():
            zw.writestr(name, data, date_time=(2024, 3, 14, 15, 9, 26))
    return path


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_zip_layout_signatures(tmp_path):
    path = tmp_path / "a.zip"
    _write_sample(str(path), {"a.txt": b"aaa"})
    data = path.read_bytes()
    assert data[:4] == struct.pack("<I", LOCAL_HEADER_SIG)
    assert struct.pack("<I", CENTRAL_HEADER_SIG) in data
    # EOCD is the last record (22 bytes, empty comment).
    assert data[-22:-18] == struct.pack("<I", EOCD_SIG)
    count, = struct.unpack_from("<H", data, -22 + 10)
    assert count == 1


def test_local_header_fields(tmp_path):
    path = tmp_path / "a.zip"
    payload = b"abcabcabc" * 100
    _write_sample(str(path), {"a.txt": payload})
    data = path.read_bytes()
    (sig, _ver, _flags, method, _time, _date, crc, csize, usize,
     nlen, xlen) = struct.unpack_from("<IHHHHHIIIHH", data, 0)
    assert sig == LOCAL_HEADER_SIG
    assert method == METHOD_DEFLATE
    assert usize == len(payload)
    assert csize < usize
    from binascii import crc32
    assert crc == crc32(payload) & 0xFFFFFFFF
    assert data[30:30 + nlen] == b"a.txt"
    assert xlen == 0


# ---------------------------------------------------------------------------
# Roundtrip
# ---------------------------------------------------------------------------

def test_roundtrip_multiple_files_and_dirs(tmp_path):
    path = tmp_path / "a.zip"
    files = _sample_files()
    _write_sample(str(path), files)
    reader = ZipReader(str(path))
    assert set(reader.namelist()) == set(files)
    for name, content in files.items():
        assert reader.read(name) == content


def test_extractall_recreates_tree(tmp_path):
    path = tmp_path / "a.zip"
    files = _sample_files()
    _write_sample(str(path), files)
    dest = tmp_path / "out"
    ZipReader(str(path)).extractall(str(dest))
    for name, content in files.items():
        assert (dest / name).read_bytes() == content


def test_timestamps_preserved(tmp_path):
    path = tmp_path / "a.zip"
    _write_sample(str(path), {"a.txt": b"x"})
    member = ZipReader(str(path)).getmember("a.txt")
    # DOS time has 2-second granularity.
    assert member.date_time == (2024, 3, 14, 15, 9, 26)


def test_empty_archive(tmp_path):
    path = tmp_path / "empty.zip"
    with ZipWriter(str(path)):
        pass
    reader = ZipReader(str(path))
    assert reader.infolist() == []


def test_directory_entries(tmp_path):
    path = tmp_path / "a.zip"
    with ZipWriter(str(path)) as zw:
        zw.writestr("docs/", b"", is_dir=True)
        zw.writestr("docs/a.txt", b"content")
    reader = ZipReader(str(path))
    dirs = [m for m in reader.infolist() if m.is_dir]
    assert [m.filename for m in dirs] == ["docs/"]
    dest = tmp_path / "out"
    reader.extractall(str(dest))
    assert (dest / "docs").is_dir()
    assert (dest / "docs" / "a.txt").read_bytes() == b"content"


def test_incompressible_file_is_stored(tmp_path):
    path = tmp_path / "a.zip"
    data = random.Random(5).randbytes(5000)
    _write_sample(str(path), {"r.bin": data})
    member = ZipReader(str(path)).getmember("r.bin")
    assert member.compress_type == METHOD_STORED
    assert ZipReader(str(path)).read("r.bin") == data


def test_compressible_file_uses_deflate(tmp_path):
    path = tmp_path / "a.zip"
    _write_sample(str(path), {"z.bin": b"\x00" * 10000})
    member = ZipReader(str(path)).getmember("z.bin")
    assert member.compress_type == METHOD_DEFLATE
    assert member.compressed_size < 200


def test_write_directory_recursively(tmp_path):
    src = tmp_path / "srcdir"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"A" * 100)
    (src / "sub" / "b.txt").write_bytes(b"B" * 200)
    path = tmp_path / "a.zip"
    with ZipWriter(str(path)) as zw:
        zw.write(str(src))
    reader = ZipReader(str(path))
    assert set(reader.namelist()) == {"srcdir/", "srcdir/a.txt", "srcdir/sub/b.txt"}
    assert reader.read("srcdir/a.txt") == b"A" * 100
    assert reader.read("srcdir/sub/b.txt") == b"B" * 200


def test_non_ascii_filename_roundtrip(tmp_path):
    path = tmp_path / "a.zip"
    _write_sample(str(path), {"中文文件.txt": b"unicode name"})
    reader = ZipReader(str(path))
    assert reader.read("中文文件.txt") == b"unicode name"


# ---------------------------------------------------------------------------
# CRC / corruption detection
# ---------------------------------------------------------------------------

def test_crc_mismatch_detected(tmp_path):
    path = tmp_path / "a.zip"
    payload = b"important data " * 100
    _write_sample(str(path), {"a.txt": payload})
    raw = bytearray(path.read_bytes())
    # Flip a byte inside the compressed payload (right after the 30-byte
    # local header + 5-byte name).
    raw[35] ^= 0xFF
    corrupted = tmp_path / "corrupt.zip"
    corrupted.write_bytes(bytes(raw))
    with pytest.raises(ZipError):
        ZipReader(str(corrupted)).read("a.txt")


def test_bad_signature_rejected(tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"this is not a zip file at all, just junk")
    with pytest.raises(ZipError):
        ZipReader(str(junk))


def test_missing_member_raises(tmp_path):
    path = tmp_path / "a.zip"
    _write_sample(str(path), {"a.txt": b"x"})
    with pytest.raises(KeyError):
        ZipReader(str(path)).read("nope.txt")


# ---------------------------------------------------------------------------
# Interop with the system tools
# ---------------------------------------------------------------------------

@needs_system_tools
def test_system_unzip_accepts_our_archive(tmp_path):
    path = tmp_path / "ours.zip"
    files = _sample_files()
    files["big.bin"] = (b"pattern-" * 5000) + random.Random(3).randbytes(50000)
    _write_sample(str(path), files)
    result = subprocess.run(
        ["unzip", "-t", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # And actually extract + compare byte for byte.
    dest = tmp_path / "sysout"
    result = subprocess.run(
        ["unzip", "-q", str(path), "-d", str(dest)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    for name, content in files.items():
        assert (dest / name).read_bytes() == content


@needs_system_tools
def test_we_read_system_zip_archive(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"hello zip " * 50)
    (src / "sub" / "b.txt").write_bytes(b"nested content")
    (src / "rand.bin").write_bytes(random.Random(9).randbytes(4000))
    archive = tmp_path / "system.zip"
    subprocess.run(
        ["zip", "-q", "-r", str(archive), "."],
        cwd=str(src), check=True, capture_output=True,
    )
    reader = ZipReader(str(archive))
    assert set(reader.namelist()) == {"a.txt", "sub/", "sub/b.txt", "rand.bin"}
    assert reader.read("a.txt") == b"hello zip " * 50
    assert reader.read("sub/b.txt") == b"nested content"
    assert reader.read("rand.bin") == (src / "rand.bin").read_bytes()


@needs_system_tools
def test_system_unzip_validates_timestamps(tmp_path):
    path = tmp_path / "ts.zip"
    _write_sample(str(path), {"a.txt": b"x"})
    result = subprocess.run(
        ["unzip", "-l", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0
    # Date rendering differs per unzip build ("2024-03-14" or "03-14-2024").
    assert "2024" in result.stdout
    assert "03-14" in result.stdout
