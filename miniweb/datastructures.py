"""Small reusable data structures."""

from typing import Dict, Iterable, Optional, Tuple


class CaseInsensitiveDict:
    """A dict with case-insensitive ASCII keys.

    Request headers are stored lower-cased.  Repeated request headers are
    combined with a comma and a space, which is the standard representation
    for comma-separated HTTP field values.
    """

    def __init__(self, data: Optional[Iterable[Tuple[str, str]]] = None) -> None:
        self._data: Dict[str, str] = {}
        if data:
            for key, value in data:
                self.add(key, value)

    def add(self, key: str, value: str) -> None:
        norm = key.lower()
        if norm in self._data:
            self._data[norm] = self._data[norm] + ", " + value
        else:
            self._data[norm] = value

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._data.get(key.lower(), default)

    def __contains__(self, key: str) -> bool:
        return key.lower() in self._data

    def __getitem__(self, key: str) -> str:
        return self._data[key.lower()]

    def __setitem__(self, key: str, value: str) -> None:
        self._data[key.lower()] = value

    def items(self) -> Iterable[Tuple[str, str]]:
        return self._data.items()

    def to_dict(self) -> Dict[str, str]:
        return dict(self._data)
