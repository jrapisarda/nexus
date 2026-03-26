"""agent_telemetry table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

agent_telemetry = sa.Table(
    "agent_telemetry",
    metadata,
    sa.Column("telemetry_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=False),
    sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
    sa.Column("objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=False),
    sa.Column("api_call_timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("prompt_hash", sa.VARCHAR(64), nullable=False),
    sa.Column("tokens_input", sa.Integer, nullable=False),
    sa.Column("tokens_thinking", sa.Integer, nullable=False),
    sa.Column("tokens_output", sa.Integer, nullable=False),
    sa.Column("cost_input_usd", sa.Numeric(8, 6), nullable=False),
    sa.Column("cost_thinking_usd", sa.Numeric(8, 6), nullable=False),
    sa.Column("cost_output_usd", sa.Numeric(8, 6), nullable=False),
    sa.Column("cost_total_usd", sa.Numeric(8, 6), nullable=False),
    sa.Column("latency_ms", sa.Integer, nullable=False),
    sa.Column("http_status", sa.Integer, nullable=False),
    sa.Column("success", sa.Boolean, nullable=False),
    sa.Column("error_category", sa.VARCHAR(50), nullable=True),
    sa.Column("model_id", sa.VARCHAR(100), nullable=False),
)
