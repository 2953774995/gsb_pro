"""Working-tree operations: hashing files, file modes, checkout/restore.

Files are hashed and written into the object store in a single streaming
pass (1 MiB chunks), so multi-megabyte files never sit fully in memory.
"""

import hashlib
import os
import zlib

from .errors import MiniGitError
from .objects import read_blob

FILE_MODE = 0o100644
EXEC_MODE = 0o100755
_CHUNK = 1 << 20  # 1 MiB


def file_mode(path):
    """Return the git-style mode of a regular file (exec bit aware)."""
    st = os.stat(path)
    return EXEC_MODE if st.st_mode & 0o111 else FILE_MODE


def hash_file(repo, path):
    """Stream a file into a blob object.

    Returns ``(mode, sha)``.  The object is stored compressed directly
    from the streaming pass; identical content deduplicates naturally by
    SHA-1.
    """
    mode = file_mode(path)
    size = os.path.getsize(path)
    header = b"blob %d\x00" % size
    hasher = hashlib.sha1(header)
    compressor = zlib.compressobj(level=6)

    tmp_dir = os.path.join(repo.gitdir, "objects", "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, "obj-%d" % os.getpid())
    with open(path, "rb") as src, open(tmp_path, "wb") as dst:
        dst.write(compressor.compress(header))
        while True:
            chunk = src.read(_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
            dst.write(compressor.compress(chunk))
        dst.write(compressor.flush())
    sha = hasher.hexdigest()

    final = repo.object_path(sha)
    if os.path.exists(final):
        os.remove(tmp_path)  # de-duplicate: content already stored
    else:
        os.makedirs(os.path.dirname(final), exist_ok=True)
        os.replace(tmp_path, final)
    return mode, sha


def _remove_empty_dirs(root, start_rel):
    """Remove empty directories under ``start_rel`` up to (not incl.) root."""
    cur = os.path.join(root, start_rel)
    while os.path.isdir(cur):
        try:
            os.rmdir(cur)
        except OSError:
            break
        parent = os.path.dirname(cur)
        if parent == cur or os.path.commonpath([parent, root]) != root or parent == root:
            break
        cur = parent


def restore_tree(repo, target_entries, tracked_paths, force=False):
    """Make the working tree match ``target_entries``.

    * files tracked but absent in the target are deleted (and emptied
      dirs pruned);
    * tracked files are overwritten with blob content;
    * untracked files are preserved -- unless an untracked file would be
      overwritten by checkout, in which case a clear error is raised
      (use ``force`` to overwrite).

    :param target_entries: ``{path: (mode, sha)}``
    :param tracked_paths: iterable of paths currently in the index
    """
    tracked = set(tracked_paths)
    target = dict(target_entries)

    # Safety check: untracked files blocking checkout.
    for path in target:
        abspath = os.path.join(repo.root, path)
        if os.path.lexists(abspath) and path not in tracked and not force:
            raise MiniGitError(
                "error: untracked working tree file %r would be overwritten "
                "by checkout" % path
            )

    # 1) delete tracked files that no longer exist in the target tree.
    for path in sorted(tracked - set(target)):
        abspath = os.path.join(repo.root, path)
        if os.path.lexists(abspath):
            os.remove(abspath)
        _remove_empty_dirs(repo.root, os.path.dirname(path))

    # 2) write / overwrite target files from their blobs.
    for path, (mode, sha) in sorted(target.items()):
        abspath = os.path.join(repo.root, path)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        data = read_blob(repo, sha)
        with open(abspath, "wb") as fh:
            fh.write(data)
        os.chmod(abspath, 0o755 if int(mode) == EXEC_MODE else 0o644)
