"""Recent system activity endpoints for the NEXUS Observatory API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Query

from nexus_core.database import get_connection
from nexus_core.models.events import events
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.knowledge_graph import knowledge_graph_nodes
from nexus_core.models.objectives import objectives
from nexus_core.models.personas import agent_personas

from nexus_api.schemas import ActivityEntryResponse, ActivityFeedResponse

router = APIRouter(prefix="/api/activity", tags=["activity"])


def _humanize_event_type(event_type: str) -> str:
    return event_type.replace("_", " ").strip().title()


def _severity_for_event(event_type: str, payload: dict[str, Any]) -> str:
    if "liquidated" in event_type:
        return "error"
    if "halted" in event_type:
        return "warning"
    if "failed" in event_type or "debugger" in event_type:
        return "error"
    if "escalated" in event_type or payload.get("verdict") == "rejected":
        return "warning"
    if any(
        marker in event_type
        for marker in ("completed", "approved", "validated", "mint", "distributed", "synthesized")
    ):
        return "success"
    return "info"


async def _load_context_maps(conn, event_rows) -> dict[str, dict[UUID, dict[str, Any]]]:
    instance_ids = {
        row.entity_id
        for row in event_rows
        if row.entity_type == "instance" and row.entity_id is not None
    }
    objective_ids = {
        row.entity_id
        for row in event_rows
        if row.entity_type == "objective" and row.entity_id is not None
    }
    finding_ids = {
        row.entity_id
        for row in event_rows
        if row.entity_type == "finding" and row.entity_id is not None
    }
    kg_node_ids = {
        row.entity_id
        for row in event_rows
        if row.entity_type == "kg_node" and row.entity_id is not None
    }
    persona_ids = {
        row.entity_id
        for row in event_rows
        if row.entity_type == "persona" and row.entity_id is not None
    }

    instance_map: dict[UUID, dict[str, Any]] = {}
    if instance_ids:
        rows = await conn.execute(
            sa.select(
                agent_instances.c.instance_id,
                agent_instances.c.status,
                agent_instances.c.started_at,
                agent_instances.c.completed_at,
                agent_instances.c.spawn_reason,
                agent_personas.c.persona_name,
                objectives.c.title.label("objective_title"),
            )
            .join(agent_personas, agent_instances.c.persona_id == agent_personas.c.persona_id)
            .join(objectives, agent_instances.c.objective_id == objectives.c.objective_id)
            .where(agent_instances.c.instance_id.in_(instance_ids))
        )
        instance_map = {
            row.instance_id: dict(row._mapping)
            for row in rows
        }

    objective_map: dict[UUID, dict[str, Any]] = {}
    if objective_ids:
        rows = await conn.execute(
            sa.select(
                objectives.c.objective_id,
                objectives.c.title,
                objectives.c.status,
                objectives.c.objective_type,
            ).where(objectives.c.objective_id.in_(objective_ids))
        )
        objective_map = {
            row.objective_id: dict(row._mapping)
            for row in rows
        }

    finding_map: dict[UUID, dict[str, Any]] = {}
    if finding_ids:
        rows = await conn.execute(
            sa.select(
                findings.c.finding_id,
                findings.c.title,
                findings.c.status,
                findings.c.finding_type,
            ).where(findings.c.finding_id.in_(finding_ids))
        )
        finding_map = {
            row.finding_id: dict(row._mapping)
            for row in rows
        }

    kg_node_map: dict[UUID, dict[str, Any]] = {}
    if kg_node_ids:
        rows = await conn.execute(
            sa.select(
                knowledge_graph_nodes.c.node_id,
                knowledge_graph_nodes.c.label,
                knowledge_graph_nodes.c.node_type,
                knowledge_graph_nodes.c.status,
            ).where(knowledge_graph_nodes.c.node_id.in_(kg_node_ids))
        )
        kg_node_map = {
            row.node_id: dict(row._mapping)
            for row in rows
        }

    persona_map: dict[UUID, dict[str, Any]] = {}
    if persona_ids:
        rows = await conn.execute(
            sa.select(
                agent_personas.c.persona_id,
                agent_personas.c.persona_name,
                agent_personas.c.role_class,
                agent_personas.c.status,
            ).where(agent_personas.c.persona_id.in_(persona_ids))
        )
        persona_map = {
            row.persona_id: dict(row._mapping)
            for row in rows
        }

    return {
        "instances": instance_map,
        "objectives": objective_map,
        "findings": finding_map,
        "kg_nodes": kg_node_map,
        "personas": persona_map,
    }


def _summarize_event(row, context: dict[str, dict[UUID, dict[str, Any]]]) -> tuple[str, str]:
    payload = dict(row.payload or {})
    event_type = row.event_type
    instance = context["instances"].get(row.entity_id) if row.entity_type == "instance" else None
    objective = context["objectives"].get(row.entity_id) if row.entity_type == "objective" else None
    finding = context["findings"].get(row.entity_id) if row.entity_type == "finding" else None
    kg_node = context["kg_nodes"].get(row.entity_id) if row.entity_type == "kg_node" else None
    persona = context["personas"].get(row.entity_id) if row.entity_type == "persona" else None

    if event_type == "agent_spawned":
        persona_name = payload.get("persona") or (instance or {}).get("persona_name") or "Agent"
        objective_title = payload.get("objective") or (instance or {}).get("objective_title") or "objective"
        return "Agent Started", f"{persona_name} started {objective_title}."

    if event_type == "agent_completed":
        persona_name = payload.get("persona") or (instance or {}).get("persona_name") or "Agent"
        objective_title = payload.get("objective") or (instance or {}).get("objective_title") or "objective"
        return "Agent Completed", f"{persona_name} completed {objective_title}."

    if event_type == "objective_approved":
        return "Objective Approved", f"Objective approved: {(objective or {}).get('title', 'Untitled objective')}."

    if event_type == "objective_completed":
        return "Objective Completed", f"Objective completed: {(objective or {}).get('title', 'Untitled objective')}."

    if event_type == "objective_revision_requested":
        return "Revision Requested", (
            f"Peer review requested another pass on {(objective or {}).get('title', 'the objective')}."
        )

    if event_type == "objective_synthesized":
        count = payload.get("source_finding_count")
        suffix = f" using {count} validated findings." if count else "."
        return "Final Synthesis", (
            f"Final synthesis completed for {(objective or {}).get('title', 'the objective')}{suffix}"
        )

    if event_type == "finding_reviewed":
        verdict = str(payload.get("verdict", "reviewed")).replace("_", " ")
        title = (finding or {}).get("title", "finding")
        approval_count = payload.get("approval_count")
        support_count = payload.get("support_count")
        reviewer_count = payload.get("reviewer_count", payload.get("review_count"))
        confidence = payload.get("mean_review_confidence", payload.get("consensus_score"))
        impact_level = payload.get("impact_level")
        required_consensus = payload.get("required_consensus")

        metrics: list[str] = []
        if support_count is not None and reviewer_count is not None:
            metrics.append(f"{support_count}/{reviewer_count} support")
        if approval_count is not None and reviewer_count is not None:
            metrics.append(f"{approval_count}/{reviewer_count} approve")
        if confidence is not None:
            metrics.append(f"mean confidence {float(confidence):.3f}")
        if impact_level:
            metrics.append(str(impact_level))
        if required_consensus:
            metrics.append(f"needs {required_consensus}")

        suffix = f" ({' | '.join(metrics)})" if metrics else ""
        return "Finding Reviewed", f"{title} was {verdict}{suffix}."

    if event_type == "review_escalated":
        reason = payload.get("reason", "manual escalation required")
        title = (finding or {}).get("title", "finding")
        return "Review Escalated", f"{title} escalated: {reason}."

    if event_type == "kg_node_created":
        label = payload.get("label") or (kg_node or {}).get("label") or "knowledge node"
        return "Knowledge Added", f"Knowledge graph node created: {label}."

    if event_type == "kg_edge_created":
        relation = payload.get("type", "relationship")
        return "Knowledge Linked", f"Knowledge graph edge added: {relation}."

    if event_type == "kg_node_status_changed":
        label = (kg_node or {}).get("label", payload.get("label", "knowledge node"))
        return "Knowledge Updated", f"{label} marked {payload.get('new_status', 'updated')}."

    if event_type == "economy_mint":
        amount = payload.get("amount", "0")
        target = (persona or {}).get("persona_name", "persona")
        return "Credits Minted", f"{amount} credits minted to {target}."

    if event_type == "bounty_distributed":
        total = payload.get("total", "0")
        payouts = payload.get("transactions", 0)
        return "Bounty Distributed", f"{total} credits distributed across {payouts} payouts."

    if event_type == "rent_decay_applied":
        affected = payload.get("personas_affected", 0)
        return "Rent Decay Applied", f"Periodic rent decay applied to {affected} personas."

    if event_type == "bond_locked":
        amount = payload.get("amount", "0")
        bond_type = payload.get("bond_type", "bond")
        return "Bond Locked", f"{bond_type} locked at {amount} credits."

    if event_type == "bond_released":
        amount = payload.get("amount", "0")
        bond_type = payload.get("bond_type", "bond")
        return "Bond Released", f"{bond_type} released at {amount} credits."

    if event_type == "bond_slashed":
        amount = payload.get("slashed_amount", "0")
        return "Bond Slashed", f"Quality reserve slashed by {amount} credits."

    if event_type == "finding_challenged":
        return "Finding Challenged", "A validated finding entered the bonded challenge window."

    if event_type == "appeal_opened":
        return "Appeal Window", "A challenge case opened for delayed resolution."

    if event_type == "contrarian_reward_paid":
        amount = payload.get("amount", "0")
        return "Contrarian Reward", f"A dissenting reviewer earned {amount} credits after vindication."

    if event_type == "slow_objective_registered":
        return "Slow Science", "An objective entered the slow-science lane with lighter rent pressure."

    if event_type == "exploration_pulse_triggered":
        return "Exploration Pulse", "Evolution triggered a diversity pulse to counter convergence."

    if event_type == "scout_coverage_gap":
        source = payload.get("source_name", "scout coverage")
        return "Scout Coverage Gap", f"{source} reported degraded scout coverage."

    if event_type == "circuit_breaker_triggered":
        rule = payload.get("rule_code", "breaker")
        severity = payload.get("severity", "warning")
        return "Circuit Breaker", f"{rule} triggered in {severity} shadow mode."

    if event_type == "candidate_persona_proposed":
        target = (persona or {}).get("persona_name") or payload.get("persona_name", "candidate persona")
        return "Persona Proposed", f"Candidate persona proposed: {target}."

    if event_type == "market_listing_created":
        seller_name = payload.get("seller_name", "An agent")
        template_code = payload.get("template_code", "listing")
        price = payload.get("price", "0")
        return "Market Listing", f"{seller_name} listed {template_code} for {price} credits."

    if event_type == "market_asset_crafted":
        template_code = payload.get("template_code", "asset")
        return "Market Asset Crafted", f"A new {template_code} asset was crafted for sale."

    if event_type == "market_purchase_submitted":
        listing_kind = payload.get("listing_kind", "listing")
        price = payload.get("price", "0")
        return "Purchase Submitted", f"A {listing_kind} purchase entered escrow at {price} credits."

    if event_type == "market_contract_transferred":
        sale_price = payload.get("sale_price", "0")
        return "Contract Transferred", f"A pending contract right was transferred for {sale_price} credits."

    if event_type == "market_reputation_adjusted":
        delta = payload.get("delta", "0")
        new_reputation = payload.get("new_reputation", "?")
        return "Market Reputation", f"Seller reputation moved by {delta}; new score {new_reputation}."

    if event_type == "service_contract_fulfilled":
        return "Service Fulfilled", "A bounded market service contract was fulfilled."

    if event_type == "service_contract_refunded":
        return "Service Refunded", "A market service contract timed out and escrow was refunded."

    if event_type == "security_instrument_created":
        symbol = payload.get("symbol", "instrument")
        family = payload.get("family", "note")
        return "Instrument Listed", f"{symbol} opened on the exchange as a {family}."

    if event_type == "security_order_placed":
        side = payload.get("side", "order")
        symbol = payload.get("instrument_symbol", "instrument")
        quantity = payload.get("quantity", "?")
        price = payload.get("price", "?")
        return "Order Placed", f"{side.title()} order on {symbol}: {quantity} @ {price}."

    if event_type == "security_order_cancelled":
        return "Order Cancelled", "An open exchange order was cancelled."

    if event_type == "security_trade_executed":
        symbol = payload.get("instrument_symbol", "instrument")
        quantity = payload.get("quantity", "?")
        price = payload.get("price", "?")
        return "Trade Executed", f"{symbol} traded {quantity} @ {price}."

    if event_type == "market_mark_updated":
        symbol = payload.get("instrument_symbol", "instrument")
        price = payload.get("mark_price", "?")
        return "Mark Updated", f"{symbol} mark moved to {price}."

    if event_type == "instrument_halted":
        symbol = payload.get("instrument_symbol", "instrument")
        return "Instrument Halted", f"{symbol} was halted."

    if event_type == "position_liquidated":
        symbol = payload.get("instrument_symbol", "instrument")
        return "Position Liquidated", f"A position in {symbol} was liquidated."

    if event_type == "governance_proposal_created":
        return "Governance Proposal", "A new governance proposal was created."

    if event_type == "governance_vote_cast":
        return "Vote Cast", "A governance vote was recorded."

    if event_type == "debugger_diagnosis_logged":
        return "Debugger Diagnosis", "Debugger logged a failure diagnosis and remediation path."

    return _humanize_event_type(event_type), _humanize_event_type(event_type)


@router.get("", response_model=ActivityFeedResponse)
async def list_recent_activity(
    limit: int = Query(40, ge=1, le=200, description="Maximum activity events to return"),
    window_minutes: int = Query(
        15,
        ge=1,
        le=240,
        description="Only return activity from the trailing N minutes",
    ),
):
    """Return recent business events for the live dashboard activity panel."""
    async with get_connection() as conn:
        cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
        result = await conn.execute(
            sa.select(events)
            .where(events.c.created_at >= cutoff)
            .order_by(events.c.created_at.desc())
            .limit(limit)
        )
        event_rows = result.fetchall()

        active_instance_count = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(agent_instances)
                .where(agent_instances.c.status.in_(["pending", "running"]))
            )
            or 0
        )

        context = await _load_context_maps(conn, event_rows)

    entries = []
    for row in event_rows:
        payload = dict(row.payload or {})
        title, summary = _summarize_event(row, context)
        entries.append(
            ActivityEntryResponse(
                event_id=row.event_id,
                event_type=row.event_type,
                entity_id=row.entity_id,
                entity_type=row.entity_type,
                title=title,
                summary=summary,
                severity=_severity_for_event(row.event_type, payload),
                payload=payload,
                created_at=row.created_at,
            )
        )

    return ActivityFeedResponse(
        entries=entries,
        count=len(entries),
        active_instance_count=active_instance_count,
        window_minutes=window_minutes,
    )
