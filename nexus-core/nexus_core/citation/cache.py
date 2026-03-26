"""PostgreSQL-backed citation verification cache."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
import structlog

from nexus_core.models.citation import citation_verifications

logger = structlog.get_logger(__name__)


def make_cache_key(identifier: str, identifier_type: str) -> str:
    """SHA-256 hash of normalized identifier for cache lookup."""
    normalized = identifier.strip().lower()
    return hashlib.sha256(f"{identifier_type}:{normalized}".encode()).hexdigest()


async def get_cached_verification(
    conn,
    identifier: str,
    identifier_type: str,
) -> dict | None:
    """Check cache for a previous verification result.

    Returns dict with verification data if cached and not expired, else None.
    """
    key = make_cache_key(identifier, identifier_type)
    result = await conn.execute(
        sa.select(citation_verifications)
        .where(
            citation_verifications.c.cache_key == key,
            citation_verifications.c.expires_at > sa.func.now(),
        )
    )
    row = result.one_or_none()
    if row is None:
        return None

    return {
        "verified": row.verified,
        "http_status_code": row.http_status_code,
        "resolved_url": row.resolved_url,
        "resolver_used": row.resolver_used,
    }


async def store_verification(
    conn,
    identifier: str,
    identifier_type: str,
    verified: bool,
    http_status_code: int | None = None,
    resolved_url: str | None = None,
    resolver_used: str | None = None,
    ttl_days: int = 30,
) -> None:
    """Store a verification result in the cache."""
    key = make_cache_key(identifier, identifier_type)
    expires = datetime.now(UTC) + timedelta(days=ttl_days)

    # Upsert: try insert, on conflict update
    existing = await conn.execute(
        sa.select(citation_verifications.c.verification_id)
        .where(citation_verifications.c.cache_key == key)
    )
    if existing.one_or_none() is not None:
        await conn.execute(
            citation_verifications.update()
            .where(citation_verifications.c.cache_key == key)
            .values(
                verified=verified,
                http_status_code=http_status_code,
                resolved_url=resolved_url,
                resolver_used=resolver_used,
                verified_at=sa.func.now(),
                expires_at=expires,
            )
        )
    else:
        await conn.execute(
            citation_verifications.insert().values(
                cache_key=key,
                source_identifier=identifier,
                identifier_type=identifier_type,
                verified=verified,
                http_status_code=http_status_code,
                resolved_url=resolved_url,
                resolver_used=resolver_used,
                expires_at=expires,
            )
        )
