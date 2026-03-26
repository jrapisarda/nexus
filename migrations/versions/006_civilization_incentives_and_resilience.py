"""Add civilization incentives, capability scoring, and shadow resilience schema.

Revision ID: 006
Revises: 005
Create Date: 2026-03-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _add_column_if_missing("agent_personas", sa.Column("sponsor_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True))
    _add_column_if_missing("agent_personas", sa.Column("probation_until", sa.DateTime(timezone=True), nullable=True))

    if not _has_table(inspector, "persona_capability_scores"):
        op.create_table(
            "persona_capability_scores",
            sa.Column("capability_score_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("capability", sa.VARCHAR(30), nullable=False),
            sa.Column("active_score", sa.Numeric(5, 3), nullable=False, server_default=sa.text("0.500")),
            sa.Column("persistent_score", sa.Numeric(5, 3), nullable=False, server_default=sa.text("0.500")),
            sa.Column("success_count", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("failure_count", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("last_signal_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("persona_id", "capability", name="uq_persona_capability_scores_persona_capability"),
        )

    if not _has_table(inspector, "civilization_bonds"):
        op.create_table(
            "civilization_bonds",
            sa.Column("bond_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("sponsor_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
            sa.Column("bond_type", sa.VARCHAR(40), nullable=False),
            sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="locked"),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("slashed_amount", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("reference_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
            sa.Column("reference_finding_id", sa.Uuid, sa.ForeignKey("findings.finding_id"), nullable=True),
            sa.Column("reference_contract_id", sa.Uuid, sa.ForeignKey("service_contracts.contract_id"), nullable=True),
            sa.Column("reference_order_id", sa.Uuid, sa.ForeignKey("market_orders.order_id"), nullable=True),
            sa.Column("memo", sa.Text, nullable=True),
            sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("release_after", sa.DateTime(timezone=True), nullable=True),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "civilization_challenges"):
        op.create_table(
            "civilization_challenges",
            sa.Column("challenge_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("finding_id", sa.Uuid, sa.ForeignKey("findings.finding_id"), nullable=False),
            sa.Column("challenger_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("case_type", sa.VARCHAR(30), nullable=False, server_default="finding"),
            sa.Column("flaw_type", sa.VARCHAR(40), nullable=True),
            sa.Column("severity", sa.VARCHAR(20), nullable=True),
            sa.Column("summary", sa.Text, nullable=True),
            sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="open"),
            sa.Column("bond_id", sa.Uuid, sa.ForeignKey("civilization_bonds.bond_id"), nullable=True),
            sa.Column("resolution_kind", sa.VARCHAR(30), nullable=True),
            sa.Column("resolution_notes", sa.Text, nullable=True),
            sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("resolution_due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_table(inspector, "civilization_quality_holdbacks"):
        op.create_table(
            "civilization_quality_holdbacks",
            sa.Column("holdback_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("finding_id", sa.Uuid, sa.ForeignKey("findings.finding_id"), nullable=False),
            sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("holdback_type", sa.VARCHAR(30), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="pending"),
            sa.Column("source_round", sa.Integer, nullable=False, server_default=sa.text("1")),
            sa.Column("reserve_ratio", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0.20")),
            sa.Column("challenge_id", sa.Uuid, nullable=True),
            sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("release_after", sa.DateTime(timezone=True), nullable=True),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("slashed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "objective_incentive_profiles"):
        op.create_table(
            "objective_incentive_profiles",
            sa.Column("objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), primary_key=True),
            sa.Column("slow_science_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
            sa.Column("uncertainty_level", sa.VARCHAR(20), nullable=False, server_default="standard"),
            sa.Column("rent_multiplier", sa.Numeric(5, 2), nullable=False, server_default=sa.text("1.00")),
            sa.Column("reserve_ratio", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("challenge_window_minutes", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("shadow_policy_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "scout_source_health"):
        op.create_table(
            "scout_source_health",
            sa.Column("source_name", sa.VARCHAR(80), primary_key=True),
            sa.Column("health_status", sa.VARCHAR(20), nullable=False, server_default="healthy"),
            sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("total_runs", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("total_successes", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("findings_ingested", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("objectives_proposed", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "evolution_metric_snapshots"):
        op.create_table(
            "evolution_metric_snapshots",
            sa.Column("snapshot_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("concentration_score", sa.Numeric(6, 4), nullable=False, server_default=sa.text("0.0000")),
            sa.Column("role_diversity_score", sa.Numeric(6, 4), nullable=False, server_default=sa.text("0.0000")),
            sa.Column("novelty_score", sa.Numeric(6, 4), nullable=False, server_default=sa.text("0.0000")),
            sa.Column("stagnation_score", sa.Numeric(6, 4), nullable=False, server_default=sa.text("0.0000")),
            sa.Column("explorer_pressure_score", sa.Numeric(6, 4), nullable=False, server_default=sa.text("0.0000")),
            sa.Column("exploration_pulse_triggered", sa.Boolean, nullable=False, server_default=sa.text("false")),
            sa.Column("metrics_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "circuit_breaker_rules"):
        op.create_table(
            "circuit_breaker_rules",
            sa.Column("rule_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("rule_code", sa.VARCHAR(80), nullable=False, unique=True),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("mode", sa.VARCHAR(20), nullable=False, server_default="shadow"),
            sa.Column("threshold_value", sa.Numeric(12, 4), nullable=False),
            sa.Column("window_minutes", sa.Integer, nullable=False, server_default=sa.text("60")),
            sa.Column("action_type", sa.VARCHAR(40), nullable=False),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
            sa.Column("shadow_only", sa.Boolean, nullable=False, server_default=sa.text("true")),
            sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "circuit_breaker_incidents"):
        op.create_table(
            "circuit_breaker_incidents",
            sa.Column("incident_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("rule_id", sa.Uuid, sa.ForeignKey("circuit_breaker_rules.rule_id"), nullable=False),
            sa.Column("mode", sa.VARCHAR(20), nullable=False, server_default="shadow"),
            sa.Column("severity", sa.VARCHAR(20), nullable=False, server_default="warning"),
            sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="open"),
            sa.Column("observed_value", sa.Numeric(12, 4), nullable=False),
            sa.Column("threshold_value", sa.Numeric(12, 4), nullable=False),
            sa.Column("payload", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )

    _create_index_if_not_exists("ix_capability_persona", "persona_capability_scores", "persona_id, capability")
    _create_index_if_not_exists("ix_bonds_persona_status", "civilization_bonds", "persona_id, status, release_after")
    _create_index_if_not_exists("ix_challenges_finding_status", "civilization_challenges", "finding_id, status, opened_at")
    _create_index_if_not_exists("ix_holdbacks_finding_status", "civilization_quality_holdbacks", "finding_id, status, release_after")
    _create_index_if_not_exists("ix_objective_incentive_slow", "objective_incentive_profiles", "slow_science_enabled, reserve_ratio")
    _create_index_if_not_exists("ix_scout_source_health_status", "scout_source_health", "health_status, updated_at")
    _create_index_if_not_exists("ix_evolution_snapshots_created", "evolution_metric_snapshots", "created_at")
    _create_index_if_not_exists("ix_breaker_incidents_rule_status", "circuit_breaker_incidents", "rule_id, status, created_at")


def downgrade() -> None:
    for index_name in [
        "ix_breaker_incidents_rule_status",
        "ix_evolution_snapshots_created",
        "ix_scout_source_health_status",
        "ix_objective_incentive_slow",
        "ix_holdbacks_finding_status",
        "ix_challenges_finding_status",
        "ix_bonds_persona_status",
        "ix_capability_persona",
    ]:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {index_name}"))

    for table_name in [
        "circuit_breaker_incidents",
        "circuit_breaker_rules",
        "evolution_metric_snapshots",
        "scout_source_health",
        "objective_incentive_profiles",
        "civilization_quality_holdbacks",
        "civilization_challenges",
        "civilization_bonds",
        "persona_capability_scores",
    ]:
        if _has_table(sa.inspect(op.get_bind()), table_name):
            op.drop_table(table_name)

    if _has_column("agent_personas", "probation_until"):
        op.drop_column("agent_personas", "probation_until")
    if _has_column("agent_personas", "sponsor_persona_id"):
        op.drop_column("agent_personas", "sponsor_persona_id")


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_if_not_exists(index_name: str, table_name: str, columns_sql: str) -> None:
    op.execute(
        sa.text(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {table_name} ({columns_sql})"
        )
    )
