import asyncio
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import sqlalchemy as sa
import structlog

from nexus_core.config import NexusSettings
from nexus_core.llm.client import KimiClient
from nexus_core.llm.prompt_builder import PromptBuilder
from nexus_core.llm.response_parser import ResponseParser
from nexus_core.models.instances import agent_instances
from nexus_core.models.findings import findings
from nexus_core.models.institutional_memory import institutional_memory
from nexus_core.models.knowledge_graph import knowledge_graph_edges, knowledge_graph_nodes
from nexus_core.models.objectives import objectives
from nexus_core.models.personas import agent_personas
from nexus_core.models.telemetry import agent_telemetry
from nexus_core.reporting import (
    CitationRecord,
    KGEdgeDelta,
    KGEdgeReference,
    KGNodeDelta,
    KGNodeReference,
    KGWriteSummary,
    RecommendationSourceFinding,
    RecommendationSummary,
    ReviewNote,
    write_finding_report,
    write_repaired_recommendation_report,
    write_recommendation_report,
)
from nexus_core.review.infiltrator import check_infiltration_outcome
from nexus_core.review.peer_review import ReviewDeferredError, orchestrate_review
from nexus_core.review.red_team import dispatch_challenge, process_challenge
from nexus_core.knowledge.graph_ops import create_node, create_edge, update_edge_status, update_node_status
from nexus_core.economy.ledger import mint_credits
from nexus_core.utils.cost import calculate_cost_breakdown, coerce_decimal_rate
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)


async def integrate_results(
    engine,
    kimi_client: KimiClient,
    instance_id: UUID,
    settings: NexusSettings,
):
    """Integrate completed agent instance results into the civilization.

    Flow: get finding -> peer review -> if approved: write to KG + distribute bounty
          -> check parent completion
    """
    # Get the instance and its finding
    async with engine.begin() as conn:
        inst_result = await conn.execute(
            agent_instances.select().where(
                agent_instances.c.instance_id == instance_id
            )
        )
        instance = inst_result.first()
        if instance is None or instance.status != "completed":
            return

        # Get finding for this instance
        finding_result = await conn.execute(
            findings.select()
            .where(
                findings.c.instance_id == instance_id,
                findings.c.status == "pending_review",
            )
            .limit(1)
        )
        finding = finding_result.first()

    if finding is None:
        async with engine.begin() as conn:
            fallback_result = await conn.execute(
                sa.select(
                    findings.c.finding_id,
                    findings.c.objective_id,
                    findings.c.status,
                )
                .where(findings.c.instance_id == instance_id)
                .order_by(findings.c.created_at.desc())
                .limit(1)
            )
            fallback_finding = fallback_result.first()

        if fallback_finding is not None:
            recovered_status = await _reconcile_objective_state_from_finding(
                engine,
                kimi_client,
                objective_id=fallback_finding.objective_id,
                finding_status=fallback_finding.status,
                finding_id=fallback_finding.finding_id,
                settings=settings,
                recovery_reason="finding_already_reviewed",
            )
            if recovered_status is not None:
                logger.info(
                    "objective_state_recovered_from_existing_finding",
                    instance_id=str(instance_id),
                    objective_id=str(fallback_finding.objective_id),
                    finding_id=str(fallback_finding.finding_id),
                    recovered_status=recovered_status,
                )
        else:
            logger.info("no_pending_finding", instance_id=str(instance_id))

        # Mark instance as integrated
        async with engine.begin() as conn:
            await conn.execute(
                agent_instances.update()
                .where(agent_instances.c.instance_id == instance_id)
                .values(status="integrated")
            )
        return

    # Run citation verification before peer review
    try:
        from nexus_core.citation.verifier import run_citation_check
        async with engine.begin() as conn:
            await run_citation_check(
                conn, finding.finding_id,
                timeout_secs=settings.CITATION_CHECK_TIMEOUT_SECS,
                cache_ttl_days=settings.CITATION_CACHE_TTL_DAYS,
            )
    except Exception:
        logger.warning("citation_check_skipped", finding_id=str(finding.finding_id))

    # Run peer review (orchestrate_review expects a connection)
    try:
        async with engine.begin() as conn:
            review_outcome = await orchestrate_review(
                conn, kimi_client, finding.finding_id
            )
    except ReviewDeferredError as e:
        logger.warning(
            "peer_review_deferred",
            finding_id=str(finding.finding_id),
            error=str(e),
        )
        return
    except Exception as e:
        logger.error(
            "peer_review_failed",
            finding_id=str(finding.finding_id),
            error=str(e),
        )
        return

    if review_outcome.verdict == "approved":
        # Write to KG
        kg_summary = await _write_to_kg(engine, finding, instance)

        # Distribute bounty
        async with engine.begin() as conn:
            bounty_amount = Decimal("10.00")
            await mint_credits(
                conn,
                bounty_amount,
                instance.persona_id,
                reference_objective_id=instance.objective_id,
                memo=f"Bounty for finding: {finding.title}",
            )

        logger.info(
            "finding_integrated",
            finding_id=str(finding.finding_id),
            verdict="approved",
        )
        objective_values = {
            "status": "completed",
            "completed_at": sa.func.now(),
            "escalated_at": None,
            "escalation_reason": None,
            "assigned_to": None,
        }
        objective_event = "objective_completed"

    elif review_outcome.verdict == "escalated":
        logger.warning(
            "finding_escalated",
            finding_id=str(finding.finding_id),
        )
        objective_values = {
            "status": "escalated",
            "escalated_at": sa.func.now(),
            "escalation_reason": "Finding failed peer review twice (circuit breaker)",
            "assigned_to": None,
        }
        objective_event = None
    else:
        logger.warning(
            "finding_rejected",
            finding_id=str(finding.finding_id),
        )
        objective_values = {
            "status": "revision_requested",
            "escalation_reason": "Peer review requested one revision pass",
            "assigned_to": None,
        }
        objective_event = "objective_revision_requested"

    # Mark instance as integrated
    async with engine.begin() as conn:
        await conn.execute(
            agent_instances.update()
            .where(agent_instances.c.instance_id == instance_id)
            .values(status="integrated")
        )
        await conn.execute(
            objectives.update()
            .where(objectives.c.objective_id == instance.objective_id)
            .values(**objective_values)
        )
        if objective_event:
            await emit_event(
                conn,
                objective_event,
                entity_id=instance.objective_id,
                entity_type="objective",
            )

    if review_outcome.verdict == "approved":
        await _publish_approval_reports(
            engine=engine,
            finding=finding,
            instance=instance,
            review_outcome=review_outcome,
            kg_summary=kg_summary,
            settings=settings,
        )
        async with engine.begin() as conn:
            challenge = await dispatch_challenge(conn, kimi_client, finding.finding_id)
            if challenge is not None:
                await process_challenge(conn, challenge, finding.finding_id)
            if getattr(finding, "is_infiltration", False):
                await check_infiltration_outcome(conn, finding.finding_id)
    elif review_outcome.verdict == "rejected":
        await _store_review_feedback(engine, finding, review_outcome)
        dispatcher = _make_dispatcher(engine, kimi_client, settings)
        await dispatcher.dispatch_objective(instance.objective_id)

    # Check if parent objective is complete
    await _advance_parent_objective(
        engine,
        kimi_client,
        instance.objective_id,
        settings=settings,
    )


async def _write_to_kg(engine, finding, instance):
    """Extract KG entities and relationships from a finding and write to KG."""
    if finding.structured_data is None:
        return KGWriteSummary()

    entities = finding.structured_data.get("kg_entities", [])
    relationships = finding.structured_data.get("kg_relationships", [])

    node_map: dict[str, UUID] = {}  # label -> node_id
    node_summaries: list[KGNodeDelta] = []
    edge_summaries: list[KGEdgeDelta] = []

    async with engine.begin() as conn:
        # Create nodes
        for entity in entities:
            label = str(entity.get("label", "")).strip()
            if not label:
                logger.warning(
                    "kg_entity_skipped_missing_label",
                    objective_id=str(instance.objective_id),
                    instance_id=str(instance.instance_id),
                    entity=entity,
                )
                continue
            node_id, is_new = await create_node(
                conn,
                label=label,
                node_type=entity.get("type", "concept"),
                properties=entity.get("properties", {}),
                confidence=0.5,
                objective_id=instance.objective_id,
                instance_id=instance.instance_id,
            )
            node_map[label] = node_id
            node_record_result = await conn.execute(
                sa.select(
                    knowledge_graph_nodes.c.label,
                    knowledge_graph_nodes.c.node_type,
                ).where(knowledge_graph_nodes.c.node_id == node_id)
            )
            node_record = node_record_result.first()
            node_summaries.append(
                KGNodeDelta(
                    node_id=node_id,
                    label=(
                        node_record.label
                        if node_record is not None and getattr(node_record, "label", None)
                        else label
                    ),
                    node_type=(
                        node_record.node_type
                        if node_record is not None
                        and getattr(node_record, "node_type", None)
                        else entity.get("type", "concept")
                    ),
                    action="created" if is_new else "merged",
                    properties=entity.get("properties", {}) or {},
                )
            )

        # Create edges
        for rel in relationships:
            source_label = str(rel.get("source", "")).strip()
            target_label = str(rel.get("target", "")).strip()
            if source_label in node_map and target_label in node_map:
                edge_id = await create_edge(
                    conn,
                    source_node_id=node_map[source_label],
                    target_node_id=node_map[target_label],
                    relationship_type=rel.get("type", "relates_to"),
                    weight=rel.get("weight", 0.5),
                    confidence=0.5,
                    evidence_ids=[str(finding.finding_id)],
                    objective_id=instance.objective_id,
                )
                edge_summaries.append(
                    KGEdgeDelta(
                        edge_id=edge_id,
                        source_label=source_label,
                        target_label=target_label,
                        relationship_type=str(rel.get("type", "relates_to")),
                        weight=float(rel.get("weight", 0.5)),
                    )
                )

        for node_id in node_map.values():
            await update_node_status(conn, node_id, "validated")
        for edge in edge_summaries:
            await update_edge_status(conn, edge.edge_id, "validated")

        # Update finding with created KG references
        await conn.execute(
            findings.update()
            .where(findings.c.finding_id == finding.finding_id)
            .values(
                kg_nodes_created=[str(node.node_id) for node in node_summaries],
                kg_edges_created=[str(edge.edge_id) for edge in edge_summaries],
            )
        )
    return KGWriteSummary(nodes=node_summaries, edges=edge_summaries)


async def _advance_parent_objective(
    engine,
    kimi_client: KimiClient,
    objective_id: UUID,
    settings: NexusSettings | None = None,
):
    """Propagate child completion state upward and synthesize parents when ready."""
    parent_to_dispatch: UUID | None = None
    parent_to_synthesize: UUID | None = None

    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(objectives.c.parent_objective_id).where(
                objectives.c.objective_id == objective_id
            )
        )
        row = result.first()
        if row is None or row.parent_objective_id is None:
            return

        parent_id = row.parent_objective_id
        status_q = await conn.execute(
            sa.select(objectives.c.objective_id, objectives.c.status).where(
                objectives.c.parent_objective_id == parent_id
            )
        )
        child_rows = status_q.fetchall()
        child_statuses = {
            str(child.objective_id): child.status for child in child_rows
        }

        if not child_statuses:
            return

        if any(status in {"failed", "escalated"} for status in child_statuses.values()):
            await conn.execute(
                objectives.update()
                .where(objectives.c.objective_id == parent_id)
                .values(
                    status="escalated",
                    escalated_at=sa.func.now(),
                    escalation_reason="One or more child objectives failed or escalated",
                )
            )
            logger.info(
                "parent_objective_escalated",
                parent_id=str(parent_id),
                child_statuses=child_statuses,
            )
            return

        if any(status != "completed" for status in child_statuses.values()):
            if any(status in {"proposed", "revision_requested"} for status in child_statuses.values()):
                parent_to_dispatch = parent_id
            else:
                return

        if parent_to_dispatch is None:
            claim = await conn.execute(
                objectives.update()
                .where(
                    objectives.c.objective_id == parent_id,
                    objectives.c.status.notin_(["completed", "synthesizing"]),
                )
                .values(status="synthesizing")
            )
            if claim.rowcount == 0:
                return
            parent_to_synthesize = parent_id

    if parent_to_dispatch is not None:
        dispatcher = _make_dispatcher(engine, kimi_client, settings)
        await dispatcher.dispatch_dag(parent_to_dispatch)
        return

    try:
        await _synthesize_parent_objective(
            engine,
            kimi_client,
            parent_to_synthesize,
            settings=settings,
        )
    except Exception as exc:
        logger.error(
            "parent_objective_synthesis_failed",
            parent_id=str(parent_to_synthesize),
            error=str(exc),
        )
        async with engine.begin() as conn:
            await conn.execute(
                objectives.update()
                .where(objectives.c.objective_id == parent_to_synthesize)
                .values(
                    status="failed",
                    escalation_reason=f"Final synthesis failed: {exc}",
                )
            )


async def _reconcile_objective_state_from_finding(
    engine,
    kimi_client: KimiClient,
    *,
    objective_id: UUID,
    finding_status: str | None,
    settings: NexusSettings | None = None,
    finding_id: UUID | None = None,
    recovery_reason: str = "stranded_objective_recovery",
) -> str | None:
    """Repair an objective state from its most recent reviewed finding."""
    if finding_status in {"validated", "challenged"}:
        desired_status = "completed"
        values = {
            "status": "completed",
            "completed_at": sa.func.now(),
            "escalated_at": None,
            "escalation_reason": None,
            "assigned_to": None,
        }
        objective_event = "objective_completed"
    elif finding_status == "revision_requested":
        desired_status = "revision_requested"
        values = {
            "status": "revision_requested",
            "escalation_reason": "Recovered from a reviewed finding awaiting revision",
            "assigned_to": None,
        }
        objective_event = "objective_revision_requested"
    elif finding_status == "escalated":
        desired_status = "escalated"
        values = {
            "status": "escalated",
            "escalated_at": sa.func.now(),
            "escalation_reason": "Recovered from an escalated reviewed finding",
            "assigned_to": None,
        }
        objective_event = None
    else:
        return None

    previous_status: str | None = None
    should_emit_event = False
    async with engine.begin() as conn:
        objective_result = await conn.execute(
            sa.select(objectives.c.status).where(objectives.c.objective_id == objective_id)
        )
        objective = objective_result.first()
        if objective is None:
            return None

        previous_status = objective.status
        update_result = await conn.execute(
            objectives.update()
            .where(
                objectives.c.objective_id == objective_id,
                objectives.c.status != desired_status,
            )
            .values(**values)
        )
        should_emit_event = update_result.rowcount > 0
        if should_emit_event and objective_event is not None:
            await emit_event(
                conn,
                objective_event,
                entity_id=objective_id,
                entity_type="objective",
            )

    logger.info(
        "objective_state_reconciled_from_finding",
        objective_id=str(objective_id),
        finding_id=str(finding_id) if finding_id is not None else None,
        finding_status=finding_status,
        previous_status=previous_status,
        new_status=desired_status,
        recovery_reason=recovery_reason,
    )

    if desired_status == "completed":
        await _advance_parent_objective(
            engine,
            kimi_client,
            objective_id,
            settings=settings,
        )

    return desired_status


async def _synthesize_parent_objective(
    engine,
    kimi_client: KimiClient,
    parent_id: UUID,
    settings: NexusSettings | None = None,
):
    """Generate a synthesis artifact once every child objective has completed."""
    async with engine.begin() as conn:
        parent_result = await conn.execute(
            objectives.select().where(objectives.c.objective_id == parent_id)
        )
        parent = parent_result.first()
        if parent is None:
            return

        finding_rows = await _select_branch_source_rows(conn, parent_id)

        persona = await _select_synthesis_persona(conn)
        if persona is None:
            raise ValueError("No active synthesizer persona available for final synthesis")

    synthesis_inputs = [
        {
            "finding_id": str(row.finding_id),
            "objective_id": str(row.objective_id),
            "objective_title": getattr(row, "objective_title", ""),
            "status": getattr(row, "status", "validated"),
            "title": row.title,
            "content": row.content,
        }
        for row in finding_rows
    ]
    system_prompt, user_prompt = PromptBuilder.build_synthesis_prompt(
        objective_title=parent.title,
        findings=synthesis_inputs,
    )
    response = await kimi_client.call_thinking(system_prompt, user_prompt)
    synthesis = ResponseParser.parse_synthesis(response.content)
    client_settings = getattr(kimi_client, "_settings", None)
    cost_breakdown = calculate_cost_breakdown(
        input_tokens=response.input_tokens,
        thinking_tokens=response.thinking_tokens,
        output_tokens=response.output_tokens,
        cost_input_per_million=coerce_decimal_rate(
            getattr(client_settings, "COST_INPUT_PER_MILLION", None),
            Decimal("0.60"),
        ),
        cost_output_per_million=coerce_decimal_rate(
            getattr(client_settings, "COST_OUTPUT_PER_MILLION", None),
            Decimal("2.50"),
        ),
    )
    cost_total = cost_breakdown.total_cost_usd
    source_finding_ids = [str(row.finding_id) for row in finding_rows]
    source_objective_ids = [str(row.objective_id) for row in finding_rows]
    source_statuses = {str(row.finding_id): row.status for row in finding_rows}

    async with engine.begin() as conn:
        instance_result = await conn.execute(
            agent_instances.insert()
            .values(
                persona_id=persona.persona_id,
                objective_id=parent_id,
                input_prompt=user_prompt,
                spawn_reason="final_synthesis",
                status="completed",
                output_content=synthesis.content,
                thinking_content=response.reasoning,
                completed_at=sa.func.now(),
                tokens_input=response.input_tokens,
                tokens_thinking=response.thinking_tokens,
                tokens_output=response.output_tokens,
                cost_usd=cost_total,
                latency_ms=response.latency_ms,
            )
            .returning(agent_instances.c.instance_id)
        )
        synthesis_instance_id = instance_result.scalar_one()

        synthesis_finding_result = await conn.execute(
            findings.insert().values(
                objective_id=parent_id,
                instance_id=synthesis_instance_id,
                finding_type="synthesis",
                title=f"Synthesis: {parent.title}",
                content=synthesis.content,
                structured_data={
                    "source_finding_ids": source_finding_ids,
                    "source_objective_ids": source_objective_ids,
                    "source_statuses": source_statuses,
                    "source_selection_policy": "accepted_descendants",
                },
                status="validated",
                impact_level=parent.impact_level,
                kg_nodes_created=[],
                kg_edges_created=[],
            )
            .returning(findings.c.finding_id)
        )
        synthesis_finding_id = synthesis_finding_result.scalar_one()
        await conn.execute(
            agent_telemetry.insert().values(
                instance_id=synthesis_instance_id,
                persona_id=persona.persona_id,
                objective_id=parent_id,
                prompt_hash=response.prompt_hash,
                tokens_input=response.input_tokens,
                tokens_thinking=response.thinking_tokens,
                tokens_output=response.output_tokens,
                cost_input_usd=cost_breakdown.input_cost_usd,
                cost_thinking_usd=cost_breakdown.thinking_cost_usd,
                cost_output_usd=cost_breakdown.output_cost_usd,
                cost_total_usd=cost_total,
                latency_ms=response.latency_ms,
                http_status=200,
                success=True,
                model_id=response.model,
            )
        )
        await conn.execute(
            objectives.update()
            .where(objectives.c.objective_id == parent_id)
            .values(
                status="completed",
                completed_at=sa.func.now(),
                output_type="synthesis",
                escalation_reason=None,
            )
        )
        await emit_event(
            conn,
            "objective_completed",
            entity_id=parent_id,
            entity_type="objective",
        )
        await emit_event(
            conn,
            "objective_synthesized",
            entity_id=parent_id,
            entity_type="objective",
            payload={
                "instance_id": str(synthesis_instance_id),
                "source_finding_count": len(finding_rows),
                "source_selection_policy": "accepted_descendants",
            },
        )

    if getattr(parent, "parent_objective_id", None) is None:
        async with engine.begin() as conn:
            recommendation_summary = await _build_recommendation_summary(
                conn,
                question_objective_id=parent_id,
                question_title=parent.title,
                synthesis_finding_id=synthesis_finding_id,
                synthesis_instance_id=synthesis_instance_id,
                synthesizer_name=getattr(persona, "persona_name", "Systems Synthesizer"),
                recommendation_markdown=synthesis.content,
                source_rows=finding_rows,
                source_selection_policy="accepted_descendants",
            )
        await _publish_recommendation_report(
            engine=engine,
            settings=settings,
            summary=recommendation_summary,
            question_status="completed",
            event_entity_id=parent_id,
        )

    logger.info(
        "parent_objective_completed",
        parent_id=str(parent_id),
        source_finding_count=len(finding_rows),
    )
    await _advance_parent_objective(
        engine,
        kimi_client,
        parent_id,
        settings=settings,
    )


async def _select_synthesis_persona(conn):
    """Pick an active synthesizer persona, with pragmatic fallbacks."""
    for role_classes in (["synthesizer"], ["synthesizer", "researcher"], None):
        query = agent_personas.select().where(agent_personas.c.status == "active")
        if role_classes is not None:
            query = query.where(agent_personas.c.role_class.in_(role_classes))
        result = await conn.execute(
            query.order_by(agent_personas.c.reputation_score.desc()).limit(1)
        )
        persona = result.first()
        if persona is not None:
            return persona

    return None


async def _store_review_feedback(engine, finding, review_outcome) -> None:
    """Persist reviewer feedback so the revision pass sees it in prompt context."""
    feedback_items = [
        review.revision_feedback.strip()
        for review in review_outcome.reviews
        if review.revision_feedback and review.revision_feedback.strip()
    ]
    if not feedback_items:
        return

    async with engine.begin() as conn:
        await conn.execute(
            institutional_memory.insert().values(
                memory_type="peer_review_feedback",
                title=f"Revision feedback for finding {finding.finding_id}",
                content="\n".join(f"- {item}" for item in feedback_items),
                source_objective_id=finding.objective_id,
                source_instance_id=finding.instance_id,
                relevance_tags=["peer_review", "revision", "feedback"],
            )
        )


def _make_dispatcher(engine, kimi_client, settings):
    from nexus_engine.dispatcher import Dispatcher

    return Dispatcher(
        engine=engine,
        kimi_client=kimi_client,
        settings=settings,
        shutdown_event=asyncio.Event(),
    )


async def _publish_approval_reports(
    *,
    engine,
    finding,
    instance,
    review_outcome,
    kg_summary: KGWriteSummary,
    settings: NexusSettings,
) -> None:
    """Write the approved finding dossier and leaf recommendation when applicable."""
    try:
        async with engine.begin() as conn:
            lineage = await _load_objective_lineage(conn, instance.objective_id)
            if not lineage:
                return
            objective = lineage[0]
            root_objective = lineage[-1]
            author_persona_name = await _load_persona_name(conn, instance.persona_id)
            child_count = await _count_child_objectives(conn, instance.objective_id)
            review_round_result = await conn.execute(
                sa.select(findings.c.review_round).where(
                    findings.c.finding_id == finding.finding_id
                )
            )
            review_round = review_round_result.scalar_one() or 0

        finding_report_path = await asyncio.to_thread(
            write_finding_report,
            settings=settings,
            root_objective_id=root_objective.objective_id,
            root_objective_title=root_objective.title,
            root_objective_status=root_objective.status,
            objective_id=objective.objective_id,
            objective_title=objective.title,
            objective_type=objective.objective_type,
            objective_description=objective.description,
            finding_id=finding.finding_id,
            finding_title=finding.title,
            finding_type=finding.finding_type,
            finding_content=finding.content,
            impact_level=review_outcome.impact_level,
            author_persona_name=author_persona_name,
            review_round=review_round,
            mean_review_confidence=review_outcome.mean_review_confidence,
            support_ratio=review_outcome.support_ratio,
            approval_count=review_outcome.approval_count,
            revise_count=review_outcome.revise_count,
            reject_count=review_outcome.reject_count,
            reviewer_count=review_outcome.reviewer_count,
            required_consensus=review_outcome.required_consensus,
            verdict_breakdown=review_outcome.verdict_breakdown,
            reviewers=[
                ReviewNote(
                    verdict=review.verdict,
                    confidence_rating=review.confidence_rating,
                    methodology_critique=review.methodology_critique,
                    evidence_evaluation=review.evidence_evaluation,
                    novelty_assessment=review.novelty_assessment,
                    revision_feedback=review.revision_feedback,
                )
                for review in review_outcome.reviews
            ],
            kg_summary=kg_summary,
            citations=_collect_citations_from_payload(getattr(finding, "structured_data", None)),
        )
        logger.info(
            "finding_report_written",
            finding_id=str(finding.finding_id),
            report_path=str(finding_report_path),
        )
        async with engine.begin() as conn:
            await emit_event(
                conn,
                "finding_report_written",
                entity_id=finding.finding_id,
                entity_type="finding",
                payload={
                    "path": str(finding_report_path),
                    "root_objective_id": str(root_objective.objective_id),
                    "objective_id": str(objective.objective_id),
                },
            )

        if objective.objective_id == root_objective.objective_id and child_count == 0:
            async with engine.begin() as conn:
                leaf_summary = await _build_recommendation_summary(
                    conn,
                    question_objective_id=root_objective.objective_id,
                    question_title=root_objective.title,
                    synthesis_finding_id=finding.finding_id,
                    synthesis_instance_id=instance.instance_id,
                    synthesizer_name=author_persona_name,
                    recommendation_markdown=finding.content,
                    source_rows=[finding],
                    source_selection_policy="accepted_descendants",
                    precomputed_kg_summary=kg_summary,
                )
            await _publish_recommendation_report(
                engine=engine,
                settings=settings,
                summary=leaf_summary,
                question_status=objective.status,
                event_entity_id=root_objective.objective_id,
            )
    except Exception:
        logger.exception(
            "finding_report_generation_failed",
            finding_id=str(finding.finding_id),
        )


async def _publish_recommendation_report(
    *,
    engine,
    settings: NexusSettings | None,
    summary: RecommendationSummary,
    question_status: str,
    event_entity_id: UUID,
) -> None:
    """Write the final recommendation dossier for a root question."""
    try:
        artifact_bundle = await asyncio.to_thread(
            write_recommendation_report,
            settings=settings,
            summary=summary,
            question_status=question_status,
        )
        logger.info(
            "recommendation_report_written",
            objective_id=str(summary.question_objective_id),
            report_path=str(artifact_bundle.report_path),
            manifest_path=str(artifact_bundle.manifest_path),
        )
        async with engine.begin() as conn:
            await emit_event(
                conn,
                "recommendation_report_written",
                entity_id=event_entity_id,
                entity_type="objective",
                payload={
                    "path": str(artifact_bundle.report_path),
                    "manifest_path": str(artifact_bundle.manifest_path),
                    "question_title": summary.question_title,
                    "source_finding_count": len(summary.source_findings),
                },
            )
    except Exception:
        logger.exception(
            "recommendation_report_generation_failed",
            objective_id=str(summary.question_objective_id),
        )


async def _load_objective_lineage(conn, objective_id: UUID) -> list:
    """Load the current objective and each parent up to the root objective."""
    lineage = []
    current_id = objective_id
    visited: set[UUID] = set()
    while current_id is not None:
        if current_id in visited:
            logger.warning(
                "objective_lineage_cycle_detected",
                objective_id=str(objective_id),
                repeated_objective_id=str(current_id),
            )
            break
        visited.add(current_id)
        result = await conn.execute(
            objectives.select().where(objectives.c.objective_id == current_id)
        )
        row = result.first()
        if row is None:
            break
        lineage.append(row)
        current_id = row.parent_objective_id
    return lineage


async def _load_persona_name(conn, persona_id: UUID) -> str:
    """Resolve a persona name for report attribution."""
    result = await conn.execute(
        sa.select(agent_personas.c.persona_name).where(
            agent_personas.c.persona_id == persona_id
        )
    )
    return result.scalar_one_or_none() or "Unknown Persona"


async def _count_child_objectives(conn, objective_id: UUID) -> int:
    """Count immediate child objectives for root-recommendation detection."""
    result = await conn.execute(
        sa.select(sa.func.count())
        .select_from(objectives)
        .where(objectives.c.parent_objective_id == objective_id)
    )
    return int(result.scalar_one() or 0)


async def repair_recommendation_report_for_objective(
    engine,
    settings: NexusSettings | None,
    objective_id: UUID,
):
    """Rebuild a sparse historical recommendation report as a versioned repair."""
    async with engine.begin() as conn:
        objective_row = await conn.execute(
            objectives.select().where(objectives.c.objective_id == objective_id)
        )
        objective = objective_row.first()
        if objective is None:
            raise ValueError(f"Objective {objective_id} not found")

        synthesis_row = await conn.execute(
            sa.select(
                findings.c.finding_id,
                findings.c.instance_id,
                findings.c.title,
                findings.c.content,
                findings.c.structured_data,
            )
            .where(
                findings.c.objective_id == objective_id,
                findings.c.finding_type == "synthesis",
            )
            .order_by(findings.c.created_at.desc())
            .limit(1)
        )
        synthesis = synthesis_row.first()
        if synthesis is None:
            synthesis_row = await conn.execute(
                sa.select(
                    findings.c.finding_id,
                    findings.c.instance_id,
                    findings.c.title,
                    findings.c.content,
                    findings.c.structured_data,
                )
                .where(findings.c.objective_id == objective_id)
                .order_by(findings.c.created_at.desc())
                .limit(1)
            )
            synthesis = synthesis_row.first()
        if synthesis is None:
            raise ValueError(f"Objective {objective_id} has no finding content to repair")

        persona_name = "Systems Synthesizer"
        if synthesis.instance_id is not None:
            persona_name = await _load_persona_name_for_instance(conn, synthesis.instance_id)

        source_rows = await _select_branch_source_rows(conn, objective_id)
        if not source_rows and objective.parent_objective_id is None and await _count_child_objectives(conn, objective_id) == 0:
            source_rows = [await _load_source_finding_row(conn, synthesis.finding_id)]

        summary = await _build_recommendation_summary(
            conn,
            question_objective_id=objective_id,
            question_title=objective.title,
            synthesis_finding_id=synthesis.finding_id,
            synthesis_instance_id=synthesis.instance_id,
            synthesizer_name=persona_name,
            recommendation_markdown=synthesis.content,
            source_rows=source_rows,
            source_selection_policy="accepted_descendants",
            repair_metadata={
                "repair_reason": "Reconstructed evidence base for sparse historical recommendation report",
                "repaired_at": datetime.utcnow().isoformat(),
            },
        )
        question_status = objective.status

    artifact_bundle = await asyncio.to_thread(
        write_repaired_recommendation_report,
        settings=settings,
        summary=summary,
        question_status=question_status,
        repair_reason="Recovered accepted descendant findings, KG references, and citations for a historical sparse report.",
    )

    async with engine.begin() as conn:
        await emit_event(
            conn,
            "recommendation_report_repaired",
            entity_id=objective_id,
            entity_type="objective",
            payload={
                "path": str(artifact_bundle.report_path),
                "manifest_path": str(artifact_bundle.manifest_path),
                "repair_note_path": str(artifact_bundle.repair_note_path) if artifact_bundle.repair_note_path else None,
                "source_finding_count": len(summary.source_findings),
            },
        )
    return artifact_bundle


async def _select_branch_source_rows(conn, parent_objective_id: UUID) -> list[SimpleNamespace]:
    """Select the latest accepted descendant finding for each direct child branch."""
    child_result = await conn.execute(
        sa.select(objectives.c.objective_id, objectives.c.title)
        .where(objectives.c.parent_objective_id == parent_objective_id)
        .order_by(objectives.c.created_at.asc())
    )
    children = child_result.fetchall()
    selected: list[SimpleNamespace] = []
    for child in children:
        descendant_ids = await _load_descendant_objective_ids(conn, child.objective_id)
        if not descendant_ids:
            continue
        row = await _load_latest_accepted_finding_for_objectives(conn, descendant_ids)
        if row is None:
            continue
        payload = dict(row._mapping)
        payload["branch_root_objective_id"] = child.objective_id
        payload["branch_root_title"] = child.title
        selected.append(SimpleNamespace(**payload))
    return selected


async def _load_descendant_objective_ids(conn, root_objective_id: UUID) -> list[UUID]:
    """Load a subtree of objective IDs, including the provided root objective."""
    result = await conn.execute(
        sa.text(
            """
            WITH RECURSIVE objective_tree AS (
                SELECT objective_id
                FROM objectives
                WHERE objective_id = :root_id
                UNION ALL
                SELECT o.objective_id
                FROM objectives o
                JOIN objective_tree t ON o.parent_objective_id = t.objective_id
            )
            SELECT objective_id FROM objective_tree
            """
        ),
        {"root_id": root_objective_id},
    )
    return [row.objective_id for row in result]


async def _load_latest_accepted_finding_for_objectives(conn, objective_ids: list[UUID]):
    """Load the newest report-eligible finding for a branch."""
    result = await conn.execute(
        sa.select(
            findings.c.finding_id,
            findings.c.objective_id,
            objectives.c.title.label("objective_title"),
            findings.c.title,
            findings.c.content,
            findings.c.finding_type,
            findings.c.impact_level,
            findings.c.review_round,
            findings.c.structured_data,
            findings.c.kg_nodes_created,
            findings.c.kg_edges_created,
            findings.c.status,
            findings.c.created_at,
        )
        .join(objectives, objectives.c.objective_id == findings.c.objective_id)
        .where(
            findings.c.objective_id.in_(objective_ids),
            findings.c.status.in_(["validated", "challenged"]),
            findings.c.finding_type != "infiltration_test",
        )
        .order_by(
            sa.case((findings.c.finding_type == "external_intelligence", 1), else_=0).asc(),
            findings.c.created_at.desc(),
        )
        .limit(1)
    )
    return result.first()


async def _load_source_finding_row(conn, finding_id: UUID):
    """Load a full finding row with objective title for recommendation summaries."""
    result = await conn.execute(
        sa.select(
            findings.c.finding_id,
            findings.c.objective_id,
            objectives.c.title.label("objective_title"),
            findings.c.title,
            findings.c.content,
            findings.c.finding_type,
            findings.c.impact_level,
            findings.c.review_round,
            findings.c.structured_data,
            findings.c.kg_nodes_created,
            findings.c.kg_edges_created,
            findings.c.status,
            findings.c.created_at,
        )
        .join(objectives, objectives.c.objective_id == findings.c.objective_id)
        .where(findings.c.finding_id == finding_id)
        .limit(1)
    )
    row = result.first()
    return SimpleNamespace(**dict(row._mapping)) if row is not None else None


async def _build_recommendation_summary(
    conn,
    *,
    question_objective_id: UUID,
    question_title: str,
    synthesis_finding_id: UUID,
    synthesis_instance_id: UUID,
    synthesizer_name: str,
    recommendation_markdown: str,
    source_rows: list,
    source_selection_policy: str,
    repair_metadata: dict[str, object] | None = None,
    precomputed_kg_summary: KGWriteSummary | None = None,
) -> RecommendationSummary:
    """Build a rich recommendation summary with KG refs and citations."""
    source_findings: list[RecommendationSourceFinding] = []
    contested_findings: list[RecommendationSourceFinding] = []
    aggregated_citations: list[CitationRecord] = []
    node_ids: set[str] = set()
    edge_ids: set[str] = set()

    for source_row in source_rows:
        finding_id = getattr(source_row, "finding_id", None)
        if finding_id is None:
            continue
        hydrated = await _load_source_finding_row(conn, finding_id) or source_row
        branch_root_objective_id = getattr(
            source_row,
            "branch_root_objective_id",
            getattr(hydrated, "objective_id", None),
        )
        direct_citations = _collect_citations_from_payload(
            getattr(hydrated, "structured_data", None),
            source_finding_id=finding_id,
        )
        branch_citations = (
            await _collect_branch_citations(conn, branch_root_objective_id)
            if branch_root_objective_id is not None
            else []
        )
        citations = _dedupe_citations(direct_citations + branch_citations)

        source_finding = RecommendationSourceFinding(
            finding_id=hydrated.finding_id,
            objective_id=hydrated.objective_id,
            objective_title=getattr(hydrated, "objective_title", f"Objective {hydrated.objective_id}"),
            title=hydrated.title,
            content=hydrated.content,
            status=hydrated.status,
            finding_type=getattr(hydrated, "finding_type", "research"),
            impact_level=getattr(hydrated, "impact_level", "routine") or "routine",
            review_round=int(getattr(hydrated, "review_round", 0) or 0),
            kg_node_refs=[str(node_ref) for node_ref in (getattr(hydrated, "kg_nodes_created", None) or [])],
            kg_edge_refs=[str(edge_ref) for edge_ref in (getattr(hydrated, "kg_edges_created", None) or [])],
            citations=citations,
        )
        source_findings.append(source_finding)
        if source_finding.status == "challenged":
            contested_findings.append(source_finding)
        aggregated_citations.extend(citations)
        node_ids.update(source_finding.kg_node_refs)
        edge_ids.update(source_finding.kg_edge_refs)

    kg_nodes, kg_edges = await _load_kg_references(conn, node_ids=node_ids, edge_ids=edge_ids)
    if precomputed_kg_summary is not None:
        if not kg_nodes:
            kg_nodes = [
                KGNodeReference(
                    node_id=node.node_id,
                    label=node.label,
                    node_type=node.node_type,
                    status="validated",
                    confidence_score=0.5,
                )
                for node in precomputed_kg_summary.nodes
            ]
        if not kg_edges:
            kg_edges = [
                KGEdgeReference(
                    edge_id=edge.edge_id,
                    source_label=edge.source_label,
                    target_label=edge.target_label,
                    relationship_type=edge.relationship_type,
                    status="validated",
                    confidence_score=0.5,
                    weight=edge.weight,
                )
                for edge in precomputed_kg_summary.edges
            ]

    deduped_citations = _dedupe_citations(aggregated_citations)
    return RecommendationSummary(
        question_objective_id=question_objective_id,
        question_title=question_title,
        synthesis_finding_id=synthesis_finding_id,
        synthesis_instance_id=synthesis_instance_id,
        synthesizer_name=synthesizer_name,
        recommendation_markdown=recommendation_markdown,
        source_findings=source_findings,
        source_selection_policy=source_selection_policy,
        why_this_follows=_build_why_this_follows_text(
            source_findings=source_findings,
            citations=deduped_citations,
            kg_nodes=kg_nodes,
            kg_edges=kg_edges,
        ),
        citations=deduped_citations,
        kg_nodes=kg_nodes,
        kg_edges=kg_edges,
        contested_findings=contested_findings,
        repair_metadata=repair_metadata or {},
    )


async def _load_kg_references(
    conn,
    *,
    node_ids: set[str],
    edge_ids: set[str],
) -> tuple[list[KGNodeReference], list[KGEdgeReference]]:
    """Resolve node and edge IDs into human-readable KG reference objects."""
    kg_nodes: list[KGNodeReference] = []
    kg_edges: list[KGEdgeReference] = []

    parsed_node_ids = [_safe_uuid(item) for item in sorted(node_ids)]
    parsed_node_ids = [item for item in parsed_node_ids if item is not None]
    if parsed_node_ids:
        node_result = await conn.execute(
            sa.select(
                knowledge_graph_nodes.c.node_id,
                knowledge_graph_nodes.c.label,
                knowledge_graph_nodes.c.node_type,
                knowledge_graph_nodes.c.status,
                knowledge_graph_nodes.c.confidence_score,
            )
            .where(knowledge_graph_nodes.c.node_id.in_(parsed_node_ids))
            .order_by(knowledge_graph_nodes.c.label.asc())
        )
        kg_nodes = [
            KGNodeReference(
                node_id=row.node_id,
                label=row.label,
                node_type=row.node_type,
                status=row.status,
                confidence_score=float(row.confidence_score or 0.0),
            )
            for row in node_result
        ]

    parsed_edge_ids = [_safe_uuid(item) for item in sorted(edge_ids)]
    parsed_edge_ids = [item for item in parsed_edge_ids if item is not None]
    if parsed_edge_ids:
        source_node = knowledge_graph_nodes.alias("source_node")
        target_node = knowledge_graph_nodes.alias("target_node")
        edge_result = await conn.execute(
            sa.select(
                knowledge_graph_edges.c.edge_id,
                knowledge_graph_edges.c.relationship_type,
                knowledge_graph_edges.c.status,
                knowledge_graph_edges.c.confidence_score,
                knowledge_graph_edges.c.weight,
                source_node.c.label.label("source_label"),
                target_node.c.label.label("target_label"),
            )
            .select_from(
                knowledge_graph_edges.join(
                    source_node,
                    source_node.c.node_id == knowledge_graph_edges.c.source_node_id,
                ).join(
                    target_node,
                    target_node.c.node_id == knowledge_graph_edges.c.target_node_id,
                )
            )
            .where(knowledge_graph_edges.c.edge_id.in_(parsed_edge_ids))
            .order_by(source_node.c.label.asc(), target_node.c.label.asc())
        )
        kg_edges = [
            KGEdgeReference(
                edge_id=row.edge_id,
                source_label=row.source_label,
                target_label=row.target_label,
                relationship_type=row.relationship_type,
                status=row.status,
                confidence_score=float(row.confidence_score or 0.0),
                weight=float(row.weight or 0.0),
            )
            for row in edge_result
        ]

    return kg_nodes, kg_edges


async def _collect_branch_citations(conn, branch_root_objective_id: UUID) -> list[CitationRecord]:
    """Collect structured citations for a branch."""
    descendant_ids = await _load_descendant_objective_ids(conn, branch_root_objective_id)
    if not descendant_ids:
        return []
    result = await conn.execute(
        sa.select(
            findings.c.finding_id,
            findings.c.content,
            findings.c.structured_data,
        )
        .where(findings.c.objective_id.in_(descendant_ids))
        .order_by(findings.c.created_at.desc())
    )
    citations: list[CitationRecord] = []
    for row in result:
        citations.extend(
            _collect_citations_from_payload(
                row.structured_data,
                source_finding_id=row.finding_id,
            )
        )
    return _dedupe_citations(citations)


def _collect_citations_from_payload(
    payload: dict | None,
    *,
    source_finding_id: UUID | None = None,
) -> list[CitationRecord]:
    """Normalize stored structured citations."""
    if not isinstance(payload, dict):
        return []

    citations: list[CitationRecord] = []
    for item in payload.get("citations", []) or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        citations.append(
            CitationRecord(
                title=title,
                source_type=str(item.get("source_type", "")).strip(),
                source_name=str(item.get("source_name", "")).strip(),
                url=str(item.get("url", "")).strip(),
                doi=str(item.get("doi", "")).strip(),
                published_date=str(item.get("published_date", "")).strip(),
                authors=_coerce_authors(item.get("authors")),
                supporting_snippet=str(item.get("supporting_snippet", "")).strip(),
                source_finding_id=source_finding_id,
                derived=bool(item.get("derived", False)),
            )
        )
    return _dedupe_citations(citations)


def _dedupe_citations(citations: list[CitationRecord]) -> list[CitationRecord]:
    """Deduplicate citations by DOI, URL, or title/source key."""
    deduped: dict[str, CitationRecord] = {}
    for citation in citations:
        key = (
            citation.doi.lower()
            or citation.url.lower()
            or f"{citation.title.lower()}::{citation.source_name.lower()}"
        )
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = citation
            continue
        if existing.derived and not citation.derived:
            deduped[key] = citation
    return list(deduped.values())


def _coerce_authors(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _build_why_this_follows_text(
    *,
    source_findings: list[RecommendationSourceFinding],
    citations: list[CitationRecord],
    kg_nodes: list[KGNodeReference],
    kg_edges: list[KGEdgeReference],
) -> str:
    """Create a compact explanation of why the recommendation follows from the evidence."""
    status_counts = defaultdict(int)
    for finding in source_findings:
        status_counts[finding.status] += 1
    contested = status_counts.get("challenged", 0)
    return (
        f"NEXUS synthesized {len(source_findings)} accepted branch outputs, with "
        f"{status_counts.get('validated', 0)} currently validated and {contested} currently challenged. "
        f"The recommendation is anchored to {len(kg_nodes)} KG nodes, {len(kg_edges)} KG edges, "
        f"and {len(citations)} structured source citations."
    )


async def _load_persona_name_for_instance(conn, instance_id: UUID) -> str:
    """Resolve the persona name for an agent instance."""
    result = await conn.execute(
        sa.select(agent_personas.c.persona_name)
        .join(agent_instances, agent_instances.c.persona_id == agent_personas.c.persona_id)
        .where(agent_instances.c.instance_id == instance_id)
    )
    return result.scalar_one_or_none() or "Unknown Persona"


def _safe_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
