"""institutional_memory table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

institutional_memory = sa.Table(
    "institutional_memory",
    metadata,
    sa.Column("memory_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("memory_type", sa.VARCHAR(50), nullable=False),
    sa.Column("title", sa.VARCHAR(500), nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("source_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
    sa.Column("source_instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=True),
    sa.Column("relevance_tags", sa.JSON, server_default=sa.text("'[]'::jsonb")),
    sa.Column("retrieval_count", sa.Integer, server_default=sa.text("0")),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)
