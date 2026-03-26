"""citation_verifications and template_craft_cycle_counts table definitions."""

import sqlalchemy as sa

from nexus_core.models import metadata

citation_verifications = sa.Table(
    "citation_verifications",
    metadata,
    sa.Column("verification_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("cache_key", sa.VARCHAR(64), nullable=False, unique=True),
    sa.Column("source_identifier", sa.Text, nullable=False),
    sa.Column("identifier_type", sa.VARCHAR(10), nullable=False),
    sa.Column("verified", sa.Boolean, nullable=False),
    sa.Column("http_status_code", sa.Integer, nullable=True),
    sa.Column("resolved_url", sa.Text, nullable=True),
    sa.Column("resolver_used", sa.VARCHAR(30), nullable=True),
    sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
)

template_craft_cycle_counts = sa.Table(
    "template_craft_cycle_counts",
    metadata,
    sa.Column("template_id", sa.Uuid, sa.ForeignKey("market_templates.template_id"), nullable=False),
    sa.Column("cycle_tick", sa.Integer, nullable=False),
    sa.Column("craft_count", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.PrimaryKeyConstraint("template_id", "cycle_tick"),
)
