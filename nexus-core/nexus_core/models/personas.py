"""agent_personas table definition."""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from nexus_core.models import metadata

agent_personas = sa.Table(
    "agent_personas",
    metadata,
    sa.Column("persona_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("persona_name", sa.VARCHAR(255), nullable=False, unique=True),
    sa.Column(
        "role_class",
        sa.VARCHAR(50),
        nullable=False,
    ),
    sa.Column("system_prompt_template", sa.Text, nullable=False),
    sa.Column("tool_permissions", sa.JSON, server_default=sa.text("'[]'::jsonb")),
    sa.Column("reasoning_strategy", sa.VARCHAR(50), server_default="chain-of-thought"),
    sa.Column("model_config_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
    sa.Column("autonomy_level", sa.Integer, server_default=sa.text("3")),
    sa.Column("parent_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
    sa.Column("sponsor_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
    sa.Column("generation", sa.Integer, server_default=sa.text("0")),
    sa.Column("reputation_score", sa.Numeric(5, 3), server_default=sa.text("0.500")),
    sa.Column("compute_budget", sa.Numeric(10, 2), server_default=sa.text("50.00")),
    sa.Column("status", sa.VARCHAR(20), server_default="active"),
    sa.Column("probation_until", sa.DateTime(timezone=True), nullable=True),
    sa.Column("specialization_vector", Vector(384), nullable=True),
    sa.Column("mutation_diff", sa.JSON, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("deprecation_reason", sa.Text, nullable=True),
    sa.CheckConstraint("autonomy_level >= 1 AND autonomy_level <= 5", name="ck_autonomy_level_range"),
)
