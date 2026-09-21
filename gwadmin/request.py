from dataclasses import dataclass, field
from .headers import Headers


@dataclass
class Request:
    method: str
    target: str
    path: str
    query: dict
    version: str
    headers: Headers
    body: bytes = b""
    params: dict = field(default_factory=dict)
    peer: tuple = None

    @property
    def content_type(self):
        return self.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    @property
    def charset(self):
        value = self.headers.get("content-type", "")
        if ";" not in value:
            return "utf-8"
        for part in value.split(";", 1)[1].split(";"):
            part = part.strip()
            if part.lower().startswith("charset="):
                return part.split("=", 1)[1].strip().strip('"') or "utf-8"
        return "utf-8"
