"""Unit tests for nexus_api.routers.files — file upload and retrieval endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import httpx

from nexus_api.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_ATTACHMENT_ID = uuid4()
_FAKE_CREATED_AT = datetime(2026, 3, 23, 12, 0, 0, tzinfo=timezone.utc)


def _make_fake_row(
    *,
    attachment_id: UUID | None = None,
    original_filename: str = "data.csv",
    content_type: str = "text/csv",
    size_bytes: int = 42,
    upload_status: str = "uploaded",
    created_at: datetime | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace that behaves like a SQLAlchemy Row."""
    return SimpleNamespace(
        attachment_id=attachment_id or _FAKE_ATTACHMENT_ID,
        original_filename=original_filename,
        stored_path="/tmp/uploads/pending/fake.csv",
        content_type=content_type,
        size_bytes=size_bytes,
        extraction_text_path=None,
        moonshot_file_id=None,
        upload_status=upload_status,
        created_at=created_at or _FAKE_CREATED_AT,
    )


def _build_mock_connection(*, insert_row=None, select_row=None):
    """Return an async context manager mock that mimics get_connection().

    Parameters:
        insert_row: The row returned by INSERT ... RETURNING.
        select_row: The row returned by SELECT (for GET endpoint).
    """
    mock_conn = AsyncMock()

    # conn.execute() returns a result proxy
    mock_result = MagicMock()
    if insert_row is not None:
        mock_result.first.return_value = insert_row
    elif select_row is not None:
        mock_result.first.return_value = select_row
    else:
        mock_result.first.return_value = None

    mock_conn.execute = AsyncMock(return_value=mock_result)

    # conn.begin() returns an async context manager (for transactions)
    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=mock_begin)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_conn.begin = MagicMock(return_value=mock_begin)

    # The inner execute on the transaction should also work
    mock_begin.execute = mock_conn.execute

    @asynccontextmanager
    async def _fake_get_connection(settings=None):
        yield mock_conn

    return _fake_get_connection, mock_conn


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

class TestFileRouteRegistration:
    """Verify file upload routes are registered on the FastAPI app."""

    def _get_paths(self):
        paths = []
        for route in app.routes:
            methods = getattr(route, "methods", None)
            path = getattr(route, "path", None)
            if methods and path:
                for m in methods:
                    paths.append((m, path))
        return paths

    def test_post_files_route_registered(self):
        paths = self._get_paths()
        assert ("POST", "/api/files") in paths

    def test_get_files_by_id_route_registered(self):
        paths = self._get_paths()
        assert ("GET", "/api/files/{attachment_id}") in paths


class TestFileRouterPrefix:
    """Verify the files router has the correct prefix."""

    def test_files_prefix(self):
        from nexus_api.routers import files
        assert files.router.prefix == "/api/files"


# ---------------------------------------------------------------------------
# POST /api/files — upload
# ---------------------------------------------------------------------------

class TestUploadFile:
    """Test the POST /api/files endpoint."""

    @pytest.fixture(autouse=True)
    def _patch_uploads_dir(self, tmp_path):
        """Patch UPLOADS_DIR so files are written to a temp directory."""
        self._uploads_dir = tmp_path / "uploads"
        self._uploads_dir.mkdir()

    async def _post_file(
        self,
        filename: str,
        content: bytes,
        content_type: str = "text/csv",
        *,
        insert_row=None,
    ):
        """Helper to POST a file with mocked DB and settings."""
        if insert_row is None:
            insert_row = _make_fake_row(
                original_filename=filename,
                content_type=content_type,
                size_bytes=len(content),
            )

        fake_get_connection, _ = _build_mock_connection(insert_row=insert_row)

        with (
            patch("nexus_api.routers.files.get_connection", fake_get_connection),
            patch(
                "nexus_api.routers.files.get_settings",
                return_value=SimpleNamespace(
                    MAX_FILE_SIZE_BYTES=20_971_520,
                    UPLOADS_DIR=str(self._uploads_dir),
                ),
            ),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/files",
                    files={"file": (filename, BytesIO(content), content_type)},
                )
        return response

    async def test_upload_valid_csv_returns_200(self):
        response = await self._post_file("data.csv", b"col1,col2\na,b\n")
        assert response.status_code == 200
        body = response.json()
        assert "attachment_id" in body
        assert body["original_filename"] == "data.csv"
        assert body["upload_status"] == "uploaded"

    async def test_upload_valid_pdf_returns_200(self):
        # PDF magic bytes
        pdf_bytes = b"%PDF-1.4 fake content"
        row = _make_fake_row(
            original_filename="paper.pdf",
            content_type="application/pdf",
            size_bytes=len(pdf_bytes),
        )
        response = await self._post_file(
            "paper.pdf", pdf_bytes, "application/pdf", insert_row=row
        )
        assert response.status_code == 200
        body = response.json()
        assert body["original_filename"] == "paper.pdf"

    async def test_upload_disallowed_extension_returns_422(self):
        response = await self._post_file("malware.exe", b"MZ\x90\x00")
        assert response.status_code == 422
        body = response.json()
        assert "not allowed" in body["detail"].lower() or "extension" in body["detail"].lower()

    async def test_upload_bat_extension_returns_422(self):
        response = await self._post_file("script.bat", b"echo hello")
        assert response.status_code == 422

    async def test_upload_empty_file_returns_422(self):
        response = await self._post_file("empty.csv", b"")
        assert response.status_code == 422
        body = response.json()
        assert "empty" in body["detail"].lower()

    async def test_upload_response_contains_expected_fields(self):
        response = await self._post_file("report.txt", b"some text content")
        assert response.status_code == 200
        body = response.json()
        expected_fields = {
            "attachment_id",
            "original_filename",
            "content_type",
            "size_bytes",
            "upload_status",
            "created_at",
        }
        assert expected_fields.issubset(body.keys())


# ---------------------------------------------------------------------------
# GET /api/files/{attachment_id} — retrieval
# ---------------------------------------------------------------------------

class TestGetAttachment:
    """Test the GET /api/files/{attachment_id} endpoint."""

    async def _get_attachment(self, attachment_id: str, *, select_row=None):
        """Helper to GET attachment metadata with mocked DB."""
        fake_get_connection, _ = _build_mock_connection(select_row=select_row)

        with patch("nexus_api.routers.files.get_connection", fake_get_connection):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"/api/files/{attachment_id}")
        return response

    async def test_get_nonexistent_returns_404(self):
        response = await self._get_attachment(str(uuid4()), select_row=None)
        assert response.status_code == 404
        body = response.json()
        assert "not found" in body["detail"].lower()

    async def test_get_existing_attachment_returns_200(self):
        att_id = uuid4()
        row = _make_fake_row(
            attachment_id=att_id,
            original_filename="found.csv",
            content_type="text/csv",
            size_bytes=123,
        )
        response = await self._get_attachment(str(att_id), select_row=row)
        assert response.status_code == 200
        body = response.json()
        assert body["attachment_id"] == str(att_id)
        assert body["original_filename"] == "found.csv"
        assert body["size_bytes"] == 123

    async def test_get_invalid_uuid_returns_422(self):
        response = await self._get_attachment("not-a-uuid")
        assert response.status_code == 422
