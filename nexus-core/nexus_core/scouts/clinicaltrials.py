"""ClinicalTrials.gov scout using REST API v2."""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nexus_core.scouts.base import BaseScout, ScoutFinding

logger = structlog.get_logger(__name__)

_BASE_URL = "https://clinicaltrials.gov/api/v2/studies"


class ClinicalTrialsScout(BaseScout):
    """Scout that searches ClinicalTrials.gov via the REST API v2.

    Rate limit: 1 request/second.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout
        # 1 request per second throttle
        self._semaphore = asyncio.Semaphore(1)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={
                "User-Agent": "NEXUS-Scout/1.0",
                "Accept": "application/json",
            },
        )

    @property
    def source_name(self) -> str:
        return "clinicaltrials"

    async def search(self, query: str, limit: int = 10) -> list[ScoutFinding]:
        """Search ClinicalTrials.gov for studies matching the query."""
        try:
            return await self._fetch_studies(query, limit)
        except Exception as e:
            logger.error("clinicaltrials_search_failed", query=query, error=str(e))
            return []

    async def scan_for_topics(self, topics: list[str], limit_per_topic: int = 5) -> list[ScoutFinding]:
        """Scan ClinicalTrials.gov for multiple research topics."""
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
                logger.error("clinicaltrials_topic_scan_failed", topic=topic, error=str(e))

        return all_findings

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_studies(self, query: str, limit: int) -> list[ScoutFinding]:
        """Fetch studies from ClinicalTrials.gov API v2."""
        params: dict[str, str | int] = {
            "query.term": query,
            "pageSize": min(limit, 100),
            "format": "json",
        }

        async with self._semaphore:
            resp = await self._client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            # 1 req/sec throttle: pause after each request
            await asyncio.sleep(1.0)

        data = resp.json()
        studies = data.get("studies", [])
        return [self._parse_study(s) for s in studies if s]

    def _parse_study(self, study: dict) -> ScoutFinding:
        """Parse a single study object from the ClinicalTrials.gov API response."""
        protocol = study.get("protocolSection", {})
        id_module = protocol.get("identificationModule", {})
        desc_module = protocol.get("descriptionModule", {})
        status_module = protocol.get("statusModule", {})
        contacts_module = protocol.get("contactsLocationsModule", {})
        design_module = protocol.get("designModule", {})

        nct_id = id_module.get("nctId", "")
        title = id_module.get("briefTitle", id_module.get("officialTitle", "Untitled Study"))
        brief_summary = desc_module.get("briefSummary", "No summary available.")

        # Extract investigators/contacts as authors
        authors: list[str] = []
        overall_officials = contacts_module.get("overallOfficials", [])
        for official in overall_officials:
            name = official.get("name", "")
            if name:
                authors.append(name)

        # Published/start date
        start_date_struct = status_module.get("startDateStruct", {})
        published_date: Optional[str] = start_date_struct.get("date")

        # Study phase as additional data
        phases = design_module.get("phases", [])
        overall_status = status_module.get("overallStatus", "")

        source_url = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else ""

        return ScoutFinding(
            title=title,
            abstract=brief_summary,
            source_url=source_url,
            source_type="clinicaltrials",
            raw_data={
                "nct_id": nct_id,
                "phases": phases,
                "overall_status": overall_status,
            },
            authors=authors,
            published_date=published_date,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
