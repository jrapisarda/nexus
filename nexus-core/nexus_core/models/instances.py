"""agent_instances table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

agent_instances = sa.Table(
    "agent_instances",
    metadata,
    sa.Column("instance_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
    sa.Column("objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=False),
    sa.Column("session_state", sa.JSON, server_default=sa.text("'{}'::jsonb")),
    sa.Column("spawned_by", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=True),
    sa.Column("spawn_reason", sa.Text, nullable=True),
    sa.Column("input_prompt", sa.Text, nullable=False),
    sa.Column("output_content", sa.Text, nullable=True),
    sa.Column("thinking_content", sa.Text, nullable=True),
    sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_heartbeat", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("status", sa.VARCHAR(20), server_default="pending"),
    sa.Column("retry_count", sa.Integer, server_default=sa.text("0")),
    sa.Column("tokens_input", sa.Integer, server_default=sa.text("0")),
    sa.Column("tokens_thinking", sa.Integer, server_default=sa.text("0")),
    sa.Column("tokens_output", sa.Integer, server_default=sa.text("0")),
    sa.Column("cost_usd", sa.Numeric(8, 6), server_default=sa.text("0")),
    sa.Column("latency_ms", sa.Integer, nullable=True),
    sa.Column("error_message", sa.Text, nullable=True),
)
