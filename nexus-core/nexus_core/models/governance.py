"""governance_proposals and governance_votes table definitions."""

import sqlalchemy as sa

from nexus_core.models import metadata

governance_proposals = sa.Table(
    "governance_proposals",
    metadata,
    sa.Column("proposal_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("proposed_by_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
    sa.Column("proposal_type", sa.VARCHAR(50), nullable=False),
    sa.Column("title", sa.VARCHAR(500), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("rationale", sa.Text, nullable=False),
    sa.Column("target_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
    sa.Column("status", sa.VARCHAR(20), server_default="proposed"),
    sa.Column("voting_deadline", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
)

governance_votes = sa.Table(
    "governance_votes",
    metadata,
    sa.Column("vote_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("proposal_id", sa.Uuid, sa.ForeignKey("governance_proposals.proposal_id"), nullable=False),
    sa.Column("voter_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
    sa.Column("vote", sa.VARCHAR(10), nullable=False),
    sa.Column("reasoning", sa.Text, nullable=False),
    sa.Column("voter_reputation_weight", sa.Numeric(5, 3), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)
