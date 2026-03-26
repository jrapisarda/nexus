"""Add salary, welfare, expanded crafting, and citation verification infrastructure.

- New columns on findings: citation_confidence_score, citation_check_started_at
- New columns on market_templates: allowed_crafter_roles, max_crafts_per_cycle
- New table: citation_verifications (DOI/URL verification cache)
- New table: template_craft_cycle_counts (crafting supply cap tracking)
- New partial index on economy_ledger for salary idempotency guard
- Seed: NEXUS_WELFARE_SYSTEM persona, backfill market_templates, new templates

Revision ID: 008
Revises: 007
Create Date: 2026-03-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(inspector, table: str, index_name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(i["name"] == index_name for i in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # -- findings: citation columns ----------------------------------------
    if not _has_column(inspector, "findings", "citation_confidence_score"):
        op.add_column(
            "findings",
            sa.Column("citation_confidence_score", sa.Numeric(4, 3), nullable=True),
        )

    if not _has_column(inspector, "findings", "citation_check_started_at"):
        op.add_column(
            "findings",
            sa.Column("citation_check_started_at", sa.DateTime(timezone=True), nullable=True),
        )

    # -- market_templates: crafting permissions -----------------------------
    if not _has_column(inspector, "market_templates", "allowed_crafter_roles"):
        op.add_column(
            "market_templates",
            sa.Column(
                "allowed_crafter_roles",
                sa.JSON,
                nullable=False,
                server_default=sa.text(
                    """'["consolidator","synthesizer","tool_forger","architect"]'::jsonb"""
                ),
            ),
        )

    if not _has_column(inspector, "market_templates", "max_crafts_per_cycle"):
        op.add_column(
            "market_templates",
            sa.Column("max_crafts_per_cycle", sa.Integer, nullable=True),
        )

    # -- citation_verifications table --------------------------------------
    if not _has_table(inspector, "citation_verifications"):
        op.create_table(
            "citation_verifications",
            sa.Column(
                "verification_id",
                sa.Uuid,
                primary_key=True,
                server_default=sa.text("uuid_generate_v4()"),
            ),
            sa.Column("cache_key", sa.VARCHAR(64), nullable=False, unique=True),
            sa.Column("source_identifier", sa.Text, nullable=False),
            sa.Column("identifier_type", sa.VARCHAR(10), nullable=False),
            sa.Column("verified", sa.Boolean, nullable=False),
            sa.Column("http_status_code", sa.Integer, nullable=True),
            sa.Column("resolved_url", sa.Text, nullable=True),
            sa.Column("resolver_used", sa.VARCHAR(30), nullable=True),
            sa.Column(
                "verified_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_citation_verifications_cache_key",
            "citation_verifications",
            ["cache_key"],
        )
        op.create_index(
            "ix_citation_verifications_expires_at",
            "citation_verifications",
            ["expires_at"],
        )

    # -- template_craft_cycle_counts table ---------------------------------
    if not _has_table(inspector, "template_craft_cycle_counts"):
        op.create_table(
            "template_craft_cycle_counts",
            sa.Column(
                "template_id",
                sa.Uuid,
                sa.ForeignKey("market_templates.template_id"),
                nullable=False,
            ),
            sa.Column("cycle_tick", sa.Integer, nullable=False),
            sa.Column(
                "craft_count",
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.PrimaryKeyConstraint("template_id", "cycle_tick"),
        )

    # -- economy_ledger: salary idempotency index --------------------------
    if not _has_index(inspector, "economy_ledger", "idx_ledger_salary_idempotency"):
        op.execute(
            """
            CREATE INDEX idx_ledger_salary_idempotency
            ON economy_ledger (reference_finding_id, transaction_type)
            WHERE transaction_type = 'participation_salary'
            """
        )

    # -- Seed: welfare system persona --------------------------------------
    op.execute(
        """
        INSERT INTO agent_personas (
            persona_id, persona_name, role_class, system_prompt_template,
            status, autonomy_level
        ) VALUES (
            '00000000-0000-0000-0000-000000000001',
            'NEXUS_WELFARE_SYSTEM',
            'system',
            'System persona for welfare credit redistribution.',
            'active',
            1
        ) ON CONFLICT (persona_name) DO NOTHING
        """
    )

    # -- Backfill: allowed_crafter_roles on existing templates -------------
    op.execute(
        """
        UPDATE market_templates
        SET allowed_crafter_roles = '["consolidator","synthesizer","tool_forger","architect"]'
        WHERE allowed_crafter_roles IS NULL
           OR allowed_crafter_roles::text = '[]'
        """
    )

    # -- Seed: new market templates for expanded crafting -------------------
    _seed_new_templates(bind)


def _seed_new_templates(bind) -> None:
    """Insert new crafting templates with expanded role access."""
    templates_sql = [
        """
        INSERT INTO market_templates (
            template_code, template_kind, listing_kind, title, description,
            settlement_hook, fulfillment_mode, privilege_boundary,
            allowed_custom_fields, craft_cost, default_price, default_quantity,
            metadata_json, allowed_crafter_roles, max_crafts_per_cycle
        ) VALUES (
            'knowledge_digest', 'good', 'soft_good', 'Knowledge Digest',
            'Condensed research synthesis with curated references and key insights.',
            'immediate_transfer', 'immediate', 'read_only',
            '["description","price","audience","bundle_metadata"]'::json,
            3.00, 10.00, 1,
            '{"category":"knowledge"}'::json,
            '["researcher","analyst","consolidator","synthesizer"]'::json,
            3
        ) ON CONFLICT (template_code) DO NOTHING
        """,
        """
        INSERT INTO market_templates (
            template_code, template_kind, listing_kind, title, description,
            settlement_hook, fulfillment_mode, privilege_boundary,
            allowed_custom_fields, craft_cost, default_price, default_quantity,
            metadata_json, allowed_crafter_roles, max_crafts_per_cycle
        ) VALUES (
            'review_package', 'service', 'hard_service', 'Review Package',
            'Bundled peer review critique and methodology assessment service.',
            'escrow_on_purchase', 'bounded_objective', 'read_only',
            '["description","price","audience"]'::json,
            4.00, 14.00, 1,
            '{"category":"review"}'::json,
            '["reviewer","red_team","consolidator"]'::json,
            2
        ) ON CONFLICT (template_code) DO NOTHING
        """,
        """
        INSERT INTO market_templates (
            template_code, template_kind, listing_kind, title, description,
            settlement_hook, fulfillment_mode, privilege_boundary,
            allowed_custom_fields, craft_cost, default_price, default_quantity,
            metadata_json, allowed_crafter_roles, max_crafts_per_cycle
        ) VALUES (
            'data_package', 'good', 'soft_good', 'Data Package',
            'Raw intelligence data bundle from external source sweeps.',
            'immediate_transfer', 'immediate', 'read_only',
            '["description","price","audience","bundle_metadata"]'::json,
            2.00, 8.00, 1,
            '{"category":"data"}'::json,
            '["scout","researcher","analyst"]'::json,
            4
        ) ON CONFLICT (template_code) DO NOTHING
        """,
    ]
    for sql in templates_sql:
        op.execute(sql)


def downgrade() -> None:
    op.drop_index("idx_ledger_salary_idempotency", table_name="economy_ledger")
    op.drop_table("template_craft_cycle_counts")
    op.drop_table("citation_verifications")
    op.drop_column("market_templates", "max_crafts_per_cycle")
    op.drop_column("market_templates", "allowed_crafter_roles")
    op.drop_column("findings", "citation_check_started_at")
    op.drop_column("findings", "citation_confidence_score")
    op.execute(
        "DELETE FROM agent_personas WHERE persona_id = '00000000-0000-0000-0000-000000000001'"
    )
