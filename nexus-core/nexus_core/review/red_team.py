"""Red Team challenge system for NEXUS validated findings."""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
import structlog

from nexus_core.civilization.service import open_challenge_case, record_capability_signal
from nexus_core.economy.ledger import mint_credits
from nexus_core.llm.prompt_builder import PromptBuilder
from nexus_core.llm.response_parser import ResponseParser
from nexus_core.knowledge.confidence import propagate_confidence
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.knowledge_graph import knowledge_graph_nodes
from nexus_core.models.personas import agent_personas
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)

# Bounty and penalty constants
RED_TEAM_BOUNTY = Decimal("8.00")
FRIVOLOUS_PENALTY = Decimal("5.00")


@dataclass
class ChallengeReport:
    """Result of a Red Team challenge against a validated finding."""

    has_flaw: bool
    flaw_type: Optional[str]
    description: Optional[str]
    counter_evidence: Optional[str]
    severity: Optional[str]
    confidence: float
    challenger_persona_id: UUID


async def select_findings_for_challenge(
    conn,
    sample_rate: float = 0.1,
) -> list[UUID]:
    """Select recently validated findings for Red Team challenge.

    Uses a random sample biased toward high-confidence findings (which are
    more valuable to challenge successfully).
    """
    # Fetch all validated findings not yet challenged (no red-team review exists)
    result = await conn.execute(
        sa.select(
            findings.c.finding_id,
            findings.c.impact_level,
        )
        .where(
            findings.c.status == "validated",
            findings.c.is_infiltration == sa.false(),
        )
        .order_by(findings.c.created_at.desc())
        .limit(200)
    )
    candidates = list(result)

    if not candidates:
        return []

    # Bias sampling: high-impact findings are 3x more likely to be selected
    weighted: list[tuple[UUID, float]] = []
    for row in candidates:
        weight = 3.0 if row.impact_level == "high-impact" else 1.0
        weighted.append((row.finding_id, weight))

    # Reservoir-style weighted sample
    sample_count = max(1, int(len(weighted) * sample_rate))
    selected: list[UUID] = []

    # Simple weighted selection without replacement
    pool = list(weighted)
    for _ in range(min(sample_count, len(pool))):
        if not pool:
            break
        total_weight = sum(w for _, w in pool)
        r = random.uniform(0, total_weight)
        cumulative = 0.0
        for idx, (fid, w) in enumerate(pool):
            cumulative += w
            if cumulative >= r:
                selected.append(fid)
                pool.pop(idx)
                break

    logger.info(
        "red_team_findings_selected",
        total_candidates=len(candidates),
        selected_count=len(selected),
        sample_rate=sample_rate,
    )
    return selected


async def dispatch_challenge(
    conn,
    kimi_client,
    finding_id: UUID,
) -> Optional[ChallengeReport]:
    """Send a validated finding to a Red Team persona for adversarial challenge.

    Selects an active Red Team persona, builds the challenge prompt, calls
    the LLM, parses the result, and returns a ``ChallengeReport``.
    """
    # Fetch the finding
    finding_row = await conn.execute(
        sa.select(findings).where(findings.c.finding_id == finding_id)
    )
    finding = finding_row.one_or_none()
    if finding is None:
        logger.warning("dispatch_challenge_finding_not_found", finding_id=str(finding_id))
        return None

    # Select a Red Team persona (role_class = 'red_team')
    rt_q = await conn.execute(
        sa.select(agent_personas.c.persona_id)
        .where(
            agent_personas.c.role_class == "red_team",
            agent_personas.c.status == "active",
        )
        .order_by(sa.func.random())
        .limit(1)
    )
    rt_row = rt_q.one_or_none()
    if rt_row is None:
        logger.warning("dispatch_challenge_no_red_team_persona")
        return None

    challenger_persona_id = rt_row.persona_id

    # Build challenge prompt
    system_prompt, user_prompt = PromptBuilder.build_challenge_prompt(
        finding_title=finding.title,
        finding_content=finding.content,
    )

    # Create agent instance for the challenge
    inst_result = await conn.execute(
        agent_instances.insert().values(
            persona_id=challenger_persona_id,
            objective_id=finding.objective_id,
            input_prompt=user_prompt,
            spawn_reason="red_team_challenge",
            status="running",
        ).returning(agent_instances.c.instance_id)
    )
    instance_id = inst_result.scalar_one()

    try:
        kimi_response = await kimi_client.call_thinking(
            system=system_prompt,
            user=user_prompt,
        )

        challenge_data = ResponseParser.parse_challenge(kimi_response.content)

        # Update instance as completed
        await conn.execute(
            agent_instances.update()
            .where(agent_instances.c.instance_id == instance_id)
            .values(
                status="completed",
                output_content=kimi_response.content,
                thinking_content=kimi_response.reasoning,
                tokens_input=kimi_response.input_tokens,
                tokens_thinking=kimi_response.thinking_tokens,
                tokens_output=kimi_response.output_tokens,
                cost_usd=kimi_response.cost_usd,
                latency_ms=kimi_response.latency_ms,
                completed_at=sa.func.now(),
            )
        )

        report = ChallengeReport(
            has_flaw=challenge_data.has_flaw,
            flaw_type=challenge_data.flaw_type,
            description=challenge_data.description,
            counter_evidence=challenge_data.counter_evidence,
            severity=challenge_data.severity,
            confidence=challenge_data.confidence,
            challenger_persona_id=challenger_persona_id,
        )

        await emit_event(
            conn, "red_team_challenge_dispatched",
            entity_id=finding_id, entity_type="finding",
            payload={
                "challenger_persona_id": str(challenger_persona_id),
                "has_flaw": report.has_flaw,
            },
        )

        return report

    except Exception as exc:
        logger.exception(
            "dispatch_challenge_failed",
            finding_id=str(finding_id),
            challenger_persona_id=str(challenger_persona_id),
        )
        await conn.execute(
            agent_instances.update()
            .where(agent_instances.c.instance_id == instance_id)
            .values(status="failed", error_message=str(exc)[:500])
        )
        return None


async def process_challenge(
    conn,
    challenge_report: ChallengeReport,
    finding_id: UUID,
) -> None:
    """Process the outcome of a Red Team challenge.

    - If a legitimate flaw is found: reduce KG confidence, trigger propagation,
      distribute bounty to the challenger.
    - If frivolous: penalise the challenger's reputation.
    """
    if challenge_report.has_flaw:
        await _handle_legitimate_flaw(conn, challenge_report, finding_id)
    else:
        await _handle_frivolous_challenge(conn, challenge_report, finding_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _handle_legitimate_flaw(
    conn,
    report: ChallengeReport,
    finding_id: UUID,
) -> None:
    """Process a challenge that found a genuine flaw."""
    logger.info(
        "red_team_flaw_found",
        finding_id=str(finding_id),
        flaw_type=report.flaw_type,
        severity=report.severity,
    )
    severity_bonus = {
        "minor": Decimal("4.00"),
        "major": Decimal("10.00"),
        "critical": Decimal("18.00"),
    }.get(report.severity or "major", Decimal("10.00"))

    # Downgrade finding status
    await conn.execute(
        findings.update()
        .where(findings.c.finding_id == finding_id)
        .values(status="challenged")
    )

    # Reduce KG node confidence for nodes created by this finding
    finding_row = await conn.execute(
        sa.select(findings.c.kg_nodes_created, findings.c.objective_id)
        .where(findings.c.finding_id == finding_id)
    )
    finding = finding_row.one_or_none()

    if finding is not None:
        kg_node_ids = finding.kg_nodes_created or []

        # Confidence reduction depends on severity
        severity_map = {"minor": Decimal("0.05"), "major": Decimal("0.15"), "critical": Decimal("0.30")}
        reduction = severity_map.get(report.severity or "minor", Decimal("0.10"))

        for node_ref in kg_node_ids:
            node_id = node_ref if isinstance(node_ref, str) else node_ref.get("node_id", node_ref)
            try:
                node_uuid = UUID(str(node_id))
            except (ValueError, AttributeError):
                continue

            current_q = await conn.execute(
                sa.select(knowledge_graph_nodes.c.confidence_score).where(
                    knowledge_graph_nodes.c.node_id == node_uuid
                )
            )
            current_confidence = float(current_q.scalar_one())
            new_confidence = max(current_confidence - float(reduction), 0.001)

            await conn.execute(
                knowledge_graph_nodes.update()
                .where(knowledge_graph_nodes.c.node_id == node_uuid)
                .values(
                    challenge_count=knowledge_graph_nodes.c.challenge_count + 1,
                    challenge_failures=knowledge_graph_nodes.c.challenge_failures + 1,
                    confidence_score=sa.func.greatest(
                        Decimal("0.001"),
                        knowledge_graph_nodes.c.confidence_score - reduction,
                    ),
                )
            )
            await propagate_confidence(
                conn,
                challenged_node_id=node_uuid,
                new_confidence=new_confidence,
            )

    challenge_id = await open_challenge_case(
        conn,
        finding_id=finding_id,
        challenger_persona_id=report.challenger_persona_id,
        flaw_type=report.flaw_type,
        severity=report.severity,
        summary=report.description,
    )

    # Distribute bounty to challenger
    await mint_credits(
        conn,
        amount=RED_TEAM_BOUNTY + severity_bonus,
        to_persona_id=report.challenger_persona_id,
        reference_objective_id=finding.objective_id if finding else None,
        memo=f"Red Team bounty: {report.flaw_type} flaw in finding {finding_id}",
    )

    await record_capability_signal(
        conn,
        persona_id=report.challenger_persona_id,
        capability="red_team",
        outcome="success",
        magnitude=Decimal("1.10"),
    )

    await emit_event(
        conn, "red_team_flaw_confirmed",
        entity_id=finding_id, entity_type="finding",
        payload={
            "challenge_id": str(challenge_id),
            "challenger_persona_id": str(report.challenger_persona_id),
            "flaw_type": report.flaw_type,
            "severity": report.severity,
        },
    )


async def _handle_frivolous_challenge(
    conn,
    report: ChallengeReport,
    finding_id: UUID,
) -> None:
    """Penalise a challenger whose challenge was deemed frivolous."""
    logger.info(
        "red_team_frivolous_challenge",
        finding_id=str(finding_id),
        challenger_persona_id=str(report.challenger_persona_id),
    )

    # Debit penalty from challenger (append-only ledger: challenger -> sink)
    from nexus_core.models.economy import economy_ledger

    await conn.execute(
        economy_ledger.insert().values(
            from_persona_id=report.challenger_persona_id,
            to_persona_id=None,  # burned
            amount=FRIVOLOUS_PENALTY,
            transaction_type="frivolous_challenge_penalty",
            reference_finding_id=finding_id,
            memo="Penalty for frivolous Red Team challenge",
        )
    )

    await record_capability_signal(
        conn,
        persona_id=report.challenger_persona_id,
        capability="red_team",
        outcome="failure",
        magnitude=Decimal("1.00"),
    )

    # Increment challenge_count on KG nodes (survived challenge)
    finding_row = await conn.execute(
        sa.select(findings.c.kg_nodes_created)
        .where(findings.c.finding_id == finding_id)
    )
    finding = finding_row.one_or_none()
    if finding is not None:
        for node_ref in (finding.kg_nodes_created or []):
            node_id = node_ref if isinstance(node_ref, str) else node_ref.get("node_id", node_ref)
            try:
                node_uuid = UUID(str(node_id))
            except (ValueError, AttributeError):
                continue
            await conn.execute(
                knowledge_graph_nodes.update()
                .where(knowledge_graph_nodes.c.node_id == node_uuid)
                .values(challenge_count=knowledge_graph_nodes.c.challenge_count + 1)
            )

    await emit_event(
        conn, "red_team_challenge_frivolous",
        entity_id=finding_id, entity_type="finding",
        payload={"challenger_persona_id": str(report.challenger_persona_id)},
    )
