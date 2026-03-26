"""Unit tests for nexus_core.models.attachments — table registration and column definitions."""

from __future__ import annotations

import sqlalchemy as sa

from nexus_core.models import metadata
from nexus_core.models.attachments import objective_attachments


class TestObjectiveAttachmentsTable:
    """Verify the objective_attachments table is correctly registered with expected columns."""

    def test_table_registered_in_metadata(self):
        assert "objective_attachments" in metadata.tables

    def test_table_object_matches_metadata(self):
        assert metadata.tables["objective_attachments"] is objective_attachments

    def test_table_name(self):
        assert objective_attachments.name == "objective_attachments"


class TestObjectiveAttachmentsColumns:
    """Verify the table has all expected columns with correct types."""

    EXPECTED_COLUMNS = [
        "attachment_id",
        "objective_id",
        "original_filename",
        "stored_path",
        "content_type",
        "size_bytes",
        "extraction_text_path",
        "moonshot_file_id",
        "upload_status",
        "created_at",
    ]

    def test_all_expected_columns_present(self):
        column_names = [c.name for c in objective_attachments.columns]
        for expected in self.EXPECTED_COLUMNS:
            assert expected in column_names, f"Missing column: {expected}"

    def test_no_extra_columns(self):
        column_names = set(c.name for c in objective_attachments.columns)
        expected_set = set(self.EXPECTED_COLUMNS)
        extra = column_names - expected_set
        assert extra == set(), f"Unexpected extra columns: {extra}"

    def test_attachment_id_is_primary_key(self):
        col = objective_attachments.c.attachment_id
        assert col.primary_key is True

    def test_attachment_id_type_is_uuid(self):
        col = objective_attachments.c.attachment_id
        assert isinstance(col.type, sa.Uuid)

    def test_objective_id_is_nullable(self):
        col = objective_attachments.c.objective_id
        assert col.nullable is True

    def test_objective_id_has_foreign_key(self):
        col = objective_attachments.c.objective_id
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "objectives.objective_id" in fk_targets

    def test_original_filename_not_nullable(self):
        col = objective_attachments.c.original_filename
        assert col.nullable is False

    def test_stored_path_not_nullable(self):
        col = objective_attachments.c.stored_path
        assert col.nullable is False

    def test_content_type_not_nullable(self):
        col = objective_attachments.c.content_type
        assert col.nullable is False

    def test_size_bytes_not_nullable(self):
        col = objective_attachments.c.size_bytes
        assert col.nullable is False

    def test_size_bytes_type_is_biginteger(self):
        col = objective_attachments.c.size_bytes
        assert isinstance(col.type, sa.BigInteger)

    def test_extraction_text_path_is_nullable(self):
        col = objective_attachments.c.extraction_text_path
        assert col.nullable is True

    def test_moonshot_file_id_is_nullable(self):
        col = objective_attachments.c.moonshot_file_id
        assert col.nullable is True

    def test_upload_status_not_nullable(self):
        col = objective_attachments.c.upload_status
        assert col.nullable is False

    def test_upload_status_has_server_default(self):
        col = objective_attachments.c.upload_status
        assert col.server_default is not None
        assert "uploaded" in str(col.server_default.arg)

    def test_created_at_has_server_default(self):
        col = objective_attachments.c.created_at
        assert col.server_default is not None
