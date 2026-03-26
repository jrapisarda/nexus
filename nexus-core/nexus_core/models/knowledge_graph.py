"""knowledge_graph_nodes and knowledge_graph_edges table definitions."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

from nexus_core.models import metadata

knowledge_graph_nodes = sa.Table(
    "knowledge_graph_nodes",
    metadata,
    sa.Column("node_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("node_type", sa.VARCHAR(50), nullable=False),
    sa.Column("label", sa.VARCHAR(500), nullable=False),
    sa.Column("canonical_label", sa.VARCHAR(500), nullable=False),
    sa.Column("properties", JSONB, server_default=sa.text("'{}'::jsonb")),
    sa.Column("properties_embedding", Vector(384), nullable=True),
    sa.Column("confidence_score", sa.Numeric(4, 3), server_default=sa.text("0.500")),
    sa.Column("discovered_by_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
    sa.Column("discovered_by_instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=True),
    sa.Column("validation_count", sa.Integer, server_default=sa.text("0")),
    sa.Column("challenge_count", sa.Integer, server_default=sa.text("0")),
    sa.Column("challenge_failures", sa.Integer, server_default=sa.text("0")),
    sa.Column("status", sa.VARCHAR(20), server_default="proposed"),
    sa.Column("owner_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
    sa.Column("purchase_price", sa.Numeric(12, 2), nullable=True),
    sa.Column("last_traversal_count", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("betweenness_score", sa.Numeric(8, 6), nullable=False, server_default=sa.text("0.0")),
    sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("last_validated", sa.DateTime(timezone=True), nullable=True),
)

knowledge_graph_edges = sa.Table(
    "knowledge_graph_edges",
    metadata,
    sa.Column("edge_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("source_node_id", sa.Uuid, sa.ForeignKey("knowledge_graph_nodes.node_id"), nullable=False),
    sa.Column("target_node_id", sa.Uuid, sa.ForeignKey("knowledge_graph_nodes.node_id"), nullable=False),
    sa.Column("relationship_type", sa.VARCHAR(100), nullable=False),
    sa.Column("weight", sa.Numeric(5, 3), server_default=sa.text("0.500")),
    sa.Column("confidence_score", sa.Numeric(4, 3), server_default=sa.text("0.500")),
    sa.Column("evidence_ids", sa.JSON, server_default=sa.text("'[]'::jsonb")),
    sa.Column("discovered_by_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
    sa.Column("challenged_by_objective_ids", sa.JSON, server_default=sa.text("'[]'::jsonb")),
    sa.Column("status", sa.VARCHAR(20), server_default="proposed"),
    sa.Column("properties", sa.JSON, server_default=sa.text("'{}'::jsonb")),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)
