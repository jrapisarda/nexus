"""Google Patents scout using the public Google Patents XHR endpoint."""

from __future__ import annotations

import asyncio
import html
import re

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nexus_core.scouts.base import BaseScout, ScoutFinding

logger = structlog.get_logger(__name__)

_BASE_URL = "https://patents.google.com/xhr/query"
_TAG_RE = re.compile(r"<[^>]+>")


class GooglePatentsScout(BaseScout):
    """Scout that searches Google Patents via its public XHR query endpoint."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(2)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={
                "User-Agent": "NEXUS-Scout/1.0",
                "Accept": "application/json",
            },
        )

    @property
    def source_name(self) -> str:
        return "google_patents"

    async def search(self, query: str, limit: int = 10) -> list[ScoutFinding]:
        """Search Google Patents for patent results matching the query."""
        try:
            return await self._fetch_results(query, limit)
        except Exception as exc:
            logger.error("google_patents_search_failed", query=query, error=str(exc))
            return []

    async def scan_for_topics(
        self,
        topics: list[str],
        limit_per_topic: int = 5,
    ) -> list[ScoutFinding]:
        """Scan Google Patents for multiple research topics."""
        all_findings: list[ScoutFinding] = []
        seen_urls: set[str] = set()

        for topic in topics:
            try:
                findings = await self.search(topic, limit=limit_per_topic)
                for finding in findings:
                    if finding.source_url not in seen_urls:
                        seen_urls.add(finding.source_url)
                        all_findings.append(finding)
            except Exception as exc:
                logger.error("google_patents_topic_scan_failed", topic=topic, error=str(exc))

        return all_findings

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_results(self, query: str, limit: int) -> list[ScoutFinding]:
        params = {
            "url": f"q={query}",
        }

        async with self._semaphore:
            response = await self._client.get(_BASE_URL, params=params)
            response.raise_for_status()

        payload = response.json()
        clusters = payload.get("results", {}).get("cluster", []) or []

        findings: list[ScoutFinding] = []
        for cluster in clusters:
            for result in cluster.get("result", []) or []:
                findings.append(self._parse_result(result))
                if len(findings) >= limit:
                    return findings

        return findings

    def _parse_result(self, result: dict) -> ScoutFinding:
        patent = result.get("patent", {}) or {}
        title = self._clean_text(patent.get("title", "Untitled Patent"))
        abstract = self._clean_text(patent.get("snippet", "No abstract available."))
        publication_number = patent.get("publication_number", "")
        language = patent.get("language", "en")
        result_id = result.get("id") or (
            f"patent/{publication_number}/{language}" if publication_number else ""
        )
        source_url = f"https://patents.google.com/{result_id}" if result_id else ""

        inventor_text = self._clean_text(patent.get("inventor", ""))
        authors = [
            name.strip()
            for name in inventor_text.split(";")
            if name and name.strip()
        ]
        if inventor_text and not authors:
            authors = [inventor_text]

        published_date = (
            patent.get("publication_date")
            or patent.get("grant_date")
            or patent.get("filing_date")
            or patent.get("priority_date")
        )

        return ScoutFinding(
            title=title,
            abstract=abstract,
            source_url=source_url,
            source_type="google_patents",
            raw_data=result,
            authors=authors,
            published_date=published_date,
        )

    @staticmethod
    def _clean_text(value: str) -> str:
        if not value:
            return ""
        return html.unescape(_TAG_RE.sub("", value)).strip()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
