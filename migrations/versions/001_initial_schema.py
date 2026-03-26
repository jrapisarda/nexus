"""Initial NEXUS schema — all 16 tables, indexes, and NOTIFY triggers.

Revision ID: 001
Revises: None
Create Date: 2026-03-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. agent_personas
    # ------------------------------------------------------------------
    op.create_table(
        "agent_personas",
        sa.Column("persona_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("persona_name", sa.VARCHAR(255), nullable=False, unique=True),
        sa.Column("role_class", sa.VARCHAR(50), nullable=False),
        sa.Column("system_prompt_template", sa.Text, nullable=False),
        sa.Column("tool_permissions", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reasoning_strategy", sa.VARCHAR(50), server_default="chain-of-thought"),
        sa.Column("model_config_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("autonomy_level", sa.Integer, server_default=sa.text("3")),
        sa.Column("parent_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
        sa.Column("generation", sa.Integer, server_default=sa.text("0")),
        sa.Column("reputation_score", sa.Numeric(5, 3), server_default=sa.text("0.500")),
        sa.Column("compute_budget", sa.Numeric(10, 2), server_default=sa.text("50.00")),
        sa.Column("status", sa.VARCHAR(20), server_default="active"),
        sa.Column("specialization_vector", Vector(384), nullable=True),
        sa.Column("mutation_diff", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecation_reason", sa.Text, nullable=True),
        sa.CheckConstraint("autonomy_level >= 1 AND autonomy_level <= 5", name="ck_autonomy_level_range"),
    )

    # ------------------------------------------------------------------
    # 2. objectives
    # ------------------------------------------------------------------
    op.create_table(
        "objectives",
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
        sa.CheckConstraint("priority >= 1 AND priority <= 10", name="ck_priority_range"),
    )

    # ------------------------------------------------------------------
    # 3. agent_instances
    # ------------------------------------------------------------------
    op.create_table(
        "agent_instances",
        sa.Column("instance_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
        sa.Column("objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=False),
        sa.Column("session_state", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("spawned_by", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=True),
        sa.Column("spawn_reason", sa.Text, nullable=True),
        sa.Column("input_prompt", sa.Text, nullable=False),
        sa.Column("output_content", sa.Text, nullable=True),
        sa.Column("thinking_content", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", sa.VARCHAR(20), server_default="pending"),
        sa.Column("retry_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("tokens_input", sa.Integer, server_default=sa.text("0")),
        sa.Column("tokens_thinking", sa.Integer, server_default=sa.text("0")),
        sa.Column("tokens_output", sa.Integer, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Numeric(8, 6), server_default=sa.text("0")),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    # ------------------------------------------------------------------
    # 4. objective_decomposition
    # ------------------------------------------------------------------
    op.create_table(
        "objective_decomposition",
        sa.Column("decomposition_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("parent_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=False),
        sa.Column("child_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=False),
        sa.Column("decomposition_rationale", sa.Text, nullable=False),
        sa.Column("dependency_type", sa.VARCHAR(20), nullable=False),
        sa.Column("depends_on", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("execution_order", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 5. knowledge_graph_nodes
    # ------------------------------------------------------------------
    op.create_table(
        "knowledge_graph_nodes",
        sa.Column("node_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("node_type", sa.VARCHAR(50), nullable=False),
        sa.Column("label", sa.VARCHAR(500), nullable=False),
        sa.Column("properties", postgresql.JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("properties_embedding", Vector(384), nullable=True),
        sa.Column("confidence_score", sa.Numeric(4, 3), server_default=sa.text("0.500")),
        sa.Column("discovered_by_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
        sa.Column("discovered_by_instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=True),
        sa.Column("validation_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("challenge_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("challenge_failures", sa.Integer, server_default=sa.text("0")),
        sa.Column("status", sa.VARCHAR(20), server_default="proposed"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_validated", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 6. knowledge_graph_edges
    # ------------------------------------------------------------------
    op.create_table(
        "knowledge_graph_edges",
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

    # ------------------------------------------------------------------
    # 7. findings
    # ------------------------------------------------------------------
    op.create_table(
        "findings",
        sa.Column("finding_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=False),
        sa.Column("instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=False),
        sa.Column("finding_type", sa.VARCHAR(50), nullable=False),
        sa.Column("title", sa.VARCHAR(500), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("structured_data", sa.JSON, nullable=True),
        sa.Column("status", sa.VARCHAR(20), server_default="pending_review"),
        sa.Column("review_round", sa.Integer, server_default=sa.text("0")),
        sa.Column("impact_level", sa.VARCHAR(20), server_default="routine"),
        sa.Column("kg_nodes_created", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("kg_edges_created", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_infiltration", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 8. peer_reviews
    # ------------------------------------------------------------------
    op.create_table(
        "peer_reviews",
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

    # ------------------------------------------------------------------
    # 9. economy_ledger
    # ------------------------------------------------------------------
    op.create_table(
        "economy_ledger",
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

    # ------------------------------------------------------------------
    # 10. governance_proposals
    # ------------------------------------------------------------------
    op.create_table(
        "governance_proposals",
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

    # ------------------------------------------------------------------
    # 11. governance_votes
    # ------------------------------------------------------------------
    op.create_table(
        "governance_votes",
        sa.Column("vote_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("proposal_id", sa.Uuid, sa.ForeignKey("governance_proposals.proposal_id"), nullable=False),
        sa.Column("voter_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
        sa.Column("vote", sa.VARCHAR(10), nullable=False),
        sa.Column("reasoning", sa.Text, nullable=False),
        sa.Column("voter_reputation_weight", sa.Numeric(5, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 12. messages
    # ------------------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("message_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("from_instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=True),
        sa.Column("to_instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=True),
        sa.Column("to_role_class", sa.VARCHAR(50), nullable=True),
        sa.Column("message_type", sa.VARCHAR(50), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("priority", sa.Integer, server_default=sa.text("5")),
        sa.Column("status", sa.VARCHAR(20), server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 13. institutional_memory
    # ------------------------------------------------------------------
    op.create_table(
        "institutional_memory",
        sa.Column("memory_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("memory_type", sa.VARCHAR(50), nullable=False),
        sa.Column("title", sa.VARCHAR(500), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
        sa.Column("source_instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=True),
        sa.Column("relevance_tags", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("retrieval_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 14. tool_registry
    # ------------------------------------------------------------------
    op.create_table(
        "tool_registry",
        sa.Column("tool_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tool_name", sa.VARCHAR(255), nullable=False, unique=True),
        sa.Column("tool_type", sa.VARCHAR(20), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("input_schema", sa.JSON, nullable=False),
        sa.Column("output_schema", sa.JSON, nullable=False),
        sa.Column("implementation", sa.Text, nullable=True),
        sa.Column("created_by_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
        sa.Column("created_by_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
        sa.Column("usage_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("success_rate", sa.Numeric(4, 3), server_default=sa.text("1.000")),
        sa.Column("status", sa.VARCHAR(20), server_default="active"),
        sa.Column("required_permissions", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 15. agent_telemetry
    # ------------------------------------------------------------------
    op.create_table(
        "agent_telemetry",
        sa.Column("telemetry_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("instance_id", sa.Uuid, sa.ForeignKey("agent_instances.instance_id"), nullable=False),
        sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
        sa.Column("objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=False),
        sa.Column("api_call_timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("prompt_hash", sa.VARCHAR(64), nullable=False),
        sa.Column("tokens_input", sa.Integer, nullable=False),
        sa.Column("tokens_thinking", sa.Integer, nullable=False),
        sa.Column("tokens_output", sa.Integer, nullable=False),
        sa.Column("cost_input_usd", sa.Numeric(8, 6), nullable=False),
        sa.Column("cost_thinking_usd", sa.Numeric(8, 6), nullable=False),
        sa.Column("cost_output_usd", sa.Numeric(8, 6), nullable=False),
        sa.Column("cost_total_usd", sa.Numeric(8, 6), nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("http_status", sa.Integer, nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("error_category", sa.VARCHAR(50), nullable=True),
        sa.Column("model_id", sa.VARCHAR(100), nullable=False),
    )

    # ------------------------------------------------------------------
    # 16. events (outbox)
    # ------------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column("event_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_type", sa.VARCHAR(100), nullable=False),
        sa.Column("entity_id", sa.Uuid, nullable=True),
        sa.Column("entity_type", sa.VARCHAR(50), nullable=True),
        sa.Column("payload", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("processed", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ==================================================================
    # INDEXES
    # ==================================================================

    # objectives: (status, priority, created_at)
    op.create_index(
        "ix_objectives_status_priority_created",
        "objectives",
        ["status", "priority", "created_at"],
    )

    # agent_instances: (status, persona_id)
    op.create_index(
        "ix_agent_instances_status_persona",
        "agent_instances",
        ["status", "persona_id"],
    )

    # economy_ledger: (to_persona_id, created_at)
    op.create_index(
        "ix_economy_ledger_to_persona_created",
        "economy_ledger",
        ["to_persona_id", "created_at"],
    )

    # economy_ledger: (from_persona_id, created_at)
    op.create_index(
        "ix_economy_ledger_from_persona_created",
        "economy_ledger",
        ["from_persona_id", "created_at"],
    )

    # knowledge_graph_nodes: GIN on properties
    op.create_index(
        "ix_kg_nodes_properties_gin",
        "knowledge_graph_nodes",
        ["properties"],
        postgresql_using="gin",
    )

    # knowledge_graph_nodes: pg_trgm GIN on label
    op.execute(
        sa.text(
            "CREATE INDEX ix_kg_nodes_label_trgm ON knowledge_graph_nodes "
            "USING gin (label gin_trgm_ops)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_kg_nodes_embedding_hnsw "
            "ON knowledge_graph_nodes USING hnsw (properties_embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )
    )

    # knowledge_graph_edges: (source_node_id, target_node_id)
    op.create_index(
        "ix_kg_edges_source_target",
        "knowledge_graph_edges",
        ["source_node_id", "target_node_id"],
    )

    # knowledge_graph_edges: (target_node_id)
    op.create_index(
        "ix_kg_edges_target",
        "knowledge_graph_edges",
        ["target_node_id"],
    )

    # peer_reviews: (finding_id)
    op.create_index(
        "ix_peer_reviews_finding",
        "peer_reviews",
        ["finding_id"],
    )

    # agent_telemetry: (instance_id, api_call_timestamp)
    op.create_index(
        "ix_agent_telemetry_instance_timestamp",
        "agent_telemetry",
        ["instance_id", "api_call_timestamp"],
    )

    # events: (processed, created_at)
    op.create_index(
        "ix_events_processed_created",
        "events",
        ["processed", "created_at"],
    )

    # HNSW index on specialization_vector (pgvector)
    op.execute(
        sa.text(
            "CREATE INDEX ix_agent_personas_specialization_hnsw "
            "ON agent_personas USING hnsw (specialization_vector vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )
    )

    # ==================================================================
    # NOTIFY TRIGGERS
    # ==================================================================

    # Trigger function: generic NOTIFY helper
    op.execute(
        sa.text("""
            CREATE OR REPLACE FUNCTION nexus_notify_event()
            RETURNS trigger AS $$
            BEGIN
                PERFORM pg_notify(
                    'nexus_events',
                    json_build_object(
                        'table', TG_TABLE_NAME,
                        'action', TG_OP,
                        'id', NEW.event_id::text
                    )::text
                );
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
    )

    # After INSERT on objectives
    op.execute(
        sa.text("""
            CREATE OR REPLACE FUNCTION nexus_notify_objective()
            RETURNS trigger AS $$
            BEGIN
                PERFORM pg_notify(
                    'nexus_events',
                    json_build_object(
                        'table', 'objectives',
                        'action', TG_OP,
                        'id', NEW.objective_id::text
                    )::text
                );
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
    )

    op.execute(
        sa.text("""
            CREATE TRIGGER trg_objectives_insert
            AFTER INSERT ON objectives
            FOR EACH ROW EXECUTE FUNCTION nexus_notify_objective();
        """)
    )

    # After INSERT on events
    op.execute(
        sa.text("""
            CREATE TRIGGER trg_events_insert
            AFTER INSERT ON events
            FOR EACH ROW EXECUTE FUNCTION nexus_notify_event();
        """)
    )

    # After UPDATE of status on agent_instances
    op.execute(
        sa.text("""
            CREATE OR REPLACE FUNCTION nexus_notify_instance_status()
            RETURNS trigger AS $$
            BEGIN
                IF OLD.status IS DISTINCT FROM NEW.status THEN
                    PERFORM pg_notify(
                        'nexus_events',
                        json_build_object(
                            'table', 'agent_instances',
                            'action', 'STATUS_CHANGE',
                            'id', NEW.instance_id::text,
                            'old_status', OLD.status,
                            'new_status', NEW.status
                        )::text
                    );
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
    )

    op.execute(
        sa.text("""
            CREATE TRIGGER trg_agent_instances_status_update
            AFTER UPDATE OF status ON agent_instances
            FOR EACH ROW EXECUTE FUNCTION nexus_notify_instance_status();
        """)
    )


def downgrade() -> None:
    # Drop triggers first
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_agent_instances_status_update ON agent_instances"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_events_insert ON events"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_objectives_insert ON objectives"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS nexus_notify_instance_status()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS nexus_notify_event()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS nexus_notify_objective()"))

    # Drop indexes created via raw SQL
    op.execute(sa.text("DROP INDEX IF EXISTS ix_agent_personas_specialization_hnsw"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_kg_nodes_label_trgm"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_kg_nodes_embedding_hnsw"))

    # Drop tables in reverse dependency order
    op.drop_table("events")
    op.drop_table("agent_telemetry")
    op.drop_table("tool_registry")
    op.drop_table("institutional_memory")
    op.drop_table("messages")
    op.drop_table("governance_votes")
    op.drop_table("governance_proposals")
    op.drop_table("economy_ledger")
    op.drop_table("peer_reviews")
    op.drop_table("findings")
    op.drop_table("knowledge_graph_edges")
    op.drop_table("knowledge_graph_nodes")
    op.drop_table("objective_decomposition")
    op.drop_table("agent_instances")
    op.drop_table("objectives")
    op.drop_table("agent_personas")
