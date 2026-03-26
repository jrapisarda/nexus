"""messages table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

messages = sa.Table(
    "messages",
    metadata,
    sa.Column("message_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("from_instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=True),
    sa.Column("to_instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=True),
    sa.Column("to_role_class", sa.VARCHAR(50), nullable=True),
    sa.Column("message_type", sa.VARCHAR(50), nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("priority", sa.Integer, server_default=sa.text("5")),
    sa.Column("status", sa.VARCHAR(20), server_default="pending"),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)
