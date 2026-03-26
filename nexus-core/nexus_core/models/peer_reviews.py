"""peer_reviews table definition."""

import sqlalchemy as sa

from nexus_core.models import metadata

peer_reviews = sa.Table(
    "peer_reviews",
    metadata,
    sa.Column("review_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("finding_id", sa.Uuid, sa.ForeignKey("findings.finding_id"), nullable=False),
    sa.Column("reviewer_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
    sa.Column("reviewer_instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=False),
    sa.Column("methodology_critique", sa.Text, nullable=False),
    sa.Column("evidence_evaluation", sa.Text, nullable=False),
    sa.Column("novelty_assessment", sa.Text, nullable=False),
    sa.Column("confidence_rating", sa.Numeric(4, 3), nullable=False),
    sa.Column("verdict", sa.VARCHAR(20), nullable=False),
    sa.Column("revision_feedback", sa.Text, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)
