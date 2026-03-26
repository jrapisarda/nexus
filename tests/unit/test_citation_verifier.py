"""Unit tests for nexus_core.citation.verifier — DOI validation and finding citation verification."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus_core.citation.verifier import is_valid_doi_format


# ---------------------------------------------------------------------------
# is_valid_doi_format
# ---------------------------------------------------------------------------

class TestIsValidDoiFormat:
    """Tests for the DOI regex validator."""

    @pytest.mark.parametrize(
        "doi, expected",
        [
            ("10.1038/nature12373", True),
            ("10.1126/science.1185383", True),
            ("10.9999/completely-fake", True),  # format valid even if DOI is fake
            ("10.1000/xyz123", True),
            ("10.12345/some-long.path_with(parens)", True),
            ("not-a-doi", False),
            ("", False),
            ("doi:10.1038/nature12373", False),  # prefix not allowed
            ("https://doi.org/10.1038/nature12373", False),  # URL not a bare DOI
            ("10./missing-registrant", False),
            ("10.12/short", False),  # 2 digits after dot is below 4-digit minimum
        ],
        ids=[
            "nature_doi",
            "science_doi",
            "fake_but_valid_format",
            "simple_doi",
            "complex_doi_chars",
            "random_string",
            "empty_string",
            "doi_prefix",
            "url_form",
            "missing_registrant",
            "short_registrant",
        ],
    )
    def test_doi_format_validation(self, doi, expected):
        result = is_valid_doi_format(doi)
        assert result is expected, f"is_valid_doi_format({doi!r}) should be {expected}"

    def test_whitespace_stripped(self):
        """DOI with leading/trailing whitespace should still match."""
        assert is_valid_doi_format("  10.1038/nature12373  ") is True

    def test_returns_bool(self):
        """Return type should always be bool."""
        assert isinstance(is_valid_doi_format("10.1038/nature12373"), bool)
        assert isinstance(is_valid_doi_format("not-valid"), bool)


# ---------------------------------------------------------------------------
# verify_finding_citations
# ---------------------------------------------------------------------------

class TestVerifyFindingCitations:
    """Tests for verify_finding_citations() — async citation scoring."""

    @pytest.fixture
    def mock_conn(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        return conn

    def _make_finding_row(self, structured_data):
        """Create a mock finding row with structured_data attribute."""
        row = MagicMock()
        row.structured_data = structured_data
        return row

    @patch("nexus_core.citation.verifier.store_verification", new_callable=AsyncMock)
    @patch("nexus_core.citation.verifier.get_cached_verification", new_callable=AsyncMock)
    @patch("nexus_core.citation.verifier._verify_doi_single", new_callable=AsyncMock)
    async def test_two_dois_both_verified_score_1(
        self, mock_verify_doi, mock_cache_get, mock_cache_store, mock_conn
    ):
        """Finding with 2 DOIs, both verified -> score 1.0."""
        from nexus_core.citation.verifier import verify_finding_citations

        finding_id = uuid4()
        structured = {
            "citations": [
                {"doi": "10.1038/nature12373"},
                {"doi": "10.1126/science.1185383"},
            ]
        }

        # DB returns the finding row
        mock_result = MagicMock()
        finding_row = self._make_finding_row(structured)
        mock_result.one_or_none.return_value = finding_row
        mock_conn.execute.return_value = mock_result

        # No cache hits
        mock_cache_get.return_value = None

        # Both DOIs verify successfully
        mock_verify_doi.return_value = {
            "verified": True,
            "resolver_used": "crossref",
            "http_status_code": 200,
            "resolved_url": "https://doi.org/test",
        }

        score = await verify_finding_citations(mock_conn, finding_id)

        assert score == 1.0

    @patch("nexus_core.citation.verifier.store_verification", new_callable=AsyncMock)
    @patch("nexus_core.citation.verifier.get_cached_verification", new_callable=AsyncMock)
    @patch("nexus_core.citation.verifier._verify_doi_single", new_callable=AsyncMock)
    async def test_two_dois_one_verified_score_half(
        self, mock_verify_doi, mock_cache_get, mock_cache_store, mock_conn
    ):
        """Finding with 2 DOIs, 1 verified 1 not -> score 0.5."""
        from nexus_core.citation.verifier import verify_finding_citations

        finding_id = uuid4()
        structured = {
            "citations": [
                {"doi": "10.1038/nature12373"},
                {"doi": "10.9999/does-not-exist"},
            ]
        }

        mock_result = MagicMock()
        finding_row = self._make_finding_row(structured)
        mock_result.one_or_none.return_value = finding_row
        mock_conn.execute.return_value = mock_result

        mock_cache_get.return_value = None

        # First DOI verified, second not
        mock_verify_doi.side_effect = [
            {"verified": True, "resolver_used": "crossref", "http_status_code": 200, "resolved_url": "https://doi.org/test"},
            {"verified": False, "resolver_used": "all_failed", "http_status_code": None},
        ]

        score = await verify_finding_citations(mock_conn, finding_id)

        assert score == 0.5

    @patch("nexus_core.citation.verifier.store_verification", new_callable=AsyncMock)
    @patch("nexus_core.citation.verifier.get_cached_verification", new_callable=AsyncMock)
    async def test_no_citations_returns_half(self, mock_cache_get, mock_cache_store, mock_conn):
        """Finding with no citations -> score 0.5 (unverifiable, not penalized)."""
        from nexus_core.citation.verifier import verify_finding_citations

        finding_id = uuid4()
        structured = {"citations": []}

        mock_result = MagicMock()
        finding_row = self._make_finding_row(structured)
        mock_result.one_or_none.return_value = finding_row
        mock_conn.execute.return_value = mock_result

        score = await verify_finding_citations(mock_conn, finding_id)

        assert score == 0.5

    @patch("nexus_core.citation.verifier.store_verification", new_callable=AsyncMock)
    @patch("nexus_core.citation.verifier.get_cached_verification", new_callable=AsyncMock)
    async def test_structured_data_none_returns_half(self, mock_cache_get, mock_cache_store, mock_conn):
        """Finding with structured_data=None -> score 0.5."""
        from nexus_core.citation.verifier import verify_finding_citations

        finding_id = uuid4()

        mock_result = MagicMock()
        finding_row = self._make_finding_row(None)
        mock_result.one_or_none.return_value = finding_row
        mock_conn.execute.return_value = mock_result

        score = await verify_finding_citations(mock_conn, finding_id)

        assert score == 0.5

    @patch("nexus_core.citation.verifier.store_verification", new_callable=AsyncMock)
    @patch("nexus_core.citation.verifier.get_cached_verification", new_callable=AsyncMock)
    async def test_finding_not_found_returns_half(self, mock_cache_get, mock_cache_store, mock_conn):
        """When the finding row does not exist, return 0.5."""
        from nexus_core.citation.verifier import verify_finding_citations

        finding_id = uuid4()

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        mock_conn.execute.return_value = mock_result

        score = await verify_finding_citations(mock_conn, finding_id)

        assert score == 0.5

    @patch("nexus_core.citation.verifier.store_verification", new_callable=AsyncMock)
    @patch("nexus_core.citation.verifier.get_cached_verification", new_callable=AsyncMock)
    @patch("nexus_core.citation.verifier._verify_doi_single", new_callable=AsyncMock)
    async def test_cache_hit_uses_cached_result(
        self, mock_verify_doi, mock_cache_get, mock_cache_store, mock_conn
    ):
        """When a cached verification exists, the external call should be skipped."""
        from nexus_core.citation.verifier import verify_finding_citations

        finding_id = uuid4()
        structured = {
            "citations": [
                {"doi": "10.1038/nature12373"},
            ]
        }

        mock_result = MagicMock()
        finding_row = self._make_finding_row(structured)
        mock_result.one_or_none.return_value = finding_row
        mock_conn.execute.return_value = mock_result

        # Cache hit returns verified
        mock_cache_get.return_value = {
            "verified": True,
            "http_status_code": 200,
            "resolved_url": "https://doi.org/test",
            "resolver_used": "crossref",
        }

        score = await verify_finding_citations(mock_conn, finding_id)

        assert score == 1.0
        # External DOI verification should NOT have been called
        mock_verify_doi.assert_not_called()
        # Cache store should NOT have been called (result was cached)
        mock_cache_store.assert_not_called()

    @patch("nexus_core.citation.verifier.store_verification", new_callable=AsyncMock)
    @patch("nexus_core.citation.verifier.get_cached_verification", new_callable=AsyncMock)
    async def test_citations_with_na_doi_treated_as_empty(self, mock_cache_get, mock_cache_store, mock_conn):
        """Citations where doi is 'N/A' or 'none' should be ignored."""
        from nexus_core.citation.verifier import verify_finding_citations

        finding_id = uuid4()
        structured = {
            "citations": [
                {"doi": "N/A"},
                {"doi": "none"},
            ]
        }

        mock_result = MagicMock()
        finding_row = self._make_finding_row(structured)
        mock_result.one_or_none.return_value = finding_row
        mock_conn.execute.return_value = mock_result

        score = await verify_finding_citations(mock_conn, finding_id)

        # No actual DOIs to verify -> 0.5
        assert score == 0.5
