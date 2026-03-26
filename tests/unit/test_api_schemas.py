"""Unit tests for nexus_api.schemas -- Pydantic v2 response models."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from nexus_api.schemas import (
    ActivityEntryResponse,
    ActivityFeedResponse,
    AlertFeedResponse,
    AlertItemResponse,
    PersonaResponse,
    PersonaListResponse,
    ObjectiveResponse,
    ObjectiveListResponse,
    ObjectiveDAGNode,
    ObjectiveDAGEdge,
    ObjectiveDAGResponse,
    ObjectiveRadarItemResponse,
    ObjectiveRadarResponse,
    ObservatoryOverviewResponse,
    CitationResponse,
    KGNodeResponse,
    KGEdgeResponse,
    KGNodeDetailResponse,
    KGSubgraphResponse,
    KGPathResponse,
    KGPathStepResponse,
    KGEvidenceFindingResponse,
    KGEvidenceRecordResponse,
    KGFindingSearchResultResponse,
    KGObjectiveSearchResultResponse,
    KGWorkbenchOverviewResponse,
    KGWorkbenchObjectiveTouchResponse,
    KGChangeItemResponse,
    KGChangeFeedResponse,
    ReportArtifactSummaryResponse,
    ReportArtifactListResponse,
    ReportFileResponse,
    LinkedObjectiveResponse,
    KGStatsResponse,
    EconomySummaryResponse,
    LedgerEntryResponse,
    PersonaWorkloadItemResponse,
    PersonaWorkloadResponse,
    ReviewIntelResponse,
    ReviewOutcomeSummaryResponse,
    TelemetryCostResponse,
    TelemetryPerformanceResponse,
    EvolutionLineageResponse,
    LineageNode,
    EventMessage,
)


NOW = datetime.now(timezone.utc)
UID = uuid4()
UID2 = uuid4()


class TestPersonaSchemas:
    def test_persona_response_from_dict(self):
        data = {
            "persona_id": UID,
            "persona_name": "Scout-Alpha",
            "role_class": "scout",
            "generation": 0,
            "credit_balance": 100.0,
            "reputation_score": 0.5,
            "compute_budget": 50.0,
            "status": "active",
            "current_assignment": "Map protein-protein interaction pathways",
            "current_assignment_status": "running",
            "current_assignment_started_at": NOW,
            "created_at": NOW,
        }
        p = PersonaResponse(**data)
        assert p.persona_name == "Scout-Alpha"
        assert p.role_class == "scout"
        assert p.credit_balance == 100.0
        assert p.parent_persona_id is None
        assert p.current_assignment_status == "running"

    def test_persona_list_response(self):
        persona = PersonaResponse(
            persona_id=UID,
            persona_name="Test",
            role_class="analyst",
            generation=1,
            credit_balance=50.0,
            reputation_score=0.7,
            compute_budget=30.0,
            status="active",
            created_at=NOW,
        )
        resp = PersonaListResponse(personas=[persona], count=1)
        assert resp.count == 1
        assert len(resp.personas) == 1


class TestObjectiveSchemas:
    def test_objective_response(self):
        data = {
            "objective_id": UID,
            "title": "Investigate CRISPR",
            "description": "Research CRISPR applications",
            "objective_type": "research",
            "priority": 5,
            "status": "proposed",
            "proposed_by_type": "system",
            "created_at": NOW,
        }
        o = ObjectiveResponse(**data)
        assert o.title == "Investigate CRISPR"
        assert o.parent_objective_id is None

    def test_objective_dag_response(self):
        node = ObjectiveDAGNode(
            id=str(UID),
            data={"label": "Root", "status": "proposed", "type": "research", "priority": 5, "color": "#6b7280"},
        )
        edge = ObjectiveDAGEdge(id="e-1", source=str(UID), target=str(UID2))
        dag = ObjectiveDAGResponse(nodes=[node], edges=[edge])
        assert len(dag.nodes) == 1
        assert len(dag.edges) == 1
        assert dag.edges[0].animated is False


class TestKGSchemas:
    def test_kg_node_response(self):
        data = {
            "node_id": UID,
            "node_type": "entity",
            "label": "CRISPR-Cas9",
            "confidence_score": 0.85,
            "validation_count": 3,
            "challenge_count": 1,
            "challenge_failures": 0,
            "status": "validated",
            "first_seen": NOW,
        }
        n = KGNodeResponse(**data)
        assert n.label == "CRISPR-Cas9"
        assert n.confidence_score == 0.85

    def test_kg_edge_response(self):
        data = {
            "edge_id": UID,
            "source_node_id": UID,
            "target_node_id": UID2,
            "relationship_type": "inhibits",
            "weight": 0.7,
            "confidence_score": 0.6,
            "status": "proposed",
            "created_at": NOW,
        }
        e = KGEdgeResponse(**data)
        assert e.relationship_type == "inhibits"

    def test_kg_stats_response(self):
        s = KGStatsResponse(
            node_count=100,
            edge_count=250,
            avg_confidence=0.65,
            validated_count=40,
            proposed_count=50,
            contested_count=10,
            node_type_counts={"entity": 60, "concept": 40},
            relationship_type_counts={"inhibits": 30, "activates": 50},
        )
        assert s.node_count == 100
        assert s.node_type_counts["entity"] == 60

    def test_kg_workbench_response(self):
        overview = KGWorkbenchOverviewResponse(
            node_count=10,
            edge_count=12,
            avg_confidence=0.7,
            challenged_node_count=2,
            challenged_edge_count=1,
            recent_change_count=6,
            report_linked_node_count=5,
            report_linked_edge_count=4,
            top_objectives=[
                KGWorkbenchObjectiveTouchResponse(
                    objective_id=UID,
                    title="Objective",
                    status="completed",
                    node_count=3,
                    edge_count=2,
                )
            ],
        )
        assert overview.top_objectives[0].title == "Objective"

    def test_objective_search_result_response(self):
        result = KGObjectiveSearchResultResponse(
            objective_id=UID,
            title="Red Queen Dynamics",
            status="active",
            objective_type="research",
            impact_level="high-impact",
        )
        assert result.title == "Red Queen Dynamics"
        assert result.impact_level == "high-impact"

    def test_finding_search_result_response(self):
        result = KGFindingSearchResultResponse(
            finding_id=UID2,
            title="Red Queen pressure shapes adaptation",
            objective_id=UID,
            objective_title="Civilization resilience",
            status="validated",
            impact_level="routine",
        )
        assert result.objective_title == "Civilization resilience"
        assert result.status == "validated"

    def test_node_detail_response(self):
        detail = KGNodeDetailResponse(
            node=KGNodeResponse(
                node_id=UID,
                node_type="concept",
                label="Automation Risk",
                confidence_score=0.75,
                validation_count=1,
                challenge_count=0,
                challenge_failures=0,
                status="validated",
                first_seen=NOW,
            ),
            adjacent_edges=[],
            linked_findings=[
                KGEvidenceFindingResponse(
                    finding_id=UID2,
                    objective_id=UID,
                    objective_title="Objective",
                    title="Finding",
                    finding_type="research",
                    status="validated",
                    impact_level="routine",
                    review_round=1,
                    created_at=NOW,
                    kg_node_refs=[],
                    kg_edge_refs=[],
                    citations=[],
                )
            ],
            linked_objectives=[],
            linked_reports=[],
            linked_citations=[],
            relationship_groups={"supports": ["Worker Transition"]},
            timeline=[],
        )
        assert detail.relationship_groups["supports"][0] == "Worker Transition"


class TestEconomySchemas:
    def test_economy_summary(self):
        s = EconomySummaryResponse(
            total_personas=10,
            total_credits_minted=1000.0,
            total_rent_collected=50.0,
            net_credits_in_system=950.0,
            gini_coefficient=0.3,
            top_balance=200.0,
            bottom_balance=20.0,
            mean_balance=95.0,
        )
        assert s.gini_coefficient == 0.3

    def test_ledger_entry(self):
        entry = LedgerEntryResponse(
            transaction_id=UID,
            to_persona_id=UID2,
            amount=25.0,
            transaction_type="bounty_claim",
            created_at=NOW,
        )
        assert entry.amount == 25.0
        assert entry.from_persona_id is None


class TestTelemetrySchemas:
    def test_cost_response(self):
        c = TelemetryCostResponse(
            total_spend_usd=5.23,
            per_agent=[{"persona_id": str(UID), "persona_name": "Scout-A", "total_cost": 3.0, "call_count": 10}],
            per_objective=[{"objective_id": str(UID), "objective_title": "Test", "total_cost": 5.23, "call_count": 15}],
            budget_ceiling_usd=38.25,
            budget_remaining_usd=33.02,
        )
        assert c.budget_remaining_usd == 33.02
        assert len(c.per_agent) == 1

    def test_performance_response(self):
        p = TelemetryPerformanceResponse(
            total_calls=100,
            success_rate=0.95,
            avg_latency_ms=1234.5,
            error_breakdown={"rate_limit": 3, "timeout": 2},
        )
        assert p.success_rate == 0.95


class TestEvolutionSchemas:
    def test_lineage_node(self):
        n = LineageNode(
            persona_id=UID,
            persona_name="Scout-Alpha",
            role_class="scout",
            generation=0,
            status="active",
            credit_balance=100.0,
        )
        assert n.parent_persona_id is None

    def test_evolution_lineage_response(self):
        n1 = LineageNode(
            persona_id=UID,
            persona_name="Parent",
            role_class="scout",
            generation=0,
            status="active",
            credit_balance=100.0,
        )
        n2 = LineageNode(
            persona_id=UID2,
            persona_name="Child",
            role_class="scout",
            generation=1,
            status="active",
            parent_persona_id=UID,
            credit_balance=80.0,
        )
        resp = EvolutionLineageResponse(nodes=[n1, n2])
        assert len(resp.nodes) == 2
        assert resp.nodes[1].parent_persona_id == UID


class TestActivitySchemas:
    def test_activity_entry_response(self):
        entry = ActivityEntryResponse(
            event_id=UID,
            event_type="agent_spawned",
            entity_id=UID2,
            entity_type="instance",
            title="Agent Started",
            summary="Scout-Alpha started the objective.",
            severity="info",
            payload={"persona": "Scout-Alpha"},
            created_at=NOW,
        )
        assert entry.event_type == "agent_spawned"
        assert entry.severity == "info"

    def test_activity_feed_response(self):
        entry = ActivityEntryResponse(
            event_id=UID,
            event_type="objective_completed",
            title="Objective Completed",
            summary="Objective completed.",
            severity="success",
            payload={},
            created_at=NOW,
        )
        feed = ActivityFeedResponse(
            entries=[entry],
            count=1,
            active_instance_count=2,
            window_minutes=15,
        )
        assert feed.count == 1
        assert feed.active_instance_count == 2
        assert feed.window_minutes == 15


class TestObservatorySchemas:
    def test_overview_response(self):
        overview = ObservatoryOverviewResponse(
            active_personas=12,
            active_objectives=4,
            running_instances=3,
            pending_reviews=2,
            escalated_objectives=1,
            objectives_completed_24h=5,
            findings_validated_24h=7,
            mean_review_confidence_24h=0.78,
            total_spend_usd=1.25,
            budget_remaining_usd=37.0,
            budget_utilization_pct=3.26,
            success_rate_24h=0.97,
            total_calls_24h=42,
        )
        assert overview.active_personas == 12
        assert overview.total_calls_24h == 42

    def test_alert_feed_response(self):
        alert = AlertItemResponse(
            alert_id="budget-warning",
            severity="warning",
            category="budget",
            title="Budget burn elevated",
            summary="Spend is rising quickly.",
            metric_label="Budget %",
            metric_value=82.3,
            detected_at=NOW,
        )
        feed = AlertFeedResponse(alerts=[alert], count=1)
        assert feed.count == 1
        assert feed.alerts[0].severity == "warning"

    def test_review_intel_response(self):
        outcome = ReviewOutcomeSummaryResponse(
            finding_id=UID,
            title="Validated finding",
            status="validated",
            impact_level="high-impact",
            review_round=1,
            mean_confidence=0.81,
            approval_count=2,
            support_count=3,
            reviewer_count=3,
            verdict="approved",
            reviewed_at=NOW,
        )
        intel = ReviewIntelResponse(
            total_reviews_24h=6,
            finding_outcomes_24h=2,
            mean_review_confidence_24h=0.74,
            approval_rate_24h=0.5,
            outcome_counts={"approved": 1, "rejected": 1},
            reviewer_verdict_counts={"approve": 3, "revise": 2, "reject": 1},
            finding_status_counts={"validated": 4, "pending_review": 2},
            high_impact_pending_count=1,
            recent_outcomes=[outcome],
        )
        assert intel.recent_outcomes[0].support_count == 3

    def test_workload_and_objective_radar_response(self):
        workload = PersonaWorkloadResponse(
            items=[
                PersonaWorkloadItemResponse(
                    persona_id=UID,
                    persona_name="Deep Researcher Alpha",
                    role_class="researcher",
                    status="active",
                    current_assignment="Current objective",
                    current_assignment_status="running",
                    running_instances=1,
                    pending_instances=0,
                    completed_24h=3,
                    failed_24h=0,
                    avg_latency_ms_24h=4200.0,
                    success_rate_24h=1.0,
                    spend_24h=0.44,
                )
            ],
            count=1,
            window_hours=24,
        )
        radar = ObjectiveRadarResponse(
            items=[
                ObjectiveRadarItemResponse(
                    objective_id=UID2,
                    title="Root objective",
                    status="approved",
                    objective_type="strategic",
                    impact_level="high-impact",
                    priority=9,
                    active_instances=2,
                    completed_instances=1,
                    findings_total=4,
                    validated_findings=2,
                    pending_reviews=1,
                    subtree_objective_count=3,
                    subtree_completed_count=1,
                    progress_pct=33.3,
                    total_cost_usd=0.92,
                    age_minutes=120,
                    last_activity_at=NOW,
                    attention_score=19.5,
                )
            ],
            count=1,
        )
        assert workload.items[0].persona_name == "Deep Researcher Alpha"
        assert radar.items[0].priority == 9


class TestEventMessage:
    def test_event_message(self):
        msg = EventMessage(
            type="objective.created",
            data={"objective_id": str(UID), "title": "Test"},
            timestamp=NOW.isoformat(),
        )
        assert msg.type == "objective.created"
        assert "objective_id" in msg.data


class TestReportSchemas:
    def test_report_artifact_summary(self):
        artifact = ReportArtifactSummaryResponse(
            title="Recommendation Report",
            slug="questions/test/recommendation-report.md",
            artifact_type="recommendation_report",
            objective_id=UID,
            finding_id=None,
            version="primary",
            updated_at=NOW,
            size_bytes=512,
        )
        listing = ReportArtifactListResponse(items=[artifact], count=1)
        assert listing.items[0].slug.endswith("recommendation-report.md")

    def test_report_file_response(self):
        report = ReportFileResponse(
            slug="questions/test/recommendation-report.md",
            title="Recommendation Report",
            artifact_type="recommendation_report",
            updated_at=NOW,
            size_bytes=1024,
            content="# Recommendation Report",
        )
        assert "Recommendation Report" in report.content
