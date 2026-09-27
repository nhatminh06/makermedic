"""Contract for fact collection."""

from collections.abc import Collection, Iterable
from typing import Protocol

from makermedic.core.models import Evidence


class Probe(Protocol):
    """An independently executable environmental observation source."""

    @property
    def id(self) -> str: ...

    @property
    def categories(self) -> Collection[str]: ...

    def collect(self) -> Iterable[Evidence]:
        """Collect facts only; raise ProbeCollectionError for expected failure."""
        ...
