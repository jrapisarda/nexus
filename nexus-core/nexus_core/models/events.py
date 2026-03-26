"""events outbox table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

events = sa.Table(
    "events",
    metadata,
    sa.Column("event_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("event_type", sa.VARCHAR(100), nullable=False),
    sa.Column("entity_id", sa.Uuid, nullable=True),
    sa.Column("entity_type", sa.VARCHAR(50), nullable=True),
    sa.Column("payload", sa.JSON, server_default=sa.text("'{}'::jsonb")),
    sa.Column("processed", sa.Boolean, server_default=sa.text("false")),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
)
