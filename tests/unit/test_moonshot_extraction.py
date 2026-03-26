"""Unit tests for nexus_core.utils.moonshot_extraction — MoonshotExtractionService."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus_core.utils.moonshot_extraction import MoonshotExtractionService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_openai_client():
    """Create a mock AsyncOpenAI client with files sub-API."""
    client = AsyncMock()
    client.files = AsyncMock()
    client.files.create = AsyncMock()
    client.files.content = AsyncMock()
    client.files.delete = AsyncMock()
    return client


@pytest.fixture
def service(mock_openai_client):
    return MoonshotExtractionService(mock_openai_client)


# ---------------------------------------------------------------------------
# extract() — successful extraction
# ---------------------------------------------------------------------------

class TestExtractSuccess:
    """Verify extract() returns (text, file_id) on successful extraction."""

    async def test_extract_pdf_returns_text_and_file_id(self, service, mock_openai_client):
        """A PDF file with extractable content returns (text, file_id)."""
        file_obj = MagicMock()
        file_obj.id = "file-abc123"
        mock_openai_client.files.create.return_value = file_obj

        content_obj = MagicMock()
        content_obj.text = "Extracted document text from the PDF."
        mock_openai_client.files.content.return_value = content_obj

        text, file_id = await service.extract(
            file_path=Path("/uploads/report.pdf"),
            content_type="application/pdf",
        )

        assert text == "Extracted document text from the PDF."
        assert file_id == "file-abc123"
        mock_openai_client.files.create.assert_called_once()
        mock_openai_client.files.content.assert_called_once_with("file-abc123")

    async def test_extract_docx_by_extension(self, service, mock_openai_client):
        """A .docx file is extractable even if content_type is generic."""
        file_obj = MagicMock()
        file_obj.id = "file-docx456"
        mock_openai_client.files.create.return_value = file_obj

        content_obj = MagicMock()
        content_obj.text = "Extracted from DOCX."
        mock_openai_client.files.content.return_value = content_obj

        text, file_id = await service.extract(
            file_path=Path("/uploads/document.docx"),
            content_type="application/octet-stream",
        )

        assert text == "Extracted from DOCX."
        assert file_id == "file-docx456"

    async def test_extract_xlsx_by_mime(self, service, mock_openai_client):
        """An .xlsx file is extractable by its MIME type."""
        file_obj = MagicMock()
        file_obj.id = "file-xlsx789"
        mock_openai_client.files.create.return_value = file_obj

        content_obj = MagicMock()
        content_obj.text = "Spreadsheet data extracted."
        mock_openai_client.files.content.return_value = content_obj

        text, file_id = await service.extract(
            file_path=Path("/uploads/data.xlsx"),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        assert text == "Spreadsheet data extracted."
        assert file_id == "file-xlsx789"


# ---------------------------------------------------------------------------
# extract() — not extractable
# ---------------------------------------------------------------------------

class TestExtractNotExtractable:
    """Verify extract() returns (None, None) for non-extractable files."""

    async def test_csv_not_extractable(self, service, mock_openai_client):
        """A CSV file is not extractable and should return (None, None)."""
        text, file_id = await service.extract(
            file_path=Path("/uploads/data.csv"),
            content_type="text/csv",
        )

        assert text is None
        assert file_id is None
        mock_openai_client.files.create.assert_not_called()

    async def test_png_not_extractable(self, service, mock_openai_client):
        """An image file is not extractable."""
        text, file_id = await service.extract(
            file_path=Path("/uploads/image.png"),
            content_type="image/png",
        )

        assert text is None
        assert file_id is None

    async def test_txt_not_extractable(self, service, mock_openai_client):
        """A plain text file is not extractable."""
        text, file_id = await service.extract(
            file_path=Path("/uploads/notes.txt"),
            content_type="text/plain",
        )

        assert text is None
        assert file_id is None

    async def test_json_not_extractable(self, service, mock_openai_client):
        """A JSON file is not extractable."""
        text, file_id = await service.extract(
            file_path=Path("/uploads/config.json"),
            content_type="application/json",
        )

        assert text is None
        assert file_id is None


# ---------------------------------------------------------------------------
# extract() — API exceptions
# ---------------------------------------------------------------------------

class TestExtractApiException:
    """Verify extract() returns (None, None) when Moonshot API raises."""

    async def test_extract_create_raises_exception(self, service, mock_openai_client):
        """If files.create raises, extract() returns (None, None)."""
        mock_openai_client.files.create.side_effect = RuntimeError("API connection refused")

        text, file_id = await service.extract(
            file_path=Path("/uploads/report.pdf"),
            content_type="application/pdf",
        )

        assert text is None
        assert file_id is None

    async def test_extract_content_raises_exception(self, service, mock_openai_client):
        """If files.content raises after successful create, returns (None, None)."""
        file_obj = MagicMock()
        file_obj.id = "file-err"
        mock_openai_client.files.create.return_value = file_obj
        mock_openai_client.files.content.side_effect = ValueError("Malformed response")

        text, file_id = await service.extract(
            file_path=Path("/uploads/report.pdf"),
            content_type="application/pdf",
        )

        assert text is None
        assert file_id is None

    async def test_extract_http_error(self, service, mock_openai_client):
        """HTTP errors from the API are caught gracefully."""
        mock_openai_client.files.create.side_effect = Exception("HTTP 500 Internal Server Error")

        text, file_id = await service.extract(
            file_path=Path("/uploads/report.pdf"),
            content_type="application/pdf",
        )

        assert text is None
        assert file_id is None


# ---------------------------------------------------------------------------
# extract() — timeout
# ---------------------------------------------------------------------------

class TestExtractTimeout:
    """Verify extract() returns (None, None) on timeout."""

    async def test_extract_timeout_on_create(self, service, mock_openai_client):
        """If file upload times out, extract() returns (None, None)."""

        async def slow_create(*args, **kwargs):
            await asyncio.sleep(10)

        mock_openai_client.files.create.side_effect = slow_create

        text, file_id = await service.extract(
            file_path=Path("/uploads/report.pdf"),
            content_type="application/pdf",
            timeout_secs=0.01,
        )

        assert text is None
        assert file_id is None

    async def test_extract_timeout_on_content(self, service, mock_openai_client):
        """If content retrieval times out, extract() returns (None, None)."""
        file_obj = MagicMock()
        file_obj.id = "file-slow"
        mock_openai_client.files.create.return_value = file_obj

        async def slow_content(*args, **kwargs):
            await asyncio.sleep(10)

        mock_openai_client.files.content.side_effect = slow_content

        text, file_id = await service.extract(
            file_path=Path("/uploads/report.pdf"),
            content_type="application/pdf",
            timeout_secs=0.01,
        )

        assert text is None
        assert file_id is None


# ---------------------------------------------------------------------------
# extract() — empty content
# ---------------------------------------------------------------------------

class TestExtractEmptyContent:
    """Verify extract() handles empty extracted text."""

    async def test_extract_empty_text_returns_none_text(self, service, mock_openai_client):
        """If extracted text is empty, returns (None, file_id)."""
        file_obj = MagicMock()
        file_obj.id = "file-empty"
        mock_openai_client.files.create.return_value = file_obj

        content_obj = MagicMock()
        content_obj.text = ""
        mock_openai_client.files.content.return_value = content_obj

        text, file_id = await service.extract(
            file_path=Path("/uploads/blank.pdf"),
            content_type="application/pdf",
        )

        assert text is None
        assert file_id == "file-empty"

    async def test_extract_whitespace_only_returns_none_text(self, service, mock_openai_client):
        """If extracted text is only whitespace, returns (None, file_id)."""
        file_obj = MagicMock()
        file_obj.id = "file-ws"
        mock_openai_client.files.create.return_value = file_obj

        content_obj = MagicMock()
        content_obj.text = "   \n\t  "
        mock_openai_client.files.content.return_value = content_obj

        text, file_id = await service.extract(
            file_path=Path("/uploads/whitespace.pdf"),
            content_type="application/pdf",
        )

        assert text is None
        assert file_id == "file-ws"


# ---------------------------------------------------------------------------
# write_sidecar()
# ---------------------------------------------------------------------------

class TestWriteSidecar:
    """Verify write_sidecar() creates a .txt file next to the original."""

    async def test_write_sidecar_creates_txt_file(self, service, tmp_path):
        """write_sidecar() writes extracted text to a .txt sidecar file."""
        original = tmp_path / "document.pdf"
        original.write_bytes(b"%PDF-fake")

        sidecar_path = await service.write_sidecar(original, "Extracted text content")

        assert sidecar_path == tmp_path / "document.pdf.txt"
        assert sidecar_path.exists()
        assert sidecar_path.read_text("utf-8") == "Extracted text content"

    async def test_write_sidecar_preserves_double_extension(self, service, tmp_path):
        """The sidecar appends .txt after the full original suffix."""
        original = tmp_path / "data.xlsx"
        original.write_bytes(b"fake-xlsx")

        sidecar_path = await service.write_sidecar(original, "Spreadsheet data")

        assert sidecar_path.name == "data.xlsx.txt"
        assert sidecar_path.read_text("utf-8") == "Spreadsheet data"

    async def test_write_sidecar_unicode_content(self, service, tmp_path):
        """write_sidecar() handles unicode text properly."""
        original = tmp_path / "report.pdf"
        original.write_bytes(b"%PDF-fake")

        unicode_text = "Datos del paciente: cafe\u0301, ni\u00f1o, \u00fcber"
        sidecar_path = await service.write_sidecar(original, unicode_text)

        assert sidecar_path.read_text("utf-8") == unicode_text

    async def test_write_sidecar_returns_path(self, service, tmp_path):
        """write_sidecar() returns the Path to the newly created file."""
        original = tmp_path / "file.docx"
        original.write_bytes(b"docx-fake")

        result = await service.write_sidecar(original, "content")
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# delete_remote_file()
# ---------------------------------------------------------------------------

class TestDeleteRemoteFile:
    """Verify delete_remote_file() calls the mock client."""

    async def test_delete_remote_file_calls_client(self, service, mock_openai_client):
        """delete_remote_file() delegates to client.files.delete."""
        await service.delete_remote_file("file-xyz")

        mock_openai_client.files.delete.assert_called_once_with("file-xyz")

    async def test_delete_remote_file_handles_exception(self, service, mock_openai_client):
        """delete_remote_file() does not raise if the API call fails."""
        mock_openai_client.files.delete.side_effect = RuntimeError("Not found")

        # Should not raise
        await service.delete_remote_file("file-missing")

    async def test_delete_remote_file_with_valid_id(self, service, mock_openai_client):
        """delete_remote_file() passes the exact file ID to the client."""
        await service.delete_remote_file("file-abc-123-def")

        call_args = mock_openai_client.files.delete.call_args
        assert call_args[0][0] == "file-abc-123-def"
