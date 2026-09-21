"""Case-insensitive headers with deterministic duplicate merging."""


class Headers:
    def __init__(self, items=None):
        self._items = []
        if items:
            for name, value in items:
                self.add(name, value)

    @staticmethod
    def _name(name):
        return str(name).strip().lower()

    def add(self, name, value):
        self._items.append((self._name(name), str(value)))

    def set(self, name, value):
        key = self._name(name)
        self._items = [(k, v) for k, v in self._items if k != key]
        self._items.append((key, str(value)))

    def get(self, name, default=None):
        values = self.get_all(name)
        return ", ".join(values) if values else default

    def get_all(self, name):
        key = self._name(name)
        return [v for k, v in self._items if k == key]

    def items(self):
        return list(self._items)

    def __contains__(self, name):
        return self._name(name) in {k for k, _ in self._items}
