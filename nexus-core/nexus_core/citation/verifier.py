"""Citation DOI and URL verification for NEXUS findings."""

from __future__ import annotations

import asyncio
import re
from decimal import Decimal

import httpx
import sqlalchemy as sa
import structlog

from nexus_core.citation.cache import get_cached_verification, store_verification
from nexus_core.models.findings import findings
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)

# DOI regex per CrossRef specification (covers ~99.3% of real DOIs)
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$")

# Process-level semaphore to limit concurrent external HTTP calls
_GLOBAL_SEMAPHORE: asyncio.Semaphore | None = None

USER_AGENT = "NEXUS-CitationVerifier/1.0 (mailto:admin@nexus.internal)"


def _get_semaphore(limit: int = 5) -> asyncio.Semaphore:
    global _GLOBAL_SEMAPHORE
    if _GLOBAL_SEMAPHORE is None:
        _GLOBAL_SEMAPHORE = asyncio.Semaphore(limit)
    return _GLOBAL_SEMAPHORE


def is_valid_doi_format(doi: str) -> bool:
    """Check if a DOI string matches the expected format."""
    return bool(DOI_PATTERN.match(doi.strip()))


async def _verify_doi_single(
    client: httpx.AsyncClient,
    doi: str,
    timeout: int = 5,
) -> dict:
    """Verify a single DOI through the CrossRef → OpenAlex → Semantic Scholar cascade."""
    doi = doi.strip()

    if not is_valid_doi_format(doi):
        return {"verified": False, "resolver_used": "regex_reject", "http_status_code": None}

    sem = _get_semaphore()

    # 1. CrossRef
    async with sem:
        try:
            r = await client.get(
                f"https://api.crossref.org/works/{doi}",
                params={"mailto": "admin@nexus.internal"},
                timeout=timeout,
            )
            if r.status_code == 200:
                return {
                    "verified": True,
                    "resolver_used": "crossref",
                    "http_status_code": 200,
                    "resolved_url": f"https://doi.org/{doi}",
                }
            if r.status_code != 404:
                logger.debug("crossref_non_404", doi=doi, status=r.status_code)
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.debug("crossref_error", doi=doi, error=str(exc))

    # 2. OpenAlex
    async with sem:
        try:
            r = await client.get(
                f"https://api.openalex.org/works/doi:{doi}",
                timeout=timeout,
            )
            if r.status_code == 200:
                return {
                    "verified": True,
                    "resolver_used": "openalex",
                    "http_status_code": 200,
                    "resolved_url": f"https://doi.org/{doi}",
                }
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.debug("openalex_error", doi=doi, error=str(exc))

    # 3. Semantic Scholar
    async with sem:
        try:
            r = await client.get(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                params={"fields": "title,year"},
                timeout=timeout,
            )
            if r.status_code == 200:
                return {
                    "verified": True,
                    "resolver_used": "semantic_scholar",
                    "http_status_code": 200,
                    "resolved_url": f"https://doi.org/{doi}",
                }
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.debug("semantic_scholar_error", doi=doi, error=str(exc))

    return {"verified": False, "resolver_used": "all_failed", "http_status_code": None}


async def _verify_url_single(
    client: httpx.AsyncClient,
    url: str,
    timeout: int = 5,
) -> dict:
    """Verify a URL exists via HEAD request."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return {"verified": False, "resolver_used": "invalid_scheme", "http_status_code": None}

    sem = _get_semaphore()
    async with sem:
        try:
            r = await client.head(url, follow_redirects=True, timeout=timeout)
            verified = r.status_code < 400
            return {
                "verified": verified,
                "resolver_used": "head_request",
                "http_status_code": r.status_code,
                "resolved_url": str(r.url) if r.url != url else None,
            }
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.debug("url_verify_error", url=url[:100], error=str(exc))
            return {"verified": False, "resolver_used": "error", "http_status_code": None}


async def verify_finding_citations(
    conn,
    finding_id,
    *,
    timeout_secs: int = 5,
    cache_ttl_days: int = 30,
) -> float:
    """Verify all citations in a finding and return a confidence score.

    Score: verified_count / total_count (0.0 to 1.0).
    Returns 0.5 if no citations are present (unverifiable, not penalized).
    """
    # Fetch the finding's structured_data
    row = await conn.execute(
        sa.select(findings.c.structured_data)
        .where(findings.c.finding_id == finding_id)
    )
    finding = row.one_or_none()
    if finding is None:
        return 0.5

    structured = finding.structured_data
    if not isinstance(structured, dict):
        return 0.5

    citations = structured.get("citations", [])
    if not isinstance(citations, list) or len(citations) == 0:
        return 0.5

    # Collect all DOIs and URLs to verify
    doi_checks: list[str] = []
    url_checks: list[str] = []

    for citation in citations:
        if not isinstance(citation, dict):
            continue
        doi = str(citation.get("doi", "")).strip()
        url = str(citation.get("url", "")).strip()
        if doi and doi.lower() not in ("", "n/a", "none", "null"):
            doi_checks.append(doi)
        if url and url.lower() not in ("", "n/a", "none", "null"):
            url_checks.append(url)

    total = len(doi_checks) + len(url_checks)
    if total == 0:
        return 0.5

    verified_count = 0

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        # Verify DOIs
        for doi in doi_checks:
            cached = await get_cached_verification(conn, doi, "doi")
            if cached is not None:
                if cached["verified"]:
                    verified_count += 1
                continue

            result = await _verify_doi_single(client, doi, timeout=timeout_secs)
            await store_verification(
                conn,
                identifier=doi,
                identifier_type="doi",
                verified=result["verified"],
                http_status_code=result.get("http_status_code"),
                resolved_url=result.get("resolved_url"),
                resolver_used=result.get("resolver_used"),
                ttl_days=cache_ttl_days,
            )
            if result["verified"]:
                verified_count += 1

        # Verify URLs
        for url in url_checks:
            cached = await get_cached_verification(conn, url, "url")
            if cached is not None:
                if cached["verified"]:
                    verified_count += 1
                continue

            result = await _verify_url_single(client, url, timeout=timeout_secs)
            await store_verification(
                conn,
                identifier=url,
                identifier_type="url",
                verified=result["verified"],
                http_status_code=result.get("http_status_code"),
                resolved_url=result.get("resolved_url"),
                resolver_used=result.get("resolver_used"),
                ttl_days=1,  # URLs cached for 1 day only
            )
            if result["verified"]:
                verified_count += 1

    score = verified_count / total if total > 0 else 0.5
    return round(score, 3)


async def run_citation_check(conn, finding_id, *, timeout_secs: int = 5, cache_ttl_days: int = 30) -> float:
    """Full citation check pipeline: set status, verify, update score, restore status.

    Returns the citation_confidence_score.
    """
    try:
        # Set status to citation_checking
        await conn.execute(
            findings.update()
            .where(findings.c.finding_id == finding_id)
            .values(
                status="citation_checking",
                citation_check_started_at=sa.func.now(),
            )
        )

        await emit_event(
            conn, "citation_check_started",
            entity_id=finding_id, entity_type="finding",
        )

        score = await verify_finding_citations(
            conn, finding_id,
            timeout_secs=timeout_secs,
            cache_ttl_days=cache_ttl_days,
        )

        # Update finding with score and restore to pending_review
        await conn.execute(
            findings.update()
            .where(findings.c.finding_id == finding_id)
            .values(
                citation_confidence_score=Decimal(str(score)),
                status="pending_review",
            )
        )

        await emit_event(
            conn, "citation_check_completed",
            entity_id=finding_id, entity_type="finding",
            payload={"score": score},
        )

        return score

    except Exception:
        logger.exception("citation_check_failed", finding_id=str(finding_id))
        # On failure: set score to 0.5 (unverified) and proceed
        await conn.execute(
            findings.update()
            .where(findings.c.finding_id == finding_id)
            .values(
                citation_confidence_score=Decimal("0.500"),
                status="pending_review",
            )
        )
        return 0.5
