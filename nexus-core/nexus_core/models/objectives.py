"""objectives table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

objectives = sa.Table(
    "objectives",
    metadata,
    sa.Column("objective_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("parent_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
    sa.Column("title", sa.VARCHAR(500), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("objective_type", sa.VARCHAR(20), nullable=False),
    sa.Column("impact_level", sa.VARCHAR(20), server_default="routine"),
    sa.Column("priority", sa.Integer, server_default=sa.text("5")),
    sa.Column("status", sa.VARCHAR(20), server_default="proposed"),
    sa.Column("proposed_by_type", sa.VARCHAR(10), nullable=False),
    sa.Column("proposed_by_id", sa.Uuid, nullable=True),
    sa.Column("approved_by_type", sa.VARCHAR(10), nullable=True),
    sa.Column("approved_by_id", sa.Uuid, nullable=True),
    sa.Column("assigned_to", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
    sa.Column("acceptance_criteria", sa.Text, nullable=True),
    sa.Column("knowledge_graph_anchor", sa.JSON, server_default=sa.text("'[]'::jsonb")),
    sa.Column("compute_budget_allocated", sa.Numeric(10, 2), server_default=sa.text("0")),
    sa.Column("output_type", sa.VARCHAR(50), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("escalation_reason", sa.Text, nullable=True),
    sa.Column("file_attachment_ids", sa.JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.CheckConstraint("priority >= 1 AND priority <= 10", name="ck_priority_range"),
)
