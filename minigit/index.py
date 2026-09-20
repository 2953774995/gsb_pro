"""The staging area (.minigit/index).

Format: UTF-8 JSON, keys sorted, entries sorted by path -> stable output:

    {"version": 1,
     "entries": [{"path": "a.txt", "mode": "100644", "hash": "<sha1>"}, ...]}
"""

import json
import os


class Index:
    VERSION = 1

    def __init__(self, gitdir):
        self.path = os.path.join(gitdir, "index")
        self.entries = {}  # path -> (mode, sha1)

    def load(self):
        self.entries = {}
        if os.path.isfile(self.path):
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for entry in data.get("entries", []):
                self.entries[entry["path"]] = (entry["mode"], entry["hash"])
        return self

    def save(self):
        entries = [
            {"path": path, "mode": mode, "hash": sha}
            for path, (mode, sha) in sorted(self.entries.items())
        ]
        payload = {"version": self.VERSION, "entries": entries}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, self.path)

    def add(self, path, mode, sha):
        self.entries[path] = (mode, sha)

    def remove(self, path):
        self.entries.pop(path, None)
