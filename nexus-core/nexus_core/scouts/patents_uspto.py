"""USPTO PatentsView scout for patent search."""

from __future__ import annotations

import asyncio
import json

import httpx
import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from nexus_core.scouts.base import BaseScout, ScoutFinding

logger = structlog.get_logger(__name__)

_BASE_URL = "https://search.patentsview.org/api/v1/patent/"
_MAX_PAGE_SIZE = 1000
_PATENT_FIELDS = [
    "patent_id",
    "patent_title",
    "patent_abstract",
    "patent_date",
    "inventors.inventor_name_first",
    "inventors.inventor_name_last",
]
_PATENT_SORT = [
    {"patent_date": "desc"},
    {"patent_id": "asc"},
]


def _is_retryable_http_status(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    status_code = exc.response.status_code
    return status_code in {408, 429} or status_code >= 500


def _http_error_detail(exc: httpx.HTTPStatusError) -> str:
    reason = exc.response.headers.get("X-Status-Reason") or exc.response.headers.get(
        "X-Status-Reason-Code"
    )
    if reason:
        return f"{exc} ({reason})"
    return str(exc)


class USPTOScout(BaseScout):
    """Scout that searches USPTO patents via the PatentsView API.

    Rate limit: 45 requests/minute (~0.75 req/sec).
    We enforce this with a semaphore of 1 and a 1.5s delay.
    """

    def __init__(self, api_key: str = "", timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout
        # 45 req/min ≈ 1 req every 1.33s; use semaphore(1) + delay
        self._semaphore = asyncio.Semaphore(1)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": "NEXUS-Scout/1.0",
            "Accept": "application/json",
        }
        if self._api_key:
            headers["X-Api-Key"] = self._api_key
        return headers

    @property
    def source_name(self) -> str:
        return "uspto"

    async def search(self, query: str, limit: int = 10) -> list[ScoutFinding]:
        """Search USPTO patents matching the query."""
        if not self._api_key:
            logger.warning("uspto_api_key_missing", query=query)
            return []
        try:
            return await self._fetch_patents(query, limit)
        except httpx.HTTPStatusError as e:
            logger.error(
                "uspto_search_failed",
                query=query,
                status_code=e.response.status_code,
                error=_http_error_detail(e),
            )
            return []
        except Exception as e:
            logger.error("uspto_search_failed", query=query, error=str(e))
            return []

    async def scan_for_topics(self, topics: list[str], limit_per_topic: int = 5) -> list[ScoutFinding]:
        """Scan USPTO patents for multiple research topics."""
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
                logger.error("uspto_topic_scan_failed", topic=topic, error=str(e))

        return all_findings

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception(_is_retryable_http_status),
        reraise=True,
    )
    async def _fetch_patents(self, query: str, limit: int) -> list[ScoutFinding]:
        """Fetch patents from the PatentsView API."""
        # Current PatentsView PatentSearch expects API-key-authenticated q/f/s/o parameters.
        query_payload = {
            "_or": [
                {"_text_any": {"patent_title": query}},
                {"_text_any": {"patent_abstract": query}},
            ]
        }
        params: dict[str, str | int] = {
            "q": json.dumps(query_payload, separators=(",", ":")),
            "f": json.dumps(_PATENT_FIELDS, separators=(",", ":")),
            "s": json.dumps(_PATENT_SORT, separators=(",", ":")),
            "o": json.dumps({"size": min(limit, _MAX_PAGE_SIZE)}, separators=(",", ":")),
        }

        async with self._semaphore:
            resp = await self._client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            # Rate limit: ~1.5s between requests
            await asyncio.sleep(1.5)

        data = resp.json()
        patents = data.get("patents", [])
        if patents is None:
            return []

        return [self._parse_patent(p) for p in patents]

    def _parse_patent(self, patent: dict) -> ScoutFinding:
        """Parse a single patent record from PatentsView API response."""
        patent_number = patent.get("patent_id") or patent.get("patent_number", "")
        title = patent.get("patent_title", "Untitled Patent")
        abstract = patent.get("patent_abstract", "No abstract available.")
        patent_date = patent.get("patent_date")

        # Extract inventors
        authors: list[str] = []
        inventors = patent.get("inventors", [])
        for inv in inventors:
            first = inv.get("inventor_name_first") or inv.get("inventor_first_name", "")
            last = inv.get("inventor_name_last") or inv.get("inventor_last_name", "")
            full_name = f"{first} {last}".strip()
            if full_name:
                authors.append(full_name)

        source_url = f"https://patents.google.com/patent/US{patent_number}" if patent_number else ""

        return ScoutFinding(
            title=title,
            abstract=abstract,
            source_url=source_url,
            source_type="uspto",
            raw_data=patent,
            authors=authors,
            published_date=patent_date,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
