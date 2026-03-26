"""Add canonical KG labels for deterministic deduplication.

Revision ID: 004
Revises: 003
Create Date: 2026-03-20
"""

from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "knowledge_graph_nodes", "canonical_label"):
        op.add_column(
            "knowledge_graph_nodes",
            sa.Column("canonical_label", sa.VARCHAR(length=500), nullable=True),
        )

    rows = bind.execute(
        sa.text(
            "SELECT node_id, label FROM knowledge_graph_nodes "
            "WHERE canonical_label IS NULL OR canonical_label = ''"
        )
    )
    for row in rows:
        bind.execute(
            sa.text(
                "UPDATE knowledge_graph_nodes "
                "SET canonical_label = :canonical_label "
                "WHERE node_id = :node_id"
            ),
            {
                "node_id": row.node_id,
                "canonical_label": _normalize_canonical_label(row.label or ""),
            },
        )

    op.alter_column(
        "knowledge_graph_nodes",
        "canonical_label",
        existing_type=sa.VARCHAR(length=500),
        nullable=False,
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_kg_nodes_canonical_label "
            "ON knowledge_graph_nodes (canonical_label)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_kg_nodes_type_canonical_label "
            "ON knowledge_graph_nodes (node_type, canonical_label)"
        )
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    op.execute(sa.text("DROP INDEX IF EXISTS ix_kg_nodes_type_canonical_label"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_kg_nodes_canonical_label"))
    if _has_column(inspector, "knowledge_graph_nodes", "canonical_label"):
        op.drop_column("knowledge_graph_nodes", "canonical_label")


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in inspector.get_columns(table_name)
    )


def _normalize_canonical_label(label: str) -> str:
    normalized = re.sub(r"[\s\-_]+", " ", label.strip().lower())
    normalized = re.sub(r"[^\w\s/]", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()
