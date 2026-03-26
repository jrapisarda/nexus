"""PubMed scout using NCBI E-utilities for literature search."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import quote_plus

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nexus_core.scouts.base import BaseScout, ScoutFinding

logger = structlog.get_logger(__name__)

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedScout(BaseScout):
    """Scout that searches PubMed via NCBI E-utilities.

    Rate limits:
    - Without API key: 3 requests/second
    - With API key: 10 requests/second
    """

    def __init__(self, api_key: str = "", timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout
        # Rate limiter: 3 concurrent without key, 10 with key
        max_concurrent = 10 if api_key else 3
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": "NEXUS-Scout/1.0"},
        )

    @property
    def source_name(self) -> str:
        return "pubmed"

    async def search(self, query: str, limit: int = 10) -> list[ScoutFinding]:
        """Search PubMed for articles matching the query."""
        try:
            pmids = await self._esearch(query, limit)
            if not pmids:
                return []
            return await self._efetch(pmids)
        except Exception as e:
            logger.error("pubmed_search_failed", query=query, error=str(e))
            return []

    async def scan_for_topics(self, topics: list[str], limit_per_topic: int = 5) -> list[ScoutFinding]:
        """Scan PubMed for multiple research topics."""
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
                logger.error("pubmed_topic_scan_failed", topic=topic, error=str(e))

        return all_findings

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _esearch(self, query: str, limit: int) -> list[str]:
        """Search PubMed and return list of PMIDs."""
        params: dict[str, str | int] = {
            "db": "pubmed",
            "term": query,
            "retmax": limit,
            "retmode": "xml",
            "sort": "relevance",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        async with self._semaphore:
            resp = await self._client.get(_ESEARCH_URL, params=params)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        id_list = root.find("IdList")
        if id_list is None:
            return []

        return [id_elem.text for id_elem in id_list.findall("Id") if id_elem.text]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _efetch(self, pmids: list[str]) -> list[ScoutFinding]:
        """Fetch article details for a list of PMIDs."""
        params: dict[str, str] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        async with self._semaphore:
            resp = await self._client.get(_EFETCH_URL, params=params)
            resp.raise_for_status()

        return self._parse_pubmed_xml(resp.text)

    def _parse_pubmed_xml(self, xml_text: str) -> list[ScoutFinding]:
        """Parse PubMed XML response into ScoutFinding objects."""
        findings: list[ScoutFinding] = []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.error("pubmed_xml_parse_error")
            return []

        for article_elem in root.findall(".//PubmedArticle"):
            try:
                finding = self._parse_article(article_elem)
                if finding is not None:
                    findings.append(finding)
            except Exception as e:
                logger.warning("pubmed_article_parse_error", error=str(e))

        return findings

    def _parse_article(self, article_elem: ET.Element) -> Optional[ScoutFinding]:
        """Parse a single PubmedArticle element."""
        medline = article_elem.find("MedlineCitation")
        if medline is None:
            return None

        pmid_elem = medline.find("PMID")
        pmid = pmid_elem.text if pmid_elem is not None and pmid_elem.text else ""

        article = medline.find("Article")
        if article is None:
            return None

        # Title
        title_elem = article.find("ArticleTitle")
        title = title_elem.text if title_elem is not None and title_elem.text else "Untitled"

        # Abstract
        abstract_elem = article.find("Abstract")
        abstract_parts: list[str] = []
        if abstract_elem is not None:
            for text_elem in abstract_elem.findall("AbstractText"):
                label = text_elem.get("Label", "")
                text = text_elem.text or ""
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
        abstract = " ".join(abstract_parts) if abstract_parts else "No abstract available."

        # Authors
        authors: list[str] = []
        author_list = article.find("AuthorList")
        if author_list is not None:
            for author_elem in author_list.findall("Author"):
                last = author_elem.find("LastName")
                first = author_elem.find("ForeName")
                if last is not None and last.text:
                    name = last.text
                    if first is not None and first.text:
                        name = f"{last.text} {first.text[0]}"
                    authors.append(name)

        # Published date
        pub_date_elem = article.find(".//PubDate")
        published_date: Optional[str] = None
        if pub_date_elem is not None:
            year = pub_date_elem.find("Year")
            month = pub_date_elem.find("Month")
            if year is not None and year.text:
                published_date = year.text
                if month is not None and month.text:
                    published_date = f"{year.text}-{month.text}"

        # DOI
        doi: Optional[str] = None
        article_id_list = article_elem.find(".//ArticleIdList")
        if article_id_list is not None:
            for aid in article_id_list.findall("ArticleId"):
                if aid.get("IdType") == "doi" and aid.text:
                    doi = aid.text
                    break

        source_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""

        return ScoutFinding(
            title=title,
            abstract=abstract,
            source_url=source_url,
            source_type="pubmed",
            raw_data={"pmid": pmid},
            authors=authors,
            published_date=published_date,
            doi=doi,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
