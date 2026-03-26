"""Align ledger balances, telemetry cost splits, and KG embeddings.

Revision ID: 003
Revises: 002
Create Date: 2026-03-17
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from nexus_core.utils.embeddings import EmbeddingService

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INPUT_COST_PER_MILLION = Decimal("0.60")
OUTPUT_COST_PER_MILLION = Decimal("2.50")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    has_properties_embedding = _has_column(
        inspector, "knowledge_graph_nodes", "properties_embedding"
    )
    if not has_properties_embedding:
        op.add_column(
            "knowledge_graph_nodes",
            sa.Column("properties_embedding", Vector(384), nullable=True),
        )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_kg_nodes_embedding_hnsw "
            "ON knowledge_graph_nodes USING hnsw (properties_embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )
    )

    has_cost_thinking = _has_column(inspector, "agent_telemetry", "cost_thinking_usd")
    if not has_cost_thinking:
        op.add_column(
            "agent_telemetry",
            sa.Column(
                "cost_thinking_usd",
                sa.Numeric(8, 6),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    if _has_column(inspector, "agent_personas", "credit_balance"):
        bind.execute(
            sa.text(
                """
                WITH balances AS (
                    SELECT
                        p.persona_id,
                        COALESCE(p.credit_balance, 0) AS desired_balance,
                        COALESCE(incoming.total_in, 0) - COALESCE(outgoing.total_out, 0) AS current_balance
                    FROM agent_personas p
                    LEFT JOIN (
                        SELECT to_persona_id AS persona_id, SUM(amount) AS total_in
                        FROM economy_ledger
                        WHERE to_persona_id IS NOT NULL
                        GROUP BY to_persona_id
                    ) incoming ON incoming.persona_id = p.persona_id
                    LEFT JOIN (
                        SELECT from_persona_id AS persona_id, SUM(amount) AS total_out
                        FROM economy_ledger
                        WHERE from_persona_id IS NOT NULL
                        GROUP BY from_persona_id
                    ) outgoing ON outgoing.persona_id = p.persona_id
                )
                INSERT INTO economy_ledger (
                    from_persona_id,
                    to_persona_id,
                    amount,
                    transaction_type,
                    memo
                )
                SELECT
                    NULL,
                    persona_id,
                    desired_balance - current_balance,
                    'migration_balance_seed',
                    'Backfilled from deprecated agent_personas.credit_balance'
                FROM balances
                WHERE desired_balance - current_balance > 0
                """
            )
        )

    bind.execute(
        sa.text(
            """
            UPDATE agent_telemetry
            SET
                cost_input_usd = ROUND((tokens_input::numeric * :input_rate) / 1000000, 6),
                cost_thinking_usd = ROUND((tokens_thinking::numeric * :output_rate) / 1000000, 6),
                cost_output_usd = ROUND((tokens_output::numeric * :output_rate) / 1000000, 6),
                cost_total_usd = ROUND(
                    ((tokens_input::numeric * :input_rate) / 1000000) +
                    ((tokens_thinking::numeric * :output_rate) / 1000000) +
                    ((tokens_output::numeric * :output_rate) / 1000000),
                    6
                )
            """
        ),
        {
            "input_rate": INPUT_COST_PER_MILLION,
            "output_rate": OUTPUT_COST_PER_MILLION,
        },
    )

    node_rows = bind.execute(
        sa.text(
            "SELECT node_id, node_type, label, properties "
            "FROM knowledge_graph_nodes "
            "WHERE properties_embedding IS NULL"
        )
    )
    for row in node_rows:
        embedding_text = _build_node_embedding_text(
            row.node_type,
            row.label,
            row.properties,
        )
        embedding = EmbeddingService.hash_encode(embedding_text).tolist()
        bind.execute(
            sa.text(
                "UPDATE knowledge_graph_nodes "
                "SET properties_embedding = :embedding "
                "WHERE node_id = :node_id"
            ),
            {"embedding": embedding, "node_id": row.node_id},
        )

    op.alter_column("agent_telemetry", "cost_thinking_usd", server_default=None)
    if _has_column(inspector, "agent_personas", "credit_balance"):
        op.drop_column("agent_personas", "credit_balance")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    has_credit_balance = _has_column(inspector, "agent_personas", "credit_balance")
    if not has_credit_balance:
        op.add_column(
            "agent_personas",
            sa.Column(
                "credit_balance",
                sa.Numeric(12, 2),
                nullable=True,
                server_default=sa.text("0"),
            ),
        )
    bind.execute(
        sa.text(
            """
            UPDATE agent_personas p
            SET credit_balance = balances.current_balance
            FROM (
                SELECT
                    persona_id,
                    COALESCE(total_in, 0) - COALESCE(total_out, 0) AS current_balance
                FROM (
                    SELECT persona_id, SUM(total_in) AS total_in, SUM(total_out) AS total_out
                    FROM (
                        SELECT to_persona_id AS persona_id, SUM(amount) AS total_in, 0::numeric AS total_out
                        FROM economy_ledger
                        WHERE to_persona_id IS NOT NULL
                        GROUP BY to_persona_id
                        UNION ALL
                        SELECT from_persona_id AS persona_id, 0::numeric AS total_in, SUM(amount) AS total_out
                        FROM economy_ledger
                        WHERE from_persona_id IS NOT NULL
                        GROUP BY from_persona_id
                    ) ledger_totals
                    GROUP BY persona_id
                ) aggregated
            ) balances
            WHERE p.persona_id = balances.persona_id
            """
        )
    )
    op.alter_column("agent_personas", "credit_balance", server_default=None)

    if _has_column(inspector, "agent_telemetry", "cost_thinking_usd"):
        op.drop_column("agent_telemetry", "cost_thinking_usd")
    op.execute(sa.text("DROP INDEX IF EXISTS ix_kg_nodes_embedding_hnsw"))
    if _has_column(inspector, "knowledge_graph_nodes", "properties_embedding"):
        op.drop_column("knowledge_graph_nodes", "properties_embedding")


def _build_node_embedding_text(
    node_type: str | None,
    label: str | None,
    properties,
) -> str:
    properties_text = ""
    if isinstance(properties, dict):
        properties_text = json.dumps(properties, sort_keys=True)
    elif properties is not None:
        properties_text = str(properties)

    return " ".join(
        part
        for part in [node_type or "", label or "", properties_text]
        if part
    )


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in inspector.get_columns(table_name)
    )
