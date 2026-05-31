from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RegistryEntry(Generic[T]):
    name: str
    value: T


class Registry(Generic[T]):
    def __init__(self) -> None:
        self._entries: dict[str, T] = {}

    def register(self, name: str, value: T) -> None:
        if name in self._entries:
            raise ValueError(f"duplicate registry entry: {name}")
        self._entries[name] = value

    def get(self, name: str) -> T:
        return self._entries[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))
