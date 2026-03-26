"""Pydantic v2 response models for the NEXUS observatory API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ── Personas ──────────────────────────────────────────────────────────────

class PersonaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    persona_id: UUID
    persona_name: str
    role_class: str
    system_prompt_template: str | None = None
    tool_permissions: list[Any] | None = None
    reasoning_strategy: str | None = None
    model_config_json: dict[str, Any] | None = None
    autonomy_level: int | None = None
    parent_persona_id: UUID | None = None
    sponsor_persona_id: UUID | None = None
    generation: int
    credit_balance: float
    reputation_score: float
    compute_budget: float
    status: str
    probation_until: datetime | None = None
    capability_scores: dict[str, float] | None = None
    current_assignment: str | None = None
    current_assignment_status: str | None = None
    current_assignment_started_at: datetime | None = None
    current_assignment_reason: str | None = None
    mutation_diff: dict[str, Any] | None = None
    created_at: datetime
    deprecated_at: datetime | None = None
    deprecation_reason: str | None = None


class PersonaListResponse(BaseModel):
    personas: list[PersonaResponse]
    count: int


# ── Objectives ────────────────────────────────────────────────────────────

class ObjectiveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    objective_id: UUID
    parent_objective_id: UUID | None = None
    title: str
    description: str
    objective_type: str
    impact_level: str | None = None
    priority: int
    status: str
    proposed_by_type: str
    proposed_by_id: UUID | None = None
    approved_by_type: str | None = None
    approved_by_id: UUID | None = None
    assigned_to: UUID | None = None
    acceptance_criteria: str | None = None
    knowledge_graph_anchor: list[Any] | None = None
    compute_budget_allocated: float | None = None
    output_type: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    escalated_at: datetime | None = None
    escalation_reason: str | None = None
    file_attachment_ids: list[Any] | None = None


class ObjectiveListResponse(BaseModel):
    objectives: list[ObjectiveResponse]
    count: int


class ObjectiveDAGNode(BaseModel):
    id: str
    data: dict[str, Any]
    position: dict[str, float] = {"x": 0, "y": 0}
    type: str = "default"


class ObjectiveDAGEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str | None = None
    animated: bool = False


class ObjectiveDAGResponse(BaseModel):
    nodes: list[ObjectiveDAGNode]
    edges: list[ObjectiveDAGEdge]


# ── Knowledge Graph ───────────────────────────────────────────────────────

class KGNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: UUID
    node_type: str
    label: str
    properties: dict[str, Any] | None = None
    confidence_score: float
    discovered_by_objective_id: UUID | None = None
    discovered_by_instance_id: UUID | None = None
    validation_count: int
    challenge_count: int
    challenge_failures: int
    status: str
    first_seen: datetime
    last_validated: datetime | None = None


class KGEdgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    edge_id: UUID
    source_node_id: UUID
    target_node_id: UUID
    relationship_type: str
    weight: float
    confidence_score: float
    evidence_ids: list[Any] | None = None
    discovered_by_objective_id: UUID | None = None
    challenged_by_objective_ids: list[Any] | None = None
    status: str
    properties: dict[str, Any] | None = None
    created_at: datetime


class KGStatsResponse(BaseModel):
    node_count: int
    edge_count: int
    avg_confidence: float
    validated_count: int
    proposed_count: int
    contested_count: int
    node_type_counts: dict[str, int]
    relationship_type_counts: dict[str, int]


class CitationResponse(BaseModel):
    title: str
    source_type: str = ""
    source_name: str = ""
    url: str = ""
    doi: str = ""
    published_date: str = ""
    authors: list[str] = []
    supporting_snippet: str = ""
    source_finding_id: UUID | None = None
    derived: bool = False


class KGNodeReferenceResponse(BaseModel):
    node_id: UUID
    label: str
    node_type: str
    status: str
    confidence_score: float


class KGEdgeReferenceResponse(BaseModel):
    edge_id: UUID
    source_label: str
    target_label: str
    relationship_type: str
    status: str
    confidence_score: float
    weight: float


class LinkedObjectiveResponse(BaseModel):
    objective_id: UUID
    title: str
    status: str
    objective_type: str
    impact_level: str | None = None


class KGObjectiveSearchResultResponse(BaseModel):
    objective_id: UUID
    title: str
    status: str
    objective_type: str
    impact_level: str | None = None


class KGFindingSearchResultResponse(BaseModel):
    finding_id: UUID
    title: str
    objective_id: UUID
    objective_title: str
    status: str
    impact_level: str


class ReportArtifactSummaryResponse(BaseModel):
    title: str
    slug: str
    artifact_type: str
    objective_id: UUID
    finding_id: UUID | None = None
    version: str
    updated_at: datetime
    size_bytes: int


class ReportArtifactListResponse(BaseModel):
    items: list[ReportArtifactSummaryResponse]
    count: int


class ReportFileResponse(BaseModel):
    slug: str
    title: str
    artifact_type: str
    updated_at: datetime
    size_bytes: int
    content: str


class KGEvidenceFindingResponse(BaseModel):
    finding_id: UUID
    objective_id: UUID
    objective_title: str
    title: str
    finding_type: str
    status: str
    impact_level: str
    review_round: int
    created_at: datetime
    kg_node_refs: list[str]
    kg_edge_refs: list[str]
    citations: list[CitationResponse]


class KGWorkbenchObjectiveTouchResponse(BaseModel):
    objective_id: UUID
    title: str
    status: str
    node_count: int
    edge_count: int


class KGWorkbenchOverviewResponse(BaseModel):
    node_count: int
    edge_count: int
    avg_confidence: float
    challenged_node_count: int
    challenged_edge_count: int
    recent_change_count: int
    report_linked_node_count: int
    report_linked_edge_count: int
    top_objectives: list[KGWorkbenchObjectiveTouchResponse]


class KGSubgraphResponse(BaseModel):
    center_node_id: UUID | None = None
    scope_label: str | None = None
    nodes: list[KGNodeResponse]
    edges: list[KGEdgeResponse]


class KGPathStepResponse(BaseModel):
    node_id: UUID
    label: str
    node_type: str
    confidence: float
    depth: int
    edge_type: str | None = None
    edge_weight: float | None = None
    supporting_finding_ids: list[UUID] = []


class KGPathResponse(BaseModel):
    start_node_id: UUID
    end_node_id: UUID
    found: bool
    steps: list[KGPathStepResponse]
    evidence: list[KGEvidenceFindingResponse]


class KGEvidenceRecordResponse(BaseModel):
    query_type: str
    findings: list[KGEvidenceFindingResponse]
    reports: list[ReportArtifactSummaryResponse]
    citations: list[CitationResponse]
    linked_objectives: list[LinkedObjectiveResponse]
    challenged_count: int


class KGChangeItemResponse(BaseModel):
    event_id: UUID
    event_type: str
    entity_id: UUID | None = None
    entity_type: str | None = None
    title: str
    summary: str
    payload: dict[str, Any]
    created_at: datetime


class KGChangeFeedResponse(BaseModel):
    items: list[KGChangeItemResponse]
    count: int
    window_hours: int


class KGNodeDetailResponse(BaseModel):
    node: KGNodeResponse
    adjacent_edges: list[KGEdgeResponse]
    linked_findings: list[KGEvidenceFindingResponse]
    linked_objectives: list[LinkedObjectiveResponse]
    linked_reports: list[ReportArtifactSummaryResponse]
    linked_citations: list[CitationResponse]
    relationship_groups: dict[str, list[str]]
    timeline: list[KGChangeItemResponse]


# ── Economy ───────────────────────────────────────────────────────────────

class EconomySummaryResponse(BaseModel):
    total_personas: int
    total_credits_minted: float
    total_rent_collected: float
    net_credits_in_system: float
    gini_coefficient: float
    top_balance: float
    bottom_balance: float
    mean_balance: float


class LedgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    from_persona_id: UUID | None = None
    to_persona_id: UUID | None = None
    amount: float
    transaction_type: str
    reference_objective_id: UUID | None = None
    reference_finding_id: UUID | None = None
    memo: str | None = None
    created_at: datetime


class MarketParticipantResponse(BaseModel):
    persona_id: str
    persona_name: str | None = None
    role_class: str | None = None


class MarketOverviewResponse(BaseModel):
    active_listings: int
    pending_contracts: int
    fulfilled_contracts_24h: int
    total_listing_value: float
    category_breakdown: dict[str, int]
    top_seller_ids: list[str]
    top_buyer_ids: list[str]


class MarketplaceListingResponse(BaseModel):
    listing_id: UUID
    listing_kind: str
    price: float
    quantity_available: int
    status: str
    description: str
    metadata: dict[str, Any]
    created_at: datetime
    seller_persona_id: UUID
    seller_name: str
    seller_role_class: str
    template_code: str
    template_title: str


class ServiceContractResponse(BaseModel):
    contract_id: UUID
    status: str
    agreed_price: float
    quantity: int
    created_at: datetime
    fulfilled_at: datetime | None = None
    refunded_at: datetime | None = None
    target_objective_id: UUID | None = None
    target_finding_id: UUID | None = None
    service_objective_id: UUID | None = None
    fulfillment_summary: str | None = None
    template_code: str
    template_title: str
    buyer_persona_id: UUID
    buyer_name: str
    seller_persona_id: UUID
    seller_name: str


class MarketActivityItemResponse(BaseModel):
    event_id: UUID
    event_type: str
    entity_id: UUID | None = None
    entity_type: str | None = None
    payload: dict[str, Any]
    created_at: datetime


class MarketActivityResponse(BaseModel):
    items: list[MarketActivityItemResponse]
    count: int


class SecuritiesOverviewResponse(BaseModel):
    instrument_count: int
    open_order_count: int
    trade_volume: float
    halted_count: int
    settlement_backlog: int


class MarketInstrumentResponse(BaseModel):
    instrument_id: UUID
    symbol: str
    name: str
    family: str
    risk_tier: str
    halted: bool
    settlement_status: str
    settlement_value: float | None = None
    last_trade_price: float
    mark_price: float
    expiry_at: datetime | None = None
    settlement_at: datetime | None = None
    metadata: dict[str, Any]
    underlying_objective_id: UUID | None = None
    underlying_finding_id: UUID | None = None
    underlying_persona_id: UUID | None = None


class OrderBookLevelResponse(BaseModel):
    order_id: UUID
    price: float
    remaining_quantity: float
    persona_name: str


class OrderBookResponse(BaseModel):
    instrument_id: UUID | None = None
    instrument_symbol: str | None = None
    bids: list[OrderBookLevelResponse]
    asks: list[OrderBookLevelResponse]


class TradeResponse(BaseModel):
    trade_id: UUID
    instrument_id: UUID
    instrument_symbol: str
    price: float
    quantity: float
    notional: float
    created_at: datetime
    buyer_name: str
    seller_name: str


class PositionResponse(BaseModel):
    position_id: UUID
    instrument_id: UUID
    instrument_symbol: str
    persona_id: UUID
    persona_name: str
    role_class: str
    net_quantity: float
    average_entry_price: float
    realized_pnl: float
    market_value: float
    updated_at: datetime


# ── Telemetry ─────────────────────────────────────────────────────────────

class TelemetryCostResponse(BaseModel):
    total_spend_usd: float
    per_agent: list[dict[str, Any]]
    per_objective: list[dict[str, Any]]
    budget_ceiling_usd: float
    budget_remaining_usd: float


class TelemetryPerformanceResponse(BaseModel):
    total_calls: int
    success_rate: float
    avg_latency_ms: float
    error_breakdown: dict[str, int]


# ── Evolution ─────────────────────────────────────────────────────────────

class LineageNode(BaseModel):
    persona_id: UUID
    persona_name: str
    role_class: str
    generation: int
    status: str
    parent_persona_id: UUID | None = None
    credit_balance: float


class EvolutionLineageResponse(BaseModel):
    nodes: list[LineageNode]


class ObservatoryOverviewResponse(BaseModel):
    active_personas: int
    active_objectives: int
    running_instances: int
    pending_reviews: int
    escalated_objectives: int
    objectives_completed_24h: int
    findings_validated_24h: int
    mean_review_confidence_24h: float
    total_spend_usd: float
    budget_remaining_usd: float
    budget_utilization_pct: float
    success_rate_24h: float
    total_calls_24h: int


class AlertItemResponse(BaseModel):
    alert_id: str
    severity: str
    category: str
    title: str
    summary: str
    metric_label: str | None = None
    metric_value: float | int | None = None
    entity_id: UUID | None = None
    entity_type: str | None = None
    detected_at: datetime


class AlertFeedResponse(BaseModel):
    alerts: list[AlertItemResponse]
    count: int


class ReviewOutcomeSummaryResponse(BaseModel):
    finding_id: UUID
    title: str
    status: str
    impact_level: str
    review_round: int
    mean_confidence: float
    approval_count: int
    support_count: int
    reviewer_count: int
    verdict: str
    reviewed_at: datetime


class ReviewIntelResponse(BaseModel):
    total_reviews_24h: int
    finding_outcomes_24h: int
    mean_review_confidence_24h: float
    approval_rate_24h: float
    outcome_counts: dict[str, int]
    reviewer_verdict_counts: dict[str, int]
    finding_status_counts: dict[str, int]
    high_impact_pending_count: int
    recent_outcomes: list[ReviewOutcomeSummaryResponse]


class PersonaWorkloadItemResponse(BaseModel):
    persona_id: UUID
    persona_name: str
    role_class: str
    status: str
    current_assignment: str | None = None
    current_assignment_status: str | None = None
    running_instances: int
    pending_instances: int
    completed_24h: int
    failed_24h: int
    avg_latency_ms_24h: float
    success_rate_24h: float
    spend_24h: float


class PersonaWorkloadResponse(BaseModel):
    items: list[PersonaWorkloadItemResponse]
    count: int
    window_hours: int


class ObjectiveRadarItemResponse(BaseModel):
    objective_id: UUID
    title: str
    status: str
    objective_type: str
    impact_level: str | None = None
    priority: int
    active_instances: int
    completed_instances: int
    findings_total: int
    validated_findings: int
    pending_reviews: int
    subtree_objective_count: int
    subtree_completed_count: int
    progress_pct: float
    total_cost_usd: float
    age_minutes: int
    last_activity_at: datetime
    attention_score: float


class ObjectiveRadarResponse(BaseModel):
    items: list[ObjectiveRadarItemResponse]
    count: int


# ── WebSocket ─────────────────────────────────────────────────────────────

class CivilizationOverviewResponse(BaseModel):
    wealth_gini: float
    top_balance_share: float
    role_concentration: float
    pending_challenges: int
    pending_holdbacks: int
    slow_science_objectives: int
    degraded_scout_sources: int
    open_breaker_incidents: int


class CivilizationCapabilityPersonaResponse(BaseModel):
    persona_id: UUID
    persona_name: str
    role_class: str
    reputation_score: float
    credit_balance: float
    capability_scores: dict[str, float]


class CivilizationCapabilityResponse(BaseModel):
    items: list[CivilizationCapabilityPersonaResponse]
    count: int


class CivilizationChallengeResponse(BaseModel):
    challenge_id: UUID
    finding_id: UUID
    finding_title: str
    challenger_persona_id: UUID
    challenger_name: str
    flaw_type: str | None = None
    severity: str | None = None
    status: str
    summary: str | None = None
    opened_at: datetime
    resolution_due_at: datetime | None = None
    resolved_at: datetime | None = None


class CivilizationChallengeListResponse(BaseModel):
    items: list[CivilizationChallengeResponse]
    count: int


class ScoutSourceHealthResponse(BaseModel):
    source_name: str
    health_status: str
    consecutive_failures: int
    total_runs: int
    total_successes: int
    findings_ingested: int
    objectives_proposed: int
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None


class ScoutSourceHealthListResponse(BaseModel):
    items: list[ScoutSourceHealthResponse]
    count: int


class EvolutionHealthResponse(BaseModel):
    snapshot_id: UUID | None = None
    concentration_score: float
    role_diversity_score: float
    novelty_score: float
    stagnation_score: float
    explorer_pressure_score: float
    exploration_pulse_triggered: bool
    created_at: datetime | None = None
    metrics_json: dict[str, Any]


class BreakerRuleResponse(BaseModel):
    rule_id: UUID
    rule_code: str
    description: str
    mode: str
    threshold_value: float
    window_minutes: int
    action_type: str
    enabled: bool
    shadow_only: bool


class BreakerIncidentResponse(BaseModel):
    incident_id: UUID
    rule_code: str
    mode: str
    severity: str
    status: str
    observed_value: float
    threshold_value: float
    payload: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None = None


class BreakerStatusResponse(BaseModel):
    rules: list[BreakerRuleResponse]
    incidents: list[BreakerIncidentResponse]
    open_count: int


class ActivityEntryResponse(BaseModel):
    event_id: UUID
    event_type: str
    entity_id: UUID | None = None
    entity_type: str | None = None
    title: str
    summary: str
    severity: str
    payload: dict[str, Any]
    created_at: datetime


class ActivityFeedResponse(BaseModel):
    entries: list[ActivityEntryResponse]
    count: int
    active_instance_count: int
    window_minutes: int


class EventMessage(BaseModel):
    type: str
    data: dict[str, Any]
    timestamp: str


# ── File Uploads ─────────────────────────────────────────────────────────


class FileUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attachment_id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    upload_status: str
    created_at: datetime


class ObjectiveCreateRequest(BaseModel):
    title: str
    description: str
    objective_type: str = "strategic"
    priority: int = 5
    attachment_ids: list[UUID] = []
