"""Base class and data structures for NEXUS external data source scouts."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScoutFinding:
    """Normalized finding from an external source."""

    title: str
    abstract: str
    source_url: str
    source_type: str  # pubmed, clinicaltrials, biorxiv, medrxiv, uspto, google_patents
    relevance_score: float = 0.0
    raw_data: dict = field(default_factory=dict)
    authors: list[str] = field(default_factory=list)
    published_date: Optional[str] = None
    doi: Optional[str] = None


class BaseScout(ABC):
    """Abstract base class for external data source scouts."""

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[ScoutFinding]:
        """Search the external source for a query."""
        ...

    @abstractmethod
    async def scan_for_topics(self, topics: list[str], limit_per_topic: int = 5) -> list[ScoutFinding]:
        """Scan for multiple research topics."""
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Name of this data source."""
        ...
