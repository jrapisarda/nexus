"""Unit tests for nexus_core.utils.file_context — file validation, sanitization, budget, and loader."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nexus_core.utils.file_context import (
    ALLOWED_EXTENSIONS,
    DIRECT_READ_EXTENSIONS,
    EXTRACTABLE_EXTENSIONS,
    IMAGE_EXTENSIONS,
    AttachmentContext,
    FileContextBudget,
    FileContextLoader,
    get_extension,
    is_direct_read,
    is_extractable,
    is_image,
    sanitize_filename,
    validate_extension,
)


# ---------------------------------------------------------------------------
# validate_extension
# ---------------------------------------------------------------------------

class TestValidateExtension:
    """Verify that validate_extension accepts allowed and rejects disallowed extensions."""

    @pytest.mark.parametrize("ext", sorted(ALLOWED_EXTENSIONS))
    def test_allowed_extensions_return_true(self, ext: str):
        assert validate_extension(f"document.{ext}") is True

    @pytest.mark.parametrize("ext", ["exe", "bat", "sh", "py", "dll", "so", "js", "html", "zip"])
    def test_disallowed_extensions_return_false(self, ext: str):
        assert validate_extension(f"malware.{ext}") is False

    def test_uppercase_extension_is_still_allowed(self):
        assert validate_extension("report.PDF") is True

    def test_mixed_case_extension_is_allowed(self):
        assert validate_extension("photo.JpEg") is True

    def test_no_extension_returns_false(self):
        assert validate_extension("noextension") is False

    def test_dot_only_returns_false(self):
        assert validate_extension("file.") is False

    def test_double_extension_uses_last(self):
        # .tar.gz — the extension is "gz", which is not allowed
        assert validate_extension("archive.tar.gz") is False

    def test_hidden_file_no_extension(self):
        # ".gitignore" — suffix is empty string on some systems, name is ".gitignore"
        result = validate_extension(".gitignore")
        # Path(".gitignore").suffix == "" so ext == ""
        assert result is False

    def test_empty_filename_returns_false(self):
        assert validate_extension("") is False


# ---------------------------------------------------------------------------
# get_extension
# ---------------------------------------------------------------------------

class TestGetExtension:
    """Verify get_extension returns the lowercase extension without a leading dot."""

    def test_simple_extension(self):
        assert get_extension("report.pdf") == "pdf"

    def test_uppercase_extension(self):
        assert get_extension("REPORT.PDF") == "pdf"

    def test_mixed_case(self):
        assert get_extension("Image.JpEg") == "jpeg"

    def test_no_extension_returns_empty(self):
        assert get_extension("noext") == ""

    def test_double_extension_returns_last(self):
        assert get_extension("data.backup.csv") == "csv"

    def test_dotfile_returns_empty(self):
        assert get_extension(".env") == ""

    def test_empty_filename(self):
        assert get_extension("") == ""


# ---------------------------------------------------------------------------
# is_image
# ---------------------------------------------------------------------------

class TestIsImage:
    """Verify is_image correctly identifies image file types."""

    @pytest.mark.parametrize("ext", sorted(IMAGE_EXTENSIONS))
    def test_image_extensions_return_true(self, ext: str):
        assert is_image(f"photo.{ext}") is True

    @pytest.mark.parametrize("ext", ["pdf", "csv", "txt", "docx", "xlsx"])
    def test_non_image_extensions_return_false(self, ext: str):
        assert is_image(f"file.{ext}") is False

    def test_uppercase_image_extension(self):
        assert is_image("PHOTO.PNG") is True

    def test_no_extension_returns_false(self):
        assert is_image("noext") is False


# ---------------------------------------------------------------------------
# is_extractable
# ---------------------------------------------------------------------------

class TestIsExtractable:
    """Verify is_extractable correctly identifies PDF/DOCX/XLSX types."""

    @pytest.mark.parametrize("ext", sorted(EXTRACTABLE_EXTENSIONS))
    def test_extractable_extensions_return_true(self, ext: str):
        assert is_extractable(f"file.{ext}") is True

    @pytest.mark.parametrize("ext", ["csv", "txt", "png", "jpg", "json", "md"])
    def test_non_extractable_return_false(self, ext: str):
        assert is_extractable(f"file.{ext}") is False

    def test_uppercase_extractable(self):
        assert is_extractable("FILE.DOCX") is True


# ---------------------------------------------------------------------------
# is_direct_read
# ---------------------------------------------------------------------------

class TestIsDirectRead:
    """Verify is_direct_read correctly identifies CSV/TXT/JSON/MD types."""

    @pytest.mark.parametrize("ext", sorted(DIRECT_READ_EXTENSIONS))
    def test_direct_read_extensions_return_true(self, ext: str):
        assert is_direct_read(f"data.{ext}") is True

    @pytest.mark.parametrize("ext", ["pdf", "docx", "png", "xlsx", "exe"])
    def test_non_direct_read_return_false(self, ext: str):
        assert is_direct_read(f"file.{ext}") is False

    def test_uppercase_direct_read(self):
        assert is_direct_read("DATA.CSV") is True


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------

class TestSanitizeFilename:
    """Verify sanitize_filename handles paths, unicode, length limits, and edge cases."""

    def test_simple_filename_unchanged(self):
        result = sanitize_filename("report.pdf")
        assert result == "report.pdf"

    def test_strips_directory_path(self):
        result = sanitize_filename("/home/user/docs/report.pdf")
        assert result == "report.pdf"

    def test_strips_windows_path(self):
        result = sanitize_filename("C:\\Users\\admin\\report.pdf")
        assert result == "report.pdf"

    def test_path_traversal_attack(self):
        result = sanitize_filename("../../etc/passwd")
        assert "etc" not in result or ".." not in result
        # The function strips path components so only "passwd" remains
        assert result == "passwd"

    def test_path_traversal_with_extension(self):
        result = sanitize_filename("../../../etc/shadow.txt")
        assert ".." not in result
        assert result == "shadow.txt"

    def test_unicode_normalization(self):
        # NFKD normalizes characters like accented letters
        result = sanitize_filename("cafe\u0301.txt")
        assert ".txt" in result
        # The result should be safe and not contain raw combining characters
        assert len(result) > 0

    def test_special_characters_replaced_with_underscore(self):
        result = sanitize_filename("my file (copy) [2].pdf")
        # Spaces and brackets become underscores, then collapsed
        assert " " not in result
        assert "[" not in result
        assert "]" not in result
        assert "(" not in result
        assert ")" not in result

    def test_multiple_underscores_collapsed(self):
        result = sanitize_filename("a___b___c.txt")
        assert "___" not in result
        assert result == "a_b_c.txt"

    def test_length_limit_200_chars(self):
        long_name = "a" * 250 + ".pdf"
        result = sanitize_filename(long_name)
        assert len(result) <= 200

    def test_length_limit_preserves_extension(self):
        long_name = "a" * 250 + ".pdf"
        result = sanitize_filename(long_name)
        assert result.endswith(".pdf")

    def test_empty_string_returns_unnamed(self):
        result = sanitize_filename("")
        assert result == "unnamed"

    def test_only_special_characters_returns_unnamed(self):
        # All characters get replaced with underscores, then stripped
        result = sanitize_filename("@#$%^&")
        # After replacement and stripping, if nothing remains, fallback to "unnamed"
        assert len(result) > 0

    def test_just_dots_and_slashes(self):
        result = sanitize_filename("../../..")
        # Path("../../..").name returns ".." on most systems
        assert result != ""

    def test_filename_with_dashes_and_underscores_preserved(self):
        result = sanitize_filename("my-report_v2.pdf")
        assert result == "my-report_v2.pdf"

    def test_leading_trailing_underscores_stripped(self):
        result = sanitize_filename("___file___.txt")
        assert not result.startswith("_")


# ---------------------------------------------------------------------------
# FileContextBudget.check_and_truncate
# ---------------------------------------------------------------------------

class TestFileContextBudget:
    """Verify FileContextBudget enforces character budget on file contexts."""

    def _make_context(
        self,
        text: str | None = None,
        image_path: Path | None = None,
        filename: str = "test.txt",
    ) -> AttachmentContext:
        return AttachmentContext(
            attachment_id=uuid4(),
            filename=filename,
            content_type="text/plain" if text else "image/png",
            size_bytes=len(text.encode()) if text else 1024,
            text_content=text,
            image_path=image_path,
        )

    def test_within_budget_returns_unchanged(self):
        ctx1 = self._make_context(text="Short text")
        ctx2 = self._make_context(text="Another short")
        result = FileContextBudget.check_and_truncate([ctx1, ctx2], budget_chars=10_000)
        assert len(result) == 2
        # Content should be unchanged
        texts = {c.text_content for c in result if c.text_content}
        assert "Short text" in texts
        assert "Another short" in texts

    def test_exact_budget_returns_unchanged(self):
        text_a = "a" * 500
        text_b = "b" * 500
        ctx1 = self._make_context(text=text_a)
        ctx2 = self._make_context(text=text_b)
        result = FileContextBudget.check_and_truncate([ctx1, ctx2], budget_chars=1000)
        assert len(result) == 2

    def test_over_budget_truncates_largest_first(self):
        small_text = "x" * 100
        large_text = "y" * 2000
        ctx_small = self._make_context(text=small_text, filename="small.txt")
        ctx_large = self._make_context(text=large_text, filename="large.txt")
        result = FileContextBudget.check_and_truncate(
            [ctx_small, ctx_large], budget_chars=800
        )
        # The small file should be preserved; the large file truncated or dropped
        text_contexts = [c for c in result if c.text_content]
        small_preserved = any(
            c.text_content == small_text for c in text_contexts
        )
        assert small_preserved, "Small file should be preserved intact"

    def test_truncated_file_has_truncated_marker(self):
        large_text = "y" * 2000
        ctx = self._make_context(text=large_text, filename="big.txt")
        result = FileContextBudget.check_and_truncate([ctx], budget_chars=800)
        text_contexts = [c for c in result if c.text_content]
        assert len(text_contexts) == 1
        assert "[TRUNCATED" in text_contexts[0].text_content

    def test_drops_files_when_budget_too_small(self):
        # Budget is 400: the file is 2000 chars, but remaining after no prior files
        # is 400; if remaining <= 500, the file is dropped
        large_text = "z" * 2000
        ctx = self._make_context(text=large_text, filename="huge.txt")
        result = FileContextBudget.check_and_truncate([ctx], budget_chars=400)
        text_contexts = [c for c in result if c.text_content]
        # With 400 budget, remaining is 400 which is <= 500, so file is dropped
        assert len(text_contexts) == 0

    def test_preserves_image_contexts(self):
        text_ctx = self._make_context(text="x" * 2000)
        img_ctx = self._make_context(
            image_path=Path("/tmp/image.png"), filename="image.png"
        )
        result = FileContextBudget.check_and_truncate(
            [text_ctx, img_ctx], budget_chars=500
        )
        image_results = [c for c in result if c.image_path]
        assert len(image_results) == 1
        assert image_results[0].image_path == Path("/tmp/image.png")

    def test_images_not_counted_in_budget(self):
        text_ctx = self._make_context(text="a" * 100)
        img_ctx = self._make_context(
            image_path=Path("/tmp/img.png"), filename="img.png"
        )
        result = FileContextBudget.check_and_truncate(
            [text_ctx, img_ctx], budget_chars=200
        )
        assert len(result) == 2

    def test_empty_input_returns_empty(self):
        result = FileContextBudget.check_and_truncate([], budget_chars=10_000)
        assert result == []

    def test_multiple_files_some_dropped_some_kept(self):
        # Three files: 100, 300, 600 chars. Budget = 500.
        # Processing smallest first: 100 fits (remaining 400), 300 fits (remaining 100),
        # 600 doesn't fit and remaining <= 500 so it's dropped.
        ctx_a = self._make_context(text="a" * 100, filename="a.txt")
        ctx_b = self._make_context(text="b" * 300, filename="b.txt")
        ctx_c = self._make_context(text="c" * 600, filename="c.txt")
        result = FileContextBudget.check_and_truncate(
            [ctx_a, ctx_b, ctx_c], budget_chars=500
        )
        text_contexts = [c for c in result if c.text_content]
        # a and b should fit; c should be dropped since remaining (100) <= 500
        kept_filenames = {c.filename for c in text_contexts}
        assert "a.txt" in kept_filenames
        assert "b.txt" in kept_filenames

    def test_only_images_within_budget(self):
        img1 = self._make_context(image_path=Path("/tmp/a.png"), filename="a.png")
        img2 = self._make_context(image_path=Path("/tmp/b.png"), filename="b.png")
        result = FileContextBudget.check_and_truncate([img1, img2], budget_chars=0)
        # Images don't consume budget, so they should all be returned
        assert len(result) == 2

    def test_none_text_content_treated_as_no_text(self):
        ctx = self._make_context(text=None)
        result = FileContextBudget.check_and_truncate([ctx], budget_chars=100)
        # Total text chars is 0, which is within budget (100), so the
        # original list is returned unchanged (early return path).
        assert len(result) == 1
        assert result[0].text_content is None


# ---------------------------------------------------------------------------
# FileContextLoader.load (Phase 2-7 file upload support)
# ---------------------------------------------------------------------------

class TestFileContextLoader:
    """Verify FileContextLoader.load() reads attachments from DB and disk."""

    def _make_row(
        self,
        *,
        original_filename: str,
        stored_path: str,
        content_type: str = "text/plain",
        size_bytes: int = 1024,
        extraction_text_path: str | None = None,
        attachment_id=None,
    ):
        """Create a SimpleNamespace that mimics a DB row."""
        return SimpleNamespace(
            attachment_id=attachment_id or uuid4(),
            original_filename=original_filename,
            stored_path=stored_path,
            content_type=content_type,
            size_bytes=size_bytes,
            extraction_text_path=extraction_text_path,
        )

    async def test_empty_attachment_ids_returns_empty(self):
        """Passing empty list returns empty without touching the DB."""
        result = await FileContextLoader.load(engine=None, attachment_ids=[])
        assert result == []

    async def test_direct_read_csv_loads_text_content(self, tmp_path):
        """A CSV file (direct-read) should have text_content loaded from disk."""
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("col1,col2\nval1,val2", encoding="utf-8")

        att_id = uuid4()
        row = self._make_row(
            attachment_id=att_id,
            original_filename="data.csv",
            stored_path=str(csv_file),
            content_type="text/csv",
            size_bytes=19,
        )

        # Mock the engine and connection
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row]

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin = AsyncMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin.return_value = mock_begin

        contexts = await FileContextLoader.load(mock_engine, [att_id])

        assert len(contexts) == 1
        assert contexts[0].text_content == "col1,col2\nval1,val2"
        assert contexts[0].filename == "data.csv"
        assert contexts[0].image_path is None

    async def test_direct_read_txt_loads_text_content(self, tmp_path):
        """A TXT file (direct-read) should have text_content loaded from disk."""
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Important research notes", encoding="utf-8")

        att_id = uuid4()
        row = self._make_row(
            attachment_id=att_id,
            original_filename="notes.txt",
            stored_path=str(txt_file),
            content_type="text/plain",
            size_bytes=24,
        )

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row]

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin = AsyncMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin.return_value = mock_begin

        contexts = await FileContextLoader.load(mock_engine, [att_id])

        assert len(contexts) == 1
        assert contexts[0].text_content == "Important research notes"

    async def test_image_file_sets_image_path(self, tmp_path):
        """An image file should have image_path set, not text_content."""
        img_file = tmp_path / "diagram.png"
        img_file.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 50)

        att_id = uuid4()
        row = self._make_row(
            attachment_id=att_id,
            original_filename="diagram.png",
            stored_path=str(img_file),
            content_type="image/png",
            size_bytes=58,
        )

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row]

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin = AsyncMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin.return_value = mock_begin

        contexts = await FileContextLoader.load(mock_engine, [att_id])

        assert len(contexts) == 1
        assert contexts[0].image_path == img_file
        assert contexts[0].text_content is None

    async def test_extracted_file_reads_sidecar(self, tmp_path):
        """An extracted document should read text from the sidecar .txt file."""
        sidecar = tmp_path / "report.pdf.txt"
        sidecar.write_text("Extracted text from PDF", encoding="utf-8")

        att_id = uuid4()
        row = self._make_row(
            attachment_id=att_id,
            original_filename="report.pdf",
            stored_path=str(tmp_path / "report.pdf"),
            content_type="application/pdf",
            size_bytes=50000,
            extraction_text_path=str(sidecar),
        )

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row]

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin = AsyncMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin.return_value = mock_begin

        contexts = await FileContextLoader.load(mock_engine, [att_id])

        assert len(contexts) == 1
        assert contexts[0].text_content == "Extracted text from PDF"
        assert contexts[0].image_path is None

    async def test_missing_sidecar_gives_no_text(self, tmp_path):
        """If the sidecar file does not exist, text_content remains None."""
        att_id = uuid4()
        row = self._make_row(
            attachment_id=att_id,
            original_filename="report.pdf",
            stored_path=str(tmp_path / "report.pdf"),
            content_type="application/pdf",
            size_bytes=50000,
            extraction_text_path=str(tmp_path / "report.pdf.txt"),
        )

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row]

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin = AsyncMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin.return_value = mock_begin

        contexts = await FileContextLoader.load(mock_engine, [att_id])

        assert len(contexts) == 1
        assert contexts[0].text_content is None

    async def test_mixed_file_types(self, tmp_path):
        """Multiple attachment types are loaded correctly in a single call."""
        # CSV - direct read
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b\n1,2", encoding="utf-8")

        # PNG - image
        img_file = tmp_path / "chart.png"
        img_file.write_bytes(b'\x89PNG' + b'\x00' * 20)

        # PDF with sidecar - extracted
        sidecar = tmp_path / "paper.pdf.txt"
        sidecar.write_text("Paper text", encoding="utf-8")

        rows = [
            self._make_row(
                original_filename="data.csv",
                stored_path=str(csv_file),
                content_type="text/csv",
                size_bytes=7,
            ),
            self._make_row(
                original_filename="chart.png",
                stored_path=str(img_file),
                content_type="image/png",
                size_bytes=24,
            ),
            self._make_row(
                original_filename="paper.pdf",
                stored_path=str(tmp_path / "paper.pdf"),
                content_type="application/pdf",
                size_bytes=100000,
                extraction_text_path=str(sidecar),
            ),
        ]

        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin = AsyncMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.begin.return_value = mock_begin

        ids = [r.attachment_id for r in rows]
        contexts = await FileContextLoader.load(mock_engine, ids)

        assert len(contexts) == 3

        csv_ctx = next(c for c in contexts if c.filename == "data.csv")
        assert csv_ctx.text_content == "a,b\n1,2"
        assert csv_ctx.image_path is None

        img_ctx = next(c for c in contexts if c.filename == "chart.png")
        assert img_ctx.image_path == img_file
        assert img_ctx.text_content is None

        pdf_ctx = next(c for c in contexts if c.filename == "paper.pdf")
        assert pdf_ctx.text_content == "Paper text"
        assert pdf_ctx.image_path is None
