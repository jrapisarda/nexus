"""Add wealth generation infrastructure: KG node ownership, OBI pricing, market making.

- New columns on knowledge_graph_nodes: owner_persona_id, purchase_price, last_traversal_count, betweenness_score, acquired_at
- New column on market_instruments: par_value
- New table: kg_node_bids (purchase and takeover bids for KG nodes)
- New index on knowledge_graph_nodes for owned nodes
- Seed: NEXUS_FEE_POOL system persona

Revision ID: 009
Revises: 008
Create Date: 2026-03-24
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009"
down_revision: Union[str, None] = "008"
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

    # -- knowledge_graph_nodes: ownership columns --------------------------
    if not _has_column(inspector, "knowledge_graph_nodes", "owner_persona_id"):
        op.add_column(
            "knowledge_graph_nodes",
            sa.Column(
                "owner_persona_id",
                sa.Uuid,
                sa.ForeignKey("agent_personas.persona_id"),
                nullable=True,
            ),
        )

    if not _has_column(inspector, "knowledge_graph_nodes", "purchase_price"):
        op.add_column(
            "knowledge_graph_nodes",
            sa.Column("purchase_price", sa.Numeric(12, 2), nullable=True),
        )

    if not _has_column(inspector, "knowledge_graph_nodes", "last_traversal_count"):
        op.add_column(
            "knowledge_graph_nodes",
            sa.Column(
                "last_traversal_count",
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    if not _has_column(inspector, "knowledge_graph_nodes", "betweenness_score"):
        op.add_column(
            "knowledge_graph_nodes",
            sa.Column(
                "betweenness_score",
                sa.Numeric(8, 6),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
        )

    if not _has_column(inspector, "knowledge_graph_nodes", "acquired_at"):
        op.add_column(
            "knowledge_graph_nodes",
            sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        )

    # -- market_instruments: par_value -------------------------------------
    if not _has_column(inspector, "market_instruments", "par_value"):
        op.add_column(
            "market_instruments",
            sa.Column(
                "par_value",
                sa.Numeric(12, 2),
                nullable=False,
                server_default=sa.text("50.00"),
            ),
        )

    # -- kg_node_bids table ------------------------------------------------
    if not _has_table(inspector, "kg_node_bids"):
        op.create_table(
            "kg_node_bids",
            sa.Column(
                "bid_id",
                sa.Uuid,
                primary_key=True,
                server_default=sa.text("uuid_generate_v4()"),
            ),
            sa.Column(
                "node_id",
                sa.Uuid,
                sa.ForeignKey("knowledge_graph_nodes.node_id"),
                nullable=False,
            ),
            sa.Column(
                "bidder_persona_id",
                sa.Uuid,
                sa.ForeignKey("agent_personas.persona_id"),
                nullable=False,
            ),
            sa.Column("bid_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column(
                "bid_type",
                sa.VARCHAR(20),
                nullable=False,
                server_default="purchase",
            ),
            sa.Column(
                "status",
                sa.VARCHAR(20),
                nullable=False,
                server_default="open",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )

    # -- Index on owned nodes ----------------------------------------------
    if not _has_index(inspector, "knowledge_graph_nodes", "idx_kg_nodes_owner"):
        op.execute(
            """
            CREATE INDEX idx_kg_nodes_owner
            ON knowledge_graph_nodes(owner_persona_id)
            WHERE owner_persona_id IS NOT NULL
            """
        )

    # -- Backfill par_value from current mark_price ------------------------
    op.execute(
        """
        UPDATE market_instruments
        SET par_value = COALESCE(mark_price, 50.00)
        WHERE par_value = 50.00
          AND mark_price IS NOT NULL
          AND mark_price != 50.00
        """
    )

    # -- Seed: NEXUS_FEE_POOL system persona -------------------------------
    op.execute(
        """
        INSERT INTO agent_personas (
            persona_id, persona_name, role_class, system_prompt_template,
            status, autonomy_level
        ) VALUES (
            '00000000-0000-0000-0000-000000000002',
            'NEXUS_FEE_POOL',
            'system',
            'System persona for protocol fee collection and market maker rebates.',
            'active',
            1
        ) ON CONFLICT (persona_name) DO NOTHING
        """
    )

    # Seed fee pool with 100 credits
    op.execute(
        """
        INSERT INTO economy_ledger (from_persona_id, to_persona_id, amount, transaction_type, memo)
        SELECT NULL, '00000000-0000-0000-0000-000000000002', 100.00, 'mint', 'Initial fee pool seed'
        WHERE NOT EXISTS (
            SELECT 1 FROM economy_ledger
            WHERE to_persona_id = '00000000-0000-0000-0000-000000000002'
            AND transaction_type = 'mint'
            AND memo = 'Initial fee pool seed'
        )
        """
    )


def downgrade() -> None:
    op.drop_index("idx_kg_nodes_owner", table_name="knowledge_graph_nodes")
    op.drop_table("kg_node_bids")
    op.drop_column("market_instruments", "par_value")
    op.drop_column("knowledge_graph_nodes", "acquired_at")
    op.drop_column("knowledge_graph_nodes", "betweenness_score")
    op.drop_column("knowledge_graph_nodes", "last_traversal_count")
    op.drop_column("knowledge_graph_nodes", "purchase_price")
    op.drop_column("knowledge_graph_nodes", "owner_persona_id")
    op.execute(
        "DELETE FROM agent_personas WHERE persona_id = '00000000-0000-0000-0000-000000000002'"
    )
