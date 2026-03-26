"""economy_ledger table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

economy_ledger = sa.Table(
    "economy_ledger",
    metadata,
    sa.Column("transaction_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("from_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
    sa.Column("to_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
    sa.Column("amount", sa.Numeric(12, 2), nullable=False),
    sa.Column("transaction_type", sa.VARCHAR(50), nullable=False),
    sa.Column("reference_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
    sa.Column("reference_finding_id", sa.Uuid, sa.ForeignKey("findings.finding_id"), nullable=True),
    sa.Column("memo", sa.Text, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)
