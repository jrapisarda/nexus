"""tool_registry table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

tool_registry = sa.Table(
    "tool_registry",
    metadata,
    sa.Column("tool_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("tool_name", sa.VARCHAR(255), nullable=False, unique=True),
    sa.Column("tool_type", sa.VARCHAR(20), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("input_schema", sa.JSON, nullable=False),
    sa.Column("output_schema", sa.JSON, nullable=False),
    sa.Column("implementation", sa.Text, nullable=True),
    sa.Column("created_by_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
    sa.Column("created_by_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
    sa.Column("usage_count", sa.Integer, server_default=sa.text("0")),
    sa.Column("success_rate", sa.Numeric(4, 3), server_default=sa.text("1.000")),
    sa.Column("status", sa.VARCHAR(20), server_default="active"),
    sa.Column("required_permissions", sa.JSON, server_default=sa.text("'[]'::jsonb")),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)
