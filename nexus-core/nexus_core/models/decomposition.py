"""objective_decomposition table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

objective_decomposition = sa.Table(
    "objective_decomposition",
    metadata,
    sa.Column("decomposition_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("parent_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=False),
    sa.Column("child_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=False),
    sa.Column("decomposition_rationale", sa.Text, nullable=False),
    sa.Column("dependency_type", sa.VARCHAR(20), nullable=False),
    sa.Column("depends_on", sa.JSON, server_default=sa.text("'[]'::jsonb")),
    sa.Column("execution_order", sa.Integer, server_default=sa.text("0")),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)
