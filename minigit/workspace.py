"""Working-tree helpers: walking files and materialising commits."""

import os

from .errors import MiniGitError
from .objects import COMMIT, flatten_tree, parse_commit
from .repository import MINIGIT_DIR


def iter_workdir_files(repo):
    """All files under the workdir, excluding .minigit and ignored paths."""
    result = []
    for root, dirs, files in os.walk(repo.workdir):
        rel_root = os.path.relpath(root, repo.workdir).replace(os.sep, "/")
        kept = []
        for d in sorted(dirs):
            if d == MINIGIT_DIR:
                continue
            rel = d if rel_root == "." else rel_root + "/" + d
            if not repo.ignore.is_ignored(rel, is_dir=True):
                kept.append(d)
        dirs[:] = kept
        for name in sorted(files):
            rel = name if rel_root == "." else rel_root + "/" + name
            if not repo.ignore.is_ignored(rel):
                result.append(rel)
    return sorted(result)


def head_tree_entries(repo):
    """Flattened ``{path: (mode, sha)}`` of the commit HEAD points at."""
    head = repo.refs.head_commit()
    if not head:
        return {}
    obj_type, data = repo.objects.read_object(head)
    if obj_type != COMMIT:
        raise MiniGitError("HEAD does not point at a commit")
    commit = parse_commit(data)
    return flatten_tree(repo.objects, commit["tree"])


def _prune_empty_dirs(workdir, path):
    while path and os.path.abspath(path) != os.path.abspath(workdir):
        try:
            os.rmdir(path)
        except OSError:
            break
        path = os.path.dirname(path)


def checkout_commit(repo, commit_sha):
    """Replace tracked content with ``commit_sha``'s tree and reset the index.

    Files tracked now but absent from the target commit are deleted; tracked
    files are overwritten; untracked files are left untouched.
    """
    obj_type, data = repo.objects.read_object(commit_sha)
    if obj_type != COMMIT:
        raise MiniGitError("object %s is not a commit" % commit_sha)
    commit = parse_commit(data)
    target = flatten_tree(repo.objects, commit["tree"])

    currently_tracked = set(head_tree_entries(repo)) | set(repo.index.entries)
    for path in sorted(currently_tracked - set(target)):
        fpath = repo.abspath(path)
        if os.path.isfile(fpath):
            os.remove(fpath)
            _prune_empty_dirs(repo.workdir, os.path.dirname(fpath))

    for path, (mode, sha) in sorted(target.items()):
        _obj_type, blob = repo.objects.read_object(sha)
        fpath = repo.abspath(path)
        parent = os.path.dirname(fpath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(fpath, "wb") as fh:
            fh.write(blob)
        os.chmod(fpath, 0o755 if mode == "100755" else 0o644)

    repo.index.entries = dict(target)
    repo.index.save()
