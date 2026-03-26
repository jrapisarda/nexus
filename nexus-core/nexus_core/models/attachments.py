"""objective_attachments table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

objective_attachments = sa.Table(
    "objective_attachments",
    metadata,
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
