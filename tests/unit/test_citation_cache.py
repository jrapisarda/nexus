"""Unit tests for nexus_core.citation.cache — cache key generation and lookup."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nexus_core.citation.cache import (
    get_cached_verification,
    make_cache_key,
    store_verification,
)


# ---------------------------------------------------------------------------
# make_cache_key
# ---------------------------------------------------------------------------

class TestMakeCacheKey:
    """Tests for make_cache_key() — deterministic SHA-256 cache keys."""

    def test_same_identifier_same_hash(self):
        """Identical identifier and type should produce the same key."""
        key1 = make_cache_key("10.1038/nature12373", "doi")
        key2 = make_cache_key("10.1038/nature12373", "doi")
        assert key1 == key2

    def test_different_identifiers_different_hashes(self):
        """Different identifiers should produce different keys."""
        key1 = make_cache_key("10.1038/nature12373", "doi")
        key2 = make_cache_key("10.1126/science.1185383", "doi")
        assert key1 != key2

    def test_different_types_different_hashes(self):
        """Same identifier but different types should produce different keys."""
        key1 = make_cache_key("10.1038/nature12373", "doi")
        key2 = make_cache_key("10.1038/nature12373", "url")
        assert key1 != key2

    def test_case_insensitive(self):
        """Identifiers should be normalized to lowercase."""
        key1 = make_cache_key("10.1038/Nature12373", "doi")
        key2 = make_cache_key("10.1038/nature12373", "doi")
        assert key1 == key2

    def test_whitespace_stripped(self):
        """Leading and trailing whitespace should not affect the key."""
        key1 = make_cache_key("  10.1038/nature12373  ", "doi")
        key2 = make_cache_key("10.1038/nature12373", "doi")
        assert key1 == key2

    def test_returns_hex_string(self):
        """Key should be a valid lowercase hex string (SHA-256 = 64 chars)."""
        key = make_cache_key("10.1038/nature12373", "doi")
        assert isinstance(key, str)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_empty_identifier(self):
        """Empty identifier should still produce a valid hash."""
        key = make_cache_key("", "doi")
        assert isinstance(key, str)
        assert len(key) == 64


# ---------------------------------------------------------------------------
# get_cached_verification
# ---------------------------------------------------------------------------

class TestGetCachedVerification:
    """Tests for cache lookup — returns dict or None."""

    @pytest.fixture
    def mock_conn(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        return conn

    async def test_cache_hit_returns_dict(self, mock_conn):
        """A cached, non-expired result should be returned as a dict."""
        cached_row = MagicMock()
        cached_row.verified = True
        cached_row.http_status_code = 200
        cached_row.resolved_url = "https://doi.org/10.1038/nature12373"
        cached_row.resolver_used = "crossref"

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = cached_row
        mock_conn.execute.return_value = mock_result

        result = await get_cached_verification(mock_conn, "10.1038/nature12373", "doi")

        assert result is not None
        assert result["verified"] is True
        assert result["http_status_code"] == 200
        assert result["resolved_url"] == "https://doi.org/10.1038/nature12373"
        assert result["resolver_used"] == "crossref"

    async def test_cache_miss_returns_none(self, mock_conn):
        """When no cached row exists, should return None."""
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await get_cached_verification(mock_conn, "10.1038/nature12373", "doi")

        assert result is None

    async def test_cache_expired_returns_none(self, mock_conn):
        """An expired cache entry should not be returned (DB query filters by expires_at)."""
        # The SQL query itself filters for expires_at > now(), so if the DB
        # returns no row, the entry is expired.
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await get_cached_verification(mock_conn, "10.1038/nature12373", "doi")

        assert result is None

    async def test_unverified_cache_hit(self, mock_conn):
        """A cached result where verified=False should still be returned."""
        cached_row = MagicMock()
        cached_row.verified = False
        cached_row.http_status_code = 404
        cached_row.resolved_url = None
        cached_row.resolver_used = "all_failed"

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = cached_row
        mock_conn.execute.return_value = mock_result

        result = await get_cached_verification(mock_conn, "10.9999/not-real", "doi")

        assert result is not None
        assert result["verified"] is False
        assert result["http_status_code"] == 404


# ---------------------------------------------------------------------------
# store_verification
# ---------------------------------------------------------------------------

class TestStoreVerification:
    """Tests for storing verification results in the cache."""

    @pytest.fixture
    def mock_conn(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        return conn

    async def test_inserts_when_no_existing_row(self, mock_conn):
        """When no row exists for the cache key, an INSERT should occur."""
        # First execute: SELECT for existing row -> None
        select_result = MagicMock()
        select_result.one_or_none.return_value = None

        # Second execute: INSERT
        insert_result = MagicMock()

        mock_conn.execute.side_effect = [select_result, insert_result]

        await store_verification(
            mock_conn,
            identifier="10.1038/nature12373",
            identifier_type="doi",
            verified=True,
            http_status_code=200,
            resolved_url="https://doi.org/10.1038/nature12373",
            resolver_used="crossref",
            ttl_days=30,
        )

        # Two calls: SELECT check + INSERT
        assert mock_conn.execute.call_count == 2

    async def test_updates_when_existing_row(self, mock_conn):
        """When a row already exists, an UPDATE should occur."""
        # First execute: SELECT for existing row -> found
        existing_row = MagicMock()
        existing_row.verification_id = uuid4()
        select_result = MagicMock()
        select_result.one_or_none.return_value = existing_row

        # Second execute: UPDATE
        update_result = MagicMock()

        mock_conn.execute.side_effect = [select_result, update_result]

        await store_verification(
            mock_conn,
            identifier="10.1038/nature12373",
            identifier_type="doi",
            verified=False,
            http_status_code=404,
            resolver_used="all_failed",
            ttl_days=1,
        )

        # Two calls: SELECT check + UPDATE
        assert mock_conn.execute.call_count == 2
