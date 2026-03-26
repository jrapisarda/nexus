from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from nexus_api.schemas import ReviewIntelResponse, ReviewOutcomeSummaryResponse
from nexus_api.routers.observatory import (
    build_alerts,
    build_objective_radar,
    build_persona_workload,
    build_review_intel,
)


def _row(**kwargs):
    row = SimpleNamespace(**kwargs)
    row._mapping = kwargs
    return row


def test_build_alerts_prioritizes_critical_conditions():
    now = datetime.now(UTC)
    alerts = build_alerts(
        instance_rows=[
            _row(
                instance_id=uuid4(),
                status="running",
                started_at=now - timedelta(minutes=52),
                persona_name="Scout Vanguard",
                objective_title="Investigate transition pathways",
                error_message=None,
            ),
        ],
        finding_rows=[
            _row(
                finding_id=uuid4(),
                status="pending_review",
                title="Labor displacement signal",
                impact_level="high-impact",
                created_at=now - timedelta(minutes=28),
            ),
        ],
        objective_rows=[
            _row(
                objective_id=uuid4(),
                title="AI unemployment strategy",
                status="revision_requested",
                priority=10,
                created_at=now - timedelta(hours=1),
                escalated_at=None,
            ),
        ],
        total_spend_usd=34.5,
        budget_ceiling_usd=38.25,
        now=now,
    )

    assert alerts[0]["severity"] == "critical"
    assert alerts[0]["category"] in {"budget", "instances", "reviews"}
    assert any(alert["category"] == "objectives" for alert in alerts)


def test_build_persona_workload_prefers_running_assignment():
    now = datetime.now(UTC)
    persona_id = uuid4()
    running_objective = uuid4()
    pending_objective = uuid4()

    items = build_persona_workload(
        persona_rows=[
            _row(
                persona_id=persona_id,
                persona_name="Deep Researcher Alpha",
                role_class="researcher",
                status="active",
            )
        ],
        instance_rows=[
            _row(
                persona_id=persona_id,
                objective_id=pending_objective,
                status="pending",
                started_at=now - timedelta(minutes=15),
                completed_at=None,
            ),
            _row(
                persona_id=persona_id,
                objective_id=running_objective,
                status="running",
                started_at=now - timedelta(minutes=5),
                completed_at=None,
            ),
        ],
        objective_title_map={
            running_objective: "Current live objective",
            pending_objective: "Queued objective",
        },
        telemetry_rows=[
            _row(persona_id=persona_id, cost_total_usd=0.12, latency_ms=4200, success=True),
            _row(persona_id=persona_id, cost_total_usd=0.08, latency_ms=3800, success=False),
        ],
        now=now,
        window_hours=24,
    )

    assert items[0]["current_assignment"] == "Current live objective"
    assert items[0]["running_instances"] == 1
    assert items[0]["pending_instances"] == 1
    assert items[0]["spend_24h"] == 0.2


def test_build_objective_radar_aggregates_subtree_metrics():
    now = datetime.now(UTC)
    root_id = uuid4()
    child_id = uuid4()
    radar = build_objective_radar(
        objective_rows=[
            _row(
                objective_id=root_id,
                parent_objective_id=None,
                title="Root objective",
                status="approved",
                objective_type="strategic",
                impact_level="high-impact",
                priority=9,
                created_at=now - timedelta(hours=2),
                completed_at=None,
            ),
            _row(
                objective_id=child_id,
                parent_objective_id=root_id,
                title="Child objective",
                status="completed",
                objective_type="research",
                impact_level="routine",
                priority=6,
                created_at=now - timedelta(hours=1),
                completed_at=now - timedelta(minutes=10),
            ),
        ],
        instance_rows=[
            _row(
                objective_id=child_id,
                status="running",
                started_at=now - timedelta(minutes=20),
                completed_at=None,
            )
        ],
        finding_rows=[
            _row(objective_id=child_id, status="validated", created_at=now - timedelta(minutes=12)),
            _row(objective_id=child_id, status="pending_review", created_at=now - timedelta(minutes=8)),
        ],
        telemetry_rows=[
            _row(objective_id=child_id, cost_total_usd=0.55, api_call_timestamp=now - timedelta(minutes=7)),
        ],
        now=now,
        limit=6,
    )

    assert radar[0]["objective_id"] == root_id
    assert radar[0]["subtree_objective_count"] == 1
    assert radar[0]["subtree_completed_count"] == 1
    assert radar[0]["validated_findings"] == 1
    assert radar[0]["pending_reviews"] == 1
    assert radar[0]["total_cost_usd"] == 0.55


def test_build_review_intel_summarizes_recent_outcomes():
    finding_id = uuid4()
    reviewed_at = datetime.now(UTC)
    payload = {
        "verdict": "approved",
        "finding_status": "validated",
        "impact_level": "high-impact",
        "review_round": 1,
        "mean_review_confidence": 0.81,
        "approval_count": 2,
        "support_count": 3,
        "reviewer_count": 3,
    }

    summary = build_review_intel(
        review_rows=[
            _row(finding_id=finding_id, verdict="approve", confidence_rating=0.8, created_at=reviewed_at),
            _row(finding_id=finding_id, verdict="revise", confidence_rating=0.82, created_at=reviewed_at),
        ],
        finding_rows=[
            _row(
                finding_id=finding_id,
                title="Validated finding",
                status="validated",
                impact_level="high-impact",
                review_round=1,
            )
        ],
        review_event_rows=[
            _row(entity_id=finding_id, payload=payload, created_at=reviewed_at),
        ],
        finding_map={
            finding_id: _row(
                finding_id=finding_id,
                title="Validated finding",
                status="validated",
                impact_level="high-impact",
                review_round=1,
            )
        },
    )

    assert summary["approval_rate_24h"] == 1.0
    assert summary["outcome_counts"]["approved"] == 1
    assert summary["reviewer_verdict_counts"]["approve"] == 1
    assert summary["recent_outcomes"][0]["support_count"] == 3


def test_review_intel_payload_can_be_materialized_into_schema():
    finding_id = uuid4()
    reviewed_at = datetime.now(UTC)
    payload = build_review_intel(
        review_rows=[
            _row(finding_id=finding_id, verdict="approve", confidence_rating=0.8, created_at=reviewed_at),
        ],
        finding_rows=[
            _row(
                finding_id=finding_id,
                title="Validated finding",
                status="validated",
                impact_level="high-impact",
                review_round=1,
            )
        ],
        review_event_rows=[
            _row(
                entity_id=finding_id,
                payload={
                    "verdict": "approved",
                    "finding_status": "validated",
                    "impact_level": "high-impact",
                    "review_round": 1,
                    "mean_review_confidence": 0.8,
                    "approval_count": 1,
                    "support_count": 1,
                    "reviewer_count": 1,
                },
                created_at=reviewed_at,
            )
        ],
        finding_map={
            finding_id: _row(
                finding_id=finding_id,
                title="Validated finding",
                status="validated",
                impact_level="high-impact",
                review_round=1,
            )
        },
    )
    payload["recent_outcomes"] = [
        ReviewOutcomeSummaryResponse(**item) for item in payload["recent_outcomes"]
    ]

    intel = ReviewIntelResponse(**payload)
    assert intel.recent_outcomes[0].verdict == "approved"
