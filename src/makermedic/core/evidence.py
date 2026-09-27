"""Typed in-memory evidence storage."""

from collections.abc import Iterable, Iterator

from makermedic.core.errors import DuplicateEvidenceError
from makermedic.core.models import Evidence


class EvidenceStore:
    """Store evidence by key, rejecting duplicates deterministically."""

    def __init__(self, evidence: Iterable[Evidence] = ()) -> None:
        self._items: dict[str, Evidence] = {}
        self.extend(evidence)

    def add(self, evidence: Evidence) -> None:
        if evidence.key in self._items:
            raise DuplicateEvidenceError(f"duplicate evidence key: {evidence.key}")
        self._items[evidence.key] = evidence

    def extend(self, evidence: Iterable[Evidence]) -> None:
        for item in evidence:
            self.add(item)

    def get(self, key: str) -> Evidence | None:
        return self._items.get(key)

    def require(self, key: str) -> Evidence:
        try:
            return self._items[key]
        except KeyError as error:
            raise KeyError(f"evidence not found: {key}") from error

    def values(self) -> tuple[Evidence, ...]:
        return tuple(self._items.values())

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __iter__(self) -> Iterator[Evidence]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)
