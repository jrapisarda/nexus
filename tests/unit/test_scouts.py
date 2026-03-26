"""Unit tests for NEXUS scouts (Phase 5).

Tests use mock httpx responses to avoid real HTTP requests.
"""

import asyncio
import json
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nexus_core.scouts.base import BaseScout, ScoutFinding
from nexus_core.scouts.pubmed import PubMedScout
from nexus_core.scouts.clinicaltrials import ClinicalTrialsScout
from nexus_core.scouts.biorxiv import BioRxivScout
from nexus_core.scouts.patents_uspto import USPTOScout
from nexus_core.scouts.patents_google import GooglePatentsScout


def _make_response(status_code: int, *, text: str | None = None, json_data: dict | None = None) -> httpx.Response:
    """Create an httpx.Response with a dummy request (required for raise_for_status)."""
    if json_data is not None:
        resp = httpx.Response(status_code, json=json_data)
    else:
        resp = httpx.Response(status_code, text=text or "")
    resp.request = httpx.Request("GET", "https://mock.test/")
    return resp


# ---------------------------------------------------------------------------
# ScoutFinding dataclass
# ---------------------------------------------------------------------------

class TestScoutFinding:
    def test_required_fields(self):
        f = ScoutFinding(
            title="Test",
            abstract="An abstract",
            source_url="https://example.com",
            source_type="pubmed",
        )
        assert f.title == "Test"
        assert f.abstract == "An abstract"
        assert f.source_url == "https://example.com"
        assert f.source_type == "pubmed"

    def test_defaults(self):
        f = ScoutFinding(
            title="T", abstract="A", source_url="http://x", source_type="pubmed"
        )
        assert f.relevance_score == 0.0
        assert f.raw_data == {}
        assert f.authors == []
        assert f.published_date is None
        assert f.doi is None

    def test_optional_fields(self):
        f = ScoutFinding(
            title="T",
            abstract="A",
            source_url="http://x",
            source_type="biorxiv",
            relevance_score=0.85,
            raw_data={"key": "value"},
            authors=["Smith J", "Doe A"],
            published_date="2025-06",
            doi="10.1234/test",
        )
        assert f.relevance_score == 0.85
        assert f.doi == "10.1234/test"
        assert len(f.authors) == 2


# ---------------------------------------------------------------------------
# BaseScout ABC enforcement
# ---------------------------------------------------------------------------

class TestBaseScout:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseScout()

    def test_concrete_subclass_must_implement_methods(self):
        class IncompleteScout(BaseScout):
            pass

        with pytest.raises(TypeError):
            IncompleteScout()

    def test_complete_subclass_works(self):
        class GoodScout(BaseScout):
            @property
            def source_name(self) -> str:
                return "test"

            async def search(self, query, limit=10):
                return []

            async def scan_for_topics(self, topics, limit_per_topic=5):
                return []

        s = GoodScout()
        assert s.source_name == "test"


# ---------------------------------------------------------------------------
# PubMedScout
# ---------------------------------------------------------------------------

# Sample XML responses for PubMed
ESEARCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<eSearchResult>
    <IdList>
        <Id>12345678</Id>
        <Id>87654321</Id>
    </IdList>
</eSearchResult>"""

EFETCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
    <PubmedArticle>
        <MedlineCitation>
            <PMID>12345678</PMID>
            <Article>
                <ArticleTitle>Test Article Title</ArticleTitle>
                <Abstract>
                    <AbstractText>This is the abstract text.</AbstractText>
                </Abstract>
                <AuthorList>
                    <Author>
                        <LastName>Smith</LastName>
                        <ForeName>John</ForeName>
                    </Author>
                </AuthorList>
                <Journal>
                    <JournalIssue>
                        <PubDate>
                            <Year>2025</Year>
                            <Month>Jan</Month>
                        </PubDate>
                    </JournalIssue>
                </Journal>
            </Article>
        </MedlineCitation>
        <PubmedData>
            <ArticleIdList>
                <ArticleId IdType="doi">10.1234/test.2025</ArticleId>
            </ArticleIdList>
        </PubmedData>
    </PubmedArticle>
</PubmedArticleSet>"""


class TestPubMedScout:
    def test_source_name(self):
        scout = PubMedScout()
        assert scout.source_name == "pubmed"

    def test_source_name_with_api_key(self):
        scout = PubMedScout(api_key="test-key")
        assert scout.source_name == "pubmed"

    @pytest.mark.asyncio
    async def test_search_success(self):
        scout = PubMedScout()

        # Mock HTTP responses
        responses = [
            _make_response(200, text=ESEARCH_XML),
            _make_response(200, text=EFETCH_XML),
        ]
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.search("CRISPR gene therapy", limit=5)
        assert len(results) == 1
        assert results[0].title == "Test Article Title"
        assert results[0].source_type == "pubmed"
        assert results[0].source_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
        assert results[0].doi == "10.1234/test.2025"
        assert "Smith" in results[0].authors[0]

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        scout = PubMedScout()

        empty_xml = """<?xml version="1.0"?>
        <eSearchResult><IdList></IdList></eSearchResult>"""

        async def mock_get(url, **kwargs):
            return _make_response(200, text=empty_xml)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.search("xyznonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_http_error(self):
        scout = PubMedScout()

        async def mock_get(url, **kwargs):
            resp = httpx.Response(500, text="Server Error")
            resp.request = httpx.Request("GET", url if isinstance(url, str) else "https://mock.test/")
            raise httpx.HTTPStatusError("500", request=resp.request, response=resp)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        # Should not raise — returns empty list
        results = await scout.search("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_scan_for_topics(self):
        scout = PubMedScout()

        call_index = 0

        async def mock_get(url, **kwargs):
            nonlocal call_index
            if call_index % 2 == 0:
                call_index += 1
                return _make_response(200, text=ESEARCH_XML)
            else:
                call_index += 1
                return _make_response(200, text=EFETCH_XML)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.scan_for_topics(["topic1", "topic2"], limit_per_topic=2)
        # Both topics return the same article, dedup by URL
        assert len(results) == 1

    def test_parse_article_no_abstract(self):
        scout = PubMedScout()
        xml = """<PubmedArticle>
            <MedlineCitation>
                <PMID>99999</PMID>
                <Article>
                    <ArticleTitle>No Abstract Article</ArticleTitle>
                </Article>
            </MedlineCitation>
        </PubmedArticle>"""
        elem = ET.fromstring(xml)
        finding = scout._parse_article(elem)
        assert finding is not None
        assert finding.abstract == "No abstract available."


# ---------------------------------------------------------------------------
# ClinicalTrialsScout
# ---------------------------------------------------------------------------

CLINICALTRIALS_RESPONSE = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT00000001",
                    "briefTitle": "Test Clinical Trial",
                },
                "descriptionModule": {
                    "briefSummary": "A brief summary of the trial.",
                },
                "statusModule": {
                    "overallStatus": "Recruiting",
                    "startDateStruct": {"date": "2025-01-15"},
                },
                "contactsLocationsModule": {
                    "overallOfficials": [
                        {"name": "Dr. Jane Doe"},
                    ],
                },
                "designModule": {
                    "phases": ["PHASE3"],
                },
            }
        }
    ]
}


class TestClinicalTrialsScout:
    def test_source_name(self):
        scout = ClinicalTrialsScout()
        assert scout.source_name == "clinicaltrials"

    @pytest.mark.asyncio
    async def test_search_success(self):
        scout = ClinicalTrialsScout()

        async def mock_get(url, **kwargs):
            return _make_response(200, json_data=CLINICALTRIALS_RESPONSE)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.search("cancer immunotherapy", limit=5)
        assert len(results) == 1
        assert results[0].title == "Test Clinical Trial"
        assert results[0].source_type == "clinicaltrials"
        assert "NCT00000001" in results[0].source_url
        assert results[0].raw_data["nct_id"] == "NCT00000001"
        assert results[0].raw_data["overall_status"] == "Recruiting"

    @pytest.mark.asyncio
    async def test_search_empty(self):
        scout = ClinicalTrialsScout()

        async def mock_get(url, **kwargs):
            return _make_response(200, json_data={"studies": []})

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.search("xyznonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_error(self):
        scout = ClinicalTrialsScout()

        async def mock_get(url, **kwargs):
            resp = httpx.Response(503, text="Service Unavailable")
            resp.request = httpx.Request("GET", "https://mock.test/")
            raise httpx.HTTPStatusError("503", request=resp.request, response=resp)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.search("test")
        assert results == []

    def test_parse_study_missing_fields(self):
        scout = ClinicalTrialsScout()
        study = {"protocolSection": {}}
        finding = scout._parse_study(study)
        assert finding.title == "Untitled Study"
        assert finding.abstract == "No summary available."
        assert finding.source_url == ""


# ---------------------------------------------------------------------------
# BioRxivScout
# ---------------------------------------------------------------------------

BIORXIV_RESPONSE = {
    "messages": [{"total": "2"}],
    "collection": [
        {
            "doi": "10.1101/2025.01.01.000001",
            "title": "CRISPR Advances in Gene Therapy",
            "abstract": "A preprint about CRISPR gene therapy advances.",
            "authors": "Smith, J; Doe, A",
            "date": "2025-01-15",
        },
        {
            "doi": "10.1101/2025.01.02.000002",
            "title": "Unrelated Preprint",
            "abstract": "Something about butterfly migration patterns.",
            "authors": "Jones, B",
            "date": "2025-01-16",
        },
    ],
}


class TestBioRxivScout:
    def test_source_name(self):
        scout = BioRxivScout()
        assert scout.source_name == "biorxiv"

    @pytest.mark.asyncio
    async def test_search_filters_by_query(self):
        scout = BioRxivScout(include_medrxiv=False)

        async def mock_get(url, **kwargs):
            return _make_response(200, json_data=BIORXIV_RESPONSE)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.search("CRISPR gene therapy", limit=10)
        # Only the first article should match (contains CRISPR, gene, therapy)
        assert len(results) >= 1
        assert "CRISPR" in results[0].title

    @pytest.mark.asyncio
    async def test_search_includes_medrxiv(self):
        scout = BioRxivScout(include_medrxiv=True)

        async def mock_get(url, **kwargs):
            return _make_response(200, json_data=BIORXIV_RESPONSE)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.search("CRISPR gene therapy", limit=10)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_empty_collection(self):
        scout = BioRxivScout(include_medrxiv=False)

        async def mock_get(url, **kwargs):
            return _make_response(200, json_data={"messages": [{"total": "0"}], "collection": []})

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.search("something")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_error(self):
        scout = BioRxivScout(include_medrxiv=False)

        async def mock_get(url, **kwargs):
            resp = httpx.Response(500, text="Error")
            resp.request = httpx.Request("GET", "https://mock.test/")
            raise httpx.HTTPStatusError("500", request=resp.request, response=resp)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.search("test")
        assert results == []

    def test_filter_by_query_relevance_scoring(self):
        scout = BioRxivScout()
        preprints = [
            {"doi": "10.1/a", "title": "CRISPR Gene Therapy Results", "abstract": "CRISPR therapy study", "authors": "X", "date": "2025-01"},
            {"doi": "10.1/b", "title": "Unrelated Study", "abstract": "Nothing matching", "authors": "Y", "date": "2025-01"},
        ]
        results = scout._filter_by_query(preprints, "CRISPR therapy", "biorxiv")
        assert len(results) >= 1
        # First result should be the CRISPR one
        assert results[0].doi == "10.1/a"


# ---------------------------------------------------------------------------
# USPTOScout
# ---------------------------------------------------------------------------

USPTO_RESPONSE = {
    "patents": [
        {
            "patent_id": "11000001",
            "patent_title": "Novel CRISPR Delivery Method",
            "patent_abstract": "A method for delivering CRISPR components to target cells.",
            "patent_date": "2025-01-10",
            "inventors": [
                {"inventor_name_first": "Alice", "inventor_name_last": "Wang"},
                {"inventor_name_first": "Bob", "inventor_name_last": "Chen"},
            ],
        }
    ]
}


class TestUSPTOScout:
    def test_source_name(self):
        scout = USPTOScout()
        assert scout.source_name == "uspto"

    def test_source_name_with_api_key(self):
        scout = USPTOScout(api_key="test-key")
        assert scout.source_name == "uspto"
        assert scout._build_headers()["X-Api-Key"] == "test-key"

    @pytest.mark.asyncio
    async def test_search_success_uses_current_patentsview_query_shape(self):
        scout = USPTOScout(api_key="test-key")
        captured_params = {}

        async def mock_get(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return _make_response(200, json_data=USPTO_RESPONSE)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        with patch("nexus_core.scouts.patents_uspto.asyncio.sleep", new=AsyncMock()):
            results = await scout.search("CRISPR delivery", limit=5)

        assert len(results) == 1
        assert results[0].title == "Novel CRISPR Delivery Method"
        assert results[0].source_type == "uspto"
        assert "11000001" in results[0].source_url
        assert len(results[0].authors) == 2
        assert "Alice Wang" in results[0].authors
        assert '"patent_id"' in captured_params["f"]
        assert '"inventors.inventor_name_first"' in captured_params["f"]
        assert '"size":5' in captured_params["o"]
        assert "per_page" not in captured_params["o"]
        assert "patent_title" in captured_params["q"]
        assert "patent_abstract" in captured_params["q"]

    @pytest.mark.asyncio
    async def test_search_missing_api_key_skips_request(self):
        scout = USPTOScout()
        scout._client = AsyncMock()

        results = await scout.search("governance")

        assert results == []
        scout._client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_no_patents(self):
        scout = USPTOScout(api_key="test-key")

        async def mock_get(url, **kwargs):
            return _make_response(200, json_data={"patents": None})

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        with patch("nexus_core.scouts.patents_uspto.asyncio.sleep", new=AsyncMock()):
            results = await scout.search("xyz")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_403_without_retry(self):
        scout = USPTOScout(api_key="test-key")
        calls = {"count": 0}

        async def mock_get(url, **kwargs):
            calls["count"] += 1
            resp = httpx.Response(403, text="Forbidden")
            resp.request = httpx.Request("GET", "https://mock.test/")
            raise httpx.HTTPStatusError("403", request=resp.request, response=resp)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(10)

        results = await scout.search("test")
        assert results == []
        assert calls["count"] == 1


# ---------------------------------------------------------------------------
# GooglePatentsScout
# ---------------------------------------------------------------------------

class TestGooglePatentsScout:
    def test_source_name(self):
        scout = GooglePatentsScout()
        assert scout.source_name == "google_patents"

    @pytest.mark.asyncio
    async def test_search_success(self):
        scout = GooglePatentsScout()
        payload = {
            "results": {
                "cluster": [
                    {
                        "result": [
                            {
                                "id": "patent/US1234567A1/en",
                                "patent": {
                                    "title": "<b>Quantum</b> decoder patent",
                                    "snippet": "Neural <b>decoder</b> for error correction.",
                                    "inventor": "Alice Example; Bob Example",
                                    "publication_number": "US1234567A1",
                                    "language": "en",
                                    "publication_date": "2025-01-02",
                                },
                            }
                        ]
                    }
                ]
            }
        }

        async def mock_get(url, **kwargs):
            return _make_response(200, json_data=payload)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(2)

        results = await scout.search("quantum decoder", limit=5)

        assert len(results) == 1
        assert results[0].title == "Quantum decoder patent"
        assert results[0].abstract == "Neural decoder for error correction."
        assert results[0].source_url == "https://patents.google.com/patent/US1234567A1/en"
        assert results[0].authors == ["Alice Example", "Bob Example"]
        assert results[0].published_date == "2025-01-02"

    @pytest.mark.asyncio
    async def test_scan_for_topics_deduplicates_results(self):
        scout = GooglePatentsScout()
        payload = {
            "results": {
                "cluster": [
                    {
                        "result": [
                            {
                                "id": "patent/US1234567A1/en",
                                "patent": {
                                    "title": "Quantum decoder patent",
                                    "snippet": "Neural decoder for error correction.",
                                    "inventor": "Alice Example",
                                    "publication_number": "US1234567A1",
                                    "language": "en",
                                    "publication_date": "2025-01-02",
                                },
                            }
                        ]
                    }
                ]
            }
        }

        async def mock_get(url, **kwargs):
            return _make_response(200, json_data=payload)

        scout._client = AsyncMock()
        scout._client.get = mock_get
        scout._semaphore = asyncio.Semaphore(2)

        results = await scout.scan_for_topics(["topic1", "topic2"], limit_per_topic=2)
        assert len(results) == 1
