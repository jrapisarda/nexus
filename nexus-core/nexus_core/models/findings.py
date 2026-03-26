"""findings table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

findings = sa.Table(
    "findings",
    metadata,
    sa.Column("finding_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=False),
    sa.Column("instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=False),
    sa.Column("finding_type", sa.VARCHAR(50), nullable=False),
    sa.Column("title", sa.VARCHAR(500), nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("structured_data", sa.JSON, nullable=True),
    sa.Column("status", sa.VARCHAR(20), server_default="pending_review"),
    sa.Column("review_round", sa.Integer, server_default=sa.text("0")),
    sa.Column("impact_level", sa.VARCHAR(20), server_default="routine"),
    sa.Column("kg_nodes_created", sa.JSON, server_default=sa.text("'[]'::jsonb")),
    sa.Column("kg_edges_created", sa.JSON, server_default=sa.text("'[]'::jsonb")),
    sa.Column("is_infiltration", sa.Boolean, server_default=sa.text("false")),
    sa.Column("citation_confidence_score", sa.Numeric(4, 3), nullable=True),
    sa.Column("citation_check_started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)
