"""Civilization incentive, resilience, and health tables."""

import sqlalchemy as sa

from nexus_core.models import metadata


persona_capability_scores = sa.Table(
    "persona_capability_scores",
    metadata,
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


civilization_bonds = sa.Table(
    "civilization_bonds",
    metadata,
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


civilization_challenges = sa.Table(
    "civilization_challenges",
    metadata,
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


civilization_quality_holdbacks = sa.Table(
    "civilization_quality_holdbacks",
    metadata,
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


objective_incentive_profiles = sa.Table(
    "objective_incentive_profiles",
    metadata,
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


scout_source_health = sa.Table(
    "scout_source_health",
    metadata,
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


evolution_metric_snapshots = sa.Table(
    "evolution_metric_snapshots",
    metadata,
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


circuit_breaker_rules = sa.Table(
    "circuit_breaker_rules",
    metadata,
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


circuit_breaker_incidents = sa.Table(
    "circuit_breaker_incidents",
    metadata,
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
