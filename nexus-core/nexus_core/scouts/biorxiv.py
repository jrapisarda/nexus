"""bioRxiv / medRxiv scout using the bioRxiv API."""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nexus_core.scouts.base import BaseScout, ScoutFinding

logger = structlog.get_logger(__name__)

_BIORXIV_BASE = "https://api.biorxiv.org/details/biorxiv"
_MEDRXIV_BASE = "https://api.biorxiv.org/details/medrxiv"


class BioRxivScout(BaseScout):
    """Scout that searches bioRxiv and medRxiv preprint servers.

    The bioRxiv API returns preprints by date range.  For keyword searching
    we fetch recent preprints and filter locally, since the API only
    supports date-based retrieval (not full-text search).

    For topic scanning we use the ``/details/{server}/{interval}/{cursor}``
    endpoint with pagination.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        include_medrxiv: bool = True,
        date_range: str = "2025-01-01/2026-03-16",
    ) -> None:
        self._timeout = timeout
        self._include_medrxiv = include_medrxiv
        self._date_range = date_range
        # Moderate concurrency — the API has no published rate limit but be polite
        self._semaphore = asyncio.Semaphore(2)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": "NEXUS-Scout/1.0"},
        )

    @property
    def source_name(self) -> str:
        return "biorxiv"

    async def search(self, query: str, limit: int = 10) -> list[ScoutFinding]:
        """Search bioRxiv (and optionally medRxiv) for articles matching query keywords."""
        try:
            findings: list[ScoutFinding] = []

            # Fetch recent biorxiv preprints and filter by query terms
            biorxiv_results = await self._fetch_preprints(_BIORXIV_BASE, limit * 5)
            findings.extend(self._filter_by_query(biorxiv_results, query, "biorxiv"))

            if self._include_medrxiv:
                medrxiv_results = await self._fetch_preprints(_MEDRXIV_BASE, limit * 5)
                findings.extend(self._filter_by_query(medrxiv_results, query, "medrxiv"))

            # Sort by relevance and cap at limit
            findings.sort(key=lambda f: f.relevance_score, reverse=True)
            return findings[:limit]
        except Exception as e:
            logger.error("biorxiv_search_failed", query=query, error=str(e))
            return []

    async def scan_for_topics(self, topics: list[str], limit_per_topic: int = 5) -> list[ScoutFinding]:
        """Scan bioRxiv/medRxiv for multiple research topics."""
        all_findings: list[ScoutFinding] = []
        seen_urls: set[str] = set()

        for topic in topics:
            try:
                findings = await self.search(topic, limit=limit_per_topic)
                for f in findings:
                    if f.source_url not in seen_urls:
                        seen_urls.add(f.source_url)
                        all_findings.append(f)
            except Exception as e:
                logger.error("biorxiv_topic_scan_failed", topic=topic, error=str(e))

        return all_findings

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_preprints(self, base_url: str, limit: int, cursor: int = 0) -> list[dict]:
        """Fetch preprints from bioRxiv or medRxiv API with pagination.

        Endpoint format: ``{base_url}/{interval}/{cursor}/{page_size}``
        """
        page_size = min(limit, 100)
        url = f"{base_url}/{self._date_range}/{cursor}/{page_size}"

        async with self._semaphore:
            resp = await self._client.get(url)
            resp.raise_for_status()

        data = resp.json()
        messages = data.get("messages", [{}])
        total_str = messages[0].get("total", "0") if messages else "0"

        collection = data.get("collection", [])
        results: list[dict] = list(collection)

        # Paginate if needed and we haven't reached our limit
        total = int(total_str) if str(total_str).isdigit() else 0
        fetched = len(results)
        while fetched < min(limit, total):
            next_cursor = cursor + fetched
            url = f"{base_url}/{self._date_range}/{next_cursor}/{page_size}"
            async with self._semaphore:
                resp = await self._client.get(url)
                resp.raise_for_status()
            page_data = resp.json()
            page_collection = page_data.get("collection", [])
            if not page_collection:
                break
            results.extend(page_collection)
            fetched = len(results)

        return results[:limit]

    def _filter_by_query(self, preprints: list[dict], query: str, server: str) -> list[ScoutFinding]:
        """Filter preprint records by keyword relevance and convert to ScoutFinding."""
        query_terms = [t.lower() for t in query.split() if len(t) > 2]
        findings: list[ScoutFinding] = []

        for pp in preprints:
            title = pp.get("title", "")
            abstract = pp.get("abstract", "")
            searchable = f"{title} {abstract}".lower()

            # Count matching query terms
            matched = sum(1 for term in query_terms if term in searchable)
            if matched == 0:
                continue

            relevance = matched / max(len(query_terms), 1)

            doi = pp.get("doi", "")
            source_url = f"https://doi.org/{doi}" if doi else ""

            # Parse authors
            authors_raw = pp.get("authors", "")
            authors: list[str] = []
            if isinstance(authors_raw, str) and authors_raw:
                authors = [a.strip() for a in authors_raw.split(";") if a.strip()]

            published_date: Optional[str] = pp.get("date")

            findings.append(
                ScoutFinding(
                    title=title,
                    abstract=abstract if abstract else "No abstract available.",
                    source_url=source_url,
                    source_type=server,
                    relevance_score=relevance,
                    raw_data=pp,
                    authors=authors,
                    published_date=published_date,
                    doi=doi if doi else None,
                )
            )

        return findings

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
