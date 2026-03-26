"""Add objective_attachments table and file_attachment_ids column to objectives.

Revision ID: 007
Revises: 006
Create Date: 2026-03-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # -- New table: objective_attachments ---------------------------------
    if not _has_table(inspector, "objective_attachments"):
        op.create_table(
            "objective_attachments",
            sa.Column(
                "attachment_id",
                sa.Uuid,
                primary_key=True,
                server_default=sa.text("uuid_generate_v4()"),
            ),
            sa.Column(
                "objective_id",
                sa.Uuid,
                sa.ForeignKey("objectives.objective_id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("original_filename", sa.VARCHAR(255), nullable=False),
            sa.Column("stored_path", sa.Text, nullable=False),
            sa.Column("content_type", sa.VARCHAR(100), nullable=False),
            sa.Column("size_bytes", sa.BigInteger, nullable=False),
            sa.Column("extraction_text_path", sa.Text, nullable=True),
            sa.Column("moonshot_file_id", sa.VARCHAR(255), nullable=True),
            sa.Column(
                "upload_status",
                sa.VARCHAR(20),
                nullable=False,
                server_default="uploaded",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )

    # -- Indexes -----------------------------------------------------------
    _create_index_if_not_exists(
        "ix_objective_attachments_objective_id",
        "objective_attachments",
        "objective_id",
    )
    # Partial index for orphan cleanup (attachments not yet linked to an objective)
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_objective_attachments_orphans "
            "ON objective_attachments (created_at) "
            "WHERE objective_id IS NULL"
        )
    )

    # -- New column on objectives: file_attachment_ids ---------------------
    _add_column_if_missing(
        "objectives",
        sa.Column(
            "file_attachment_ids",
            sa.JSON,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    for index_name in [
        "ix_objective_attachments_orphans",
        "ix_objective_attachments_objective_id",
    ]:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {index_name}"))

    if _has_table(sa.inspect(op.get_bind()), "objective_attachments"):
        op.drop_table("objective_attachments")

    if _has_column("objectives", "file_attachment_ids"):
        op.drop_column("objectives", "file_attachment_ids")


# -- Helpers (same pattern as prior migrations) ----------------------------


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_if_not_exists(
    index_name: str, table_name: str, columns_sql: str
) -> None:
    op.execute(
        sa.text(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {table_name} ({columns_sql})"
        )
    )
