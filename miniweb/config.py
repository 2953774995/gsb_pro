"""Tunable server limits / defaults."""

from dataclasses import dataclass

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_WORKERS = 10
DEFAULT_TIMEOUT = 30.0
# Request line and the header block are each capped at this many bytes.
DEFAULT_MAX_HEADER_SIZE = 8 * 1024
DEFAULT_MAX_BODY_SIZE = 2 * 1024 * 1024
SERVER_NAME = "miniweb/0.1"


@dataclass
class Config:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    workers: int = DEFAULT_WORKERS
    timeout: float = DEFAULT_TIMEOUT
    max_header_size: int = DEFAULT_MAX_HEADER_SIZE
    max_body_size: int = DEFAULT_MAX_BODY_SIZE
    static_root: str = ""
