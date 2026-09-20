"""Core in-memory message value types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredMessage:
    sequence: int
    topic: bytes
    payload: bytes
