"""Adaptive peer review pipeline with circuit breaker for NEXUS findings."""

from __future__ import annotations

from collections import Counter
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

import pybreaker
import sqlalchemy as sa
import structlog

from nexus_core.civilization.service import (
    create_quality_holdbacks,
    record_capability_signal,
)
from nexus_core.economy.ledger import distribute_bounty, issue_participation_salary
from nexus_core.llm.client import MalformedModelResponseError
from nexus_core.llm.prompt_builder import PromptBuilder
from nexus_core.llm.response_parser import ResponseParser, ReviewData, StructuredOutputError
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.knowledge_graph import knowledge_graph_nodes
from nexus_core.models.objectives import objectives
from nexus_core.models.peer_reviews import peer_reviews
from nexus_core.models.personas import agent_personas
from nexus_core.models.civilization import objective_incentive_profiles
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)

# Circuit breaker: after 2 consecutive failures for API calls, open circuit for 5 min
_review_breaker = pybreaker.CircuitBreaker(
    fail_max=2,
    reset_timeout=300,
    name="peer_review_breaker",
)


async def _call_with_review_breaker(func, *args, **kwargs):
    """Async-safe circuit breaker wrapper for peer-review transport calls."""
    state = _review_breaker.current_state
    if state == pybreaker.STATE_OPEN:
        opened_at = _review_breaker._state_storage.opened_at
        timeout = timedelta(seconds=_review_breaker.reset_timeout)
        if opened_at and datetime.now(UTC) < opened_at + timeout:
            raise pybreaker.CircuitBreakerError(
                "Timeout not elapsed yet, circuit breaker still open"
            )
        _review_breaker.half_open()
        state = _review_breaker.current_state

    try:
        result = await func(*args, **kwargs)
    except BaseException as exc:
        if _review_breaker.is_system_error(exc):
            _review_breaker._inc_counter()
            if (
                state == pybreaker.STATE_HALF_OPEN
                or _review_breaker._state_storage.counter >= _review_breaker.fail_max
            ):
                _review_breaker.open()
        else:
            _review_breaker._state_storage.reset_counter()
        raise

    _review_breaker._state_storage.reset_counter()
    if _review_breaker.current_state == pybreaker.STATE_HALF_OPEN:
        _review_breaker.close()
    return result


@dataclass
class ReviewOutcome:
    """Result of the full peer review pipeline for a finding."""

    finding_id: UUID
    verdict: str  # "approved", "rejected", "escalated"
    reviews: list[ReviewData] = field(default_factory=list)
    consensus_score: float = 0.0
    mean_review_confidence: float = 0.0
    approval_count: int = 0
    revise_count: int = 0
    reject_count: int = 0
    support_count: int = 0
    support_ratio: float = 0.0
    reviewer_count: int = 0
    verdict_breakdown: dict[str, int] = field(default_factory=dict)
    impact_level: str = "routine"
    required_consensus: str = "majority"


class ReviewDeferredError(RuntimeError):
    """Raised when peer review cannot reach quorum because of transient failures."""


def _support_weight(verdict: str) -> float:
    """Map review verdicts to support strength for acceptance decisions."""
    return {
        "approve": 1.0,
        "revise": 0.7,
        "reject": 0.0,
    }.get(verdict, 0.0)


def _decide_review_verdict(
    impact: str,
    verdicts: list[str],
    consensus_score: float,
) -> tuple[str, int, int, int, int, float, str]:
    """Decide whether review results are sufficient for acceptance."""
    approval_count = sum(1 for verdict in verdicts if verdict == "approve")
    revise_count = sum(1 for verdict in verdicts if verdict == "revise")
    reject_count = sum(1 for verdict in verdicts if verdict == "reject")
    support_count = approval_count + revise_count
    support_ratio = (
        sum(_support_weight(verdict) for verdict in verdicts) / len(verdicts)
        if verdicts
        else 0.0
    )

    if impact == "high-impact":
        required_consensus = "two-thirds support with no rejects"
        approved = reject_count == 0 and support_ratio >= (2 / 3) and consensus_score >= 0.55
    else:
        required_consensus = "majority support"
        approved = (
            support_ratio > 0.5
            and reject_count < (len(verdicts) / 2)
            and consensus_score >= 0.45
        )

    final_verdict = "approved" if approved else "rejected"
    return (
        final_verdict,
        approval_count,
        revise_count,
        reject_count,
        support_count,
        round(support_ratio, 3),
        required_consensus,
    )


async def classify_impact(conn, finding_id: UUID) -> str:
    """Classify a finding's impact level based on its parent objective.

    Returns ``"routine"`` or ``"high-impact"``.
    """
    # Get the finding's objective_id
    finding_row = await conn.execute(
        sa.select(findings.c.objective_id, findings.c.impact_level)
        .where(findings.c.finding_id == finding_id)
    )
    row = finding_row.one_or_none()
    if row is None:
        logger.warning("classify_impact_finding_not_found", finding_id=str(finding_id))
        return "routine"

    # If the finding already has an explicit impact_level, respect it
    if row.impact_level and row.impact_level != "routine":
        return row.impact_level

    # Otherwise inherit from the parent objective
    obj_row = await conn.execute(
        sa.select(objectives.c.impact_level)
        .where(objectives.c.objective_id == row.objective_id)
    )
    obj = obj_row.one_or_none()
    if obj is None:
        return "routine"

    return obj.impact_level or "routine"


async def select_reviewers(conn, finding_id: UUID, count: int) -> list[UUID]:
    """Select reviewer persona IDs for a finding.

    Excludes the author persona's lineage (same parent_persona_id tree) and
    prefers diversity of ``role_class`` among selected reviewers.
    """
    # Determine the author persona (via the instance that created the finding)
    author_q = await conn.execute(
        sa.select(agent_instances.c.persona_id)
        .join(findings, findings.c.instance_id == agent_instances.c.instance_id)
        .where(findings.c.finding_id == finding_id)
    )
    author_row = author_q.one_or_none()
    if author_row is None:
        logger.warning("select_reviewers_no_author", finding_id=str(finding_id))
        return []

    author_persona_id = author_row.persona_id

    # Gather the author's lineage (self + parent chain) to exclude
    lineage_ids: set[UUID] = {author_persona_id}
    current_id: Optional[UUID] = author_persona_id
    while current_id is not None:
        parent_q = await conn.execute(
            sa.select(agent_personas.c.parent_persona_id)
            .where(agent_personas.c.persona_id == current_id)
        )
        parent_row = parent_q.one_or_none()
        if parent_row is None or parent_row.parent_persona_id is None:
            break
        lineage_ids.add(parent_row.parent_persona_id)
        current_id = parent_row.parent_persona_id

    # Also exclude direct children of author
    children_q = await conn.execute(
        sa.select(agent_personas.c.persona_id)
        .where(agent_personas.c.parent_persona_id == author_persona_id)
    )
    for child_row in children_q:
        lineage_ids.add(child_row.persona_id)

    # Fetch eligible active personas, ordered to maximise role_class diversity
    eligible_q = await conn.execute(
        sa.select(
            agent_personas.c.persona_id,
            agent_personas.c.role_class,
            agent_personas.c.reputation_score,
        )
        .where(
            agent_personas.c.status == "active",
            agent_personas.c.persona_id.notin_(lineage_ids),
            # Exclude special role classes that should not act as peer reviewers
            agent_personas.c.role_class.notin_(["infiltrator"]),
        )
        .order_by(agent_personas.c.reputation_score.desc())
    )

    candidates = [
        {"persona_id": r.persona_id, "role_class": r.role_class, "reputation": r.reputation_score}
        for r in eligible_q
    ]

    if not candidates:
        logger.warning("select_reviewers_no_candidates", finding_id=str(finding_id))
        return []

    # Greedy diversity selection: pick one from each role_class first, then fill
    selected: list[UUID] = []
    seen_classes: set[str] = set()

    # First pass: one per role class
    for c in candidates:
        if len(selected) >= count:
            break
        if c["role_class"] not in seen_classes:
            selected.append(c["persona_id"])
            seen_classes.add(c["role_class"])

    # Second pass: fill remaining slots by reputation (already sorted desc)
    for c in candidates:
        if len(selected) >= count:
            break
        if c["persona_id"] not in selected:
            selected.append(c["persona_id"])

    return selected[:count]


async def orchestrate_review(
    conn,
    kimi_client,
    finding_id: UUID,
) -> ReviewOutcome:
    """Full peer review pipeline for a single finding.

    Steps:
    1. Fetch the finding and parent objective
    2. Classify impact level
    3. Select reviewers (2 for routine, 3 for high-impact)
    4. Dispatch review calls via Kimi
    5. Insert peer_review rows
    6. Compute consensus
    7. Handle tie-breaker if variance > 1.5
    8. Update finding status
    9. If validated, bump KG node confidence
    10. Distribute reviewer compensation
    11. Return ReviewOutcome
    """
    # --- 1. Fetch finding ------------------------------------------------
    finding_row = await conn.execute(
        sa.select(findings).where(findings.c.finding_id == finding_id)
    )
    finding = finding_row.one_or_none()
    if finding is None:
        logger.error("orchestrate_review_finding_not_found", finding_id=str(finding_id))
        return ReviewOutcome(finding_id=finding_id, verdict="rejected")

    # Fetch parent objective
    obj_row = await conn.execute(
        sa.select(objectives).where(objectives.c.objective_id == finding.objective_id)
    )
    objective = obj_row.one_or_none()

    # --- 2. Classify impact -----------------------------------------------
    impact = await classify_impact(conn, finding_id)

    # Update finding impact_level to reflect classification
    await conn.execute(
        findings.update()
        .where(findings.c.finding_id == finding_id)
        .values(impact_level=impact)
    )

    # --- 3. Select reviewers ----------------------------------------------
    reviewer_count = 3 if impact == "high-impact" else 2
    reviewer_ids = await select_reviewers(conn, finding_id, reviewer_count)

    if len(reviewer_ids) < reviewer_count:
        logger.warning(
            "orchestrate_review_insufficient_reviewers",
            finding_id=str(finding_id),
            requested=reviewer_count,
            selected=len(reviewer_ids),
        )
        raise ReviewDeferredError(
            f"Review quorum unavailable: selected {len(reviewer_ids)}/{reviewer_count} reviewers"
        )

    # --- 4. Dispatch review calls -----------------------------------------
    completed_reviews: list[tuple[UUID, ReviewData, UUID]] = []

    for reviewer_persona_id in reviewer_ids:
        review_data, instance_id = await _dispatch_single_review(
            conn, kimi_client, finding, impact, reviewer_persona_id,
        )
        if review_data is not None and instance_id is not None:
            completed_reviews.append((reviewer_persona_id, review_data, instance_id))

    if len(completed_reviews) < reviewer_count:
        logger.warning(
            "review_quorum_unmet",
            finding_id=str(finding_id),
            requested=reviewer_count,
            completed=len(completed_reviews),
        )
        raise ReviewDeferredError(
            f"Peer review quorum not reached: completed {len(completed_reviews)}/{reviewer_count} reviews"
        )

    reviews = [review_data for _, review_data, _ in completed_reviews]

    # --- 6. Compute consensus ---------------------------------------------
    confidence_ratings = [r.confidence_rating for r in reviews]
    verdicts = [r.verdict for r in reviews]

    consensus_score = statistics.mean(confidence_ratings) if confidence_ratings else 0.0

    # Check variance for tie-breaker
    if len(confidence_ratings) >= 2:
        variance = statistics.variance(confidence_ratings)
    else:
        variance = 0.0

    # --- 7. Tie-breaker if variance > 1.5 ---------------------------------
    if variance > 1.5 and len(reviews) < 5:
        logger.info(
            "review_tie_breaker_triggered",
            finding_id=str(finding_id),
            variance=variance,
        )
        extra_reviewers = await select_reviewers(conn, finding_id, 1)
        # Filter out already-selected reviewers
        extra_reviewers = [r for r in extra_reviewers if r not in reviewer_ids]
        if extra_reviewers:
            extra_review, extra_instance_id = await _dispatch_single_review(
                conn, kimi_client, finding, impact, extra_reviewers[0],
            )
            if extra_review is not None and extra_instance_id is not None:
                completed_reviews.append(
                    (extra_reviewers[0], extra_review, extra_instance_id)
                )
                reviews.append(extra_review)
                # Recompute
                confidence_ratings = [r.confidence_rating for r in reviews]
                verdicts = [r.verdict for r in reviews]
                consensus_score = statistics.mean(confidence_ratings)

    # --- 5. Insert peer_review rows ----------------------------------------
    for reviewer_persona_id, review_data, reviewer_instance_id in completed_reviews:
        await conn.execute(
            peer_reviews.insert().values(
                finding_id=finding_id,
                reviewer_persona_id=reviewer_persona_id,
                reviewer_instance_id=reviewer_instance_id,
                methodology_critique=review_data.methodology_critique,
                evidence_evaluation=review_data.evidence_evaluation,
                novelty_assessment=review_data.novelty_assessment,
                confidence_rating=Decimal(str(round(review_data.confidence_rating, 3))),
                verdict=review_data.verdict,
                revision_feedback=review_data.revision_feedback,
            )
        )

    # --- Determine final verdict ------------------------------------------
    verdict_breakdown = dict(Counter(verdicts))
    (
        final_verdict,
        approval_count,
        revise_count,
        reject_count,
        support_count,
        support_ratio,
        required_consensus,
    ) = _decide_review_verdict(
        impact=impact,
        verdicts=verdicts,
        consensus_score=consensus_score,
    )

    # --- 8. Update finding status -----------------------------------------
    review_round_q = await conn.execute(
        sa.select(findings.c.review_round).where(findings.c.finding_id == finding_id)
    )
    current_round = review_round_q.scalar_one() or 0
    next_round = current_round + 1

    if final_verdict == "approved":
        new_status = "validated"
        outcome_verdict = "approved"
    elif next_round >= 2:
        new_status = "escalated"
        outcome_verdict = "escalated"
    else:
        new_status = "revision_requested"
        outcome_verdict = "rejected"

    await conn.execute(
        findings.update()
        .where(findings.c.finding_id == finding_id)
        .values(status=new_status, review_round=next_round)
    )

    await emit_event(
        conn, "finding_reviewed",
        entity_id=finding_id, entity_type="finding",
        payload={
            "verdict": outcome_verdict,
            "mean_review_confidence": round(consensus_score, 3),
            "consensus_score": round(consensus_score, 3),
            "approval_count": approval_count,
            "revise_count": revise_count,
            "reject_count": reject_count,
            "support_count": support_count,
            "support_ratio": support_ratio,
            "review_count": len(reviews),
            "reviewer_count": len(reviews),
            "verdict_breakdown": verdict_breakdown,
            "impact_level": impact,
            "required_consensus": required_consensus,
            "finding_status": new_status,
            "review_round": next_round,
        },
    )
    if outcome_verdict == "escalated":
        await emit_event(
            conn,
            "review_escalated",
            entity_id=finding_id,
            entity_type="finding",
            payload={"reason": "failed_twice_in_peer_review"},
        )

    # --- 8b. Issue participation salary (regardless of verdict) -------------
    try:
        # Quality gate: content > 200 chars, structured_data not null, has citations
        _content = finding.content or ""
        _structured = finding.structured_data
        _has_citations = (
            isinstance(_structured, dict)
            and isinstance(_structured.get("citations"), list)
            and len(_structured.get("citations", [])) > 0
        )
        if len(_content) > 200 and _structured is not None and _has_citations:
            # Get author persona
            _author_q = await conn.execute(
                sa.select(
                    agent_instances.c.persona_id,
                ).where(agent_instances.c.instance_id == finding.instance_id)
            )
            _author_row = _author_q.one_or_none()
            if _author_row is not None:
                # Get reputation score
                _rep_q = await conn.execute(
                    sa.select(agent_personas.c.reputation_score)
                    .where(agent_personas.c.persona_id == _author_row.persona_id)
                )
                _rep_row = _rep_q.one_or_none()
                _reputation = Decimal(str(_rep_row.reputation_score)) if _rep_row else Decimal("0.5")

                _obj_budget = Decimal(str(objective.compute_budget_allocated or 10)) if objective else Decimal("10")

                from nexus_core.config import get_settings
                _settings = get_settings()
                await issue_participation_salary(
                    conn,
                    finding_id=finding_id,
                    persona_id=_author_row.persona_id,
                    objective_budget=_obj_budget,
                    reputation_score=_reputation,
                    reference_objective_id=finding.objective_id,
                    salary_budget_rate=_settings.SALARY_BUDGET_RATE,
                    salary_min=_settings.SALARY_MIN_CREDITS,
                    salary_max=_settings.SALARY_MAX_CREDITS,
                )
    except Exception:
        logger.exception("salary_issuance_failed", finding_id=str(finding_id))

    # --- 9. If validated: boost KG node confidence -------------------------
    if final_verdict == "approved":
        kg_node_ids = finding.kg_nodes_created or []
        for node_ref in kg_node_ids:
            node_id = node_ref if isinstance(node_ref, str) else node_ref.get("node_id", node_ref)
            try:
                node_uuid = UUID(str(node_id))
            except (ValueError, AttributeError):
                continue
            # Increment validation_count and bump confidence toward consensus
            await conn.execute(
                knowledge_graph_nodes.update()
                .where(knowledge_graph_nodes.c.node_id == node_uuid)
                .values(
                    validation_count=knowledge_graph_nodes.c.validation_count + 1,
                    confidence_score=sa.func.least(
                        Decimal("0.999"),
                        knowledge_graph_nodes.c.confidence_score + Decimal(str(round(consensus_score * 0.1, 3))),
                    ),
                    status="validated",
                    last_validated=sa.func.now(),
                )
            )

    # --- 10. Distribute reviewer compensation ------------------------------
    if final_verdict == "approved" and objective is not None:
        # Get the author persona for the completer share
        author_instance_q = await conn.execute(
            sa.select(agent_instances.c.persona_id)
            .where(agent_instances.c.instance_id == finding.instance_id)
        )
        author_persona_row = author_instance_q.one_or_none()
        if author_persona_row is not None:
            bounty = objective.compute_budget_allocated or Decimal("10.00")
            bounty = Decimal(str(bounty))
            profile = (
                await conn.execute(
                    sa.select(
                        objective_incentive_profiles.c.reserve_ratio,
                        objective_incentive_profiles.c.challenge_window_minutes,
                    ).where(objective_incentive_profiles.c.objective_id == finding.objective_id)
                )
            ).first()
            reserve_ratio = Decimal(str(getattr(profile, "reserve_ratio", Decimal("0.00")) or 0))
            reserve_total = (bounty * reserve_ratio).quantize(Decimal("0.01"))
            base_bounty = bounty - reserve_total
            reviewer_ids = [
                reviewer_persona_id
                for reviewer_persona_id, _, _ in completed_reviews[: len(reviews)]
            ]
            try:
                await distribute_bounty(
                    conn,
                    objective_id=finding.objective_id,
                    finding_id=finding_id,
                    completer_persona_id=author_persona_row.persona_id,
                    reviewer_persona_ids=reviewer_ids,
                    red_team_persona_ids=[],  # Red team compensation handled separately
                    total_bounty=base_bounty,
                )
                await record_capability_signal(
                    conn,
                    persona_id=author_persona_row.persona_id,
                    capability="research",
                    outcome="bonus",
                    magnitude=Decimal("0.70"),
                )
                for reviewer_id in reviewer_ids:
                    await record_capability_signal(
                        conn,
                        persona_id=reviewer_id,
                        capability="review",
                        outcome="bonus",
                        magnitude=Decimal("0.55"),
                    )
                if reserve_total > 0:
                    challenge_window = int(
                        getattr(profile, "challenge_window_minutes", 30) or 30
                    )
                    await create_quality_holdbacks(
                        conn,
                        finding_id=finding_id,
                        objective_id=finding.objective_id,
                        author_persona_id=author_persona_row.persona_id,
                        reviewer_persona_ids=reviewer_ids,
                        total_bounty=bounty,
                        reserve_ratio=reserve_ratio,
                        release_after=datetime.now(UTC) + timedelta(minutes=challenge_window),
                    )
            except Exception:
                logger.exception("distribute_bounty_failed", finding_id=str(finding_id))

    outcome = ReviewOutcome(
        finding_id=finding_id,
        verdict=outcome_verdict,
        reviews=reviews,
        consensus_score=round(consensus_score, 3),
        mean_review_confidence=round(consensus_score, 3),
        approval_count=approval_count,
        revise_count=revise_count,
        reject_count=reject_count,
        support_count=support_count,
        support_ratio=support_ratio,
        reviewer_count=len(reviews),
        verdict_breakdown=verdict_breakdown,
        impact_level=impact,
        required_consensus=required_consensus,
    )
    logger.info(
        "review_completed",
        finding_id=str(finding_id),
        verdict=outcome_verdict,
        mean_review_confidence=outcome.mean_review_confidence,
        approval_count=outcome.approval_count,
        revise_count=outcome.revise_count,
        reject_count=outcome.reject_count,
        support_count=outcome.support_count,
        support_ratio=outcome.support_ratio,
        reviewer_count=outcome.reviewer_count,
        verdict_breakdown=outcome.verdict_breakdown,
        impact_level=outcome.impact_level,
        required_consensus=outcome.required_consensus,
    )
    return outcome


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _dispatch_single_review(
    conn,
    kimi_client,
    finding,
    impact_level: str,
    reviewer_persona_id: UUID,
) -> tuple[Optional[ReviewData], Optional[UUID]]:
    """Dispatch a single review call through the circuit breaker.

    Returns ``(ReviewData, instance_id)`` on success or ``(None, None)`` on
    failure / circuit-breaker open.
    """
    # Build review prompt (include citation score if available)
    citation_score = float(getattr(finding, "citation_confidence_score", None) or 0.5)
    system_prompt, user_prompt = PromptBuilder.build_review_prompt(
        finding_title=finding.title,
        finding_content=finding.content,
        impact_level=impact_level,
        citation_confidence_score=citation_score,
    )

    # Create an agent_instance record for the reviewer
    instance_result = await conn.execute(
        agent_instances.insert().values(
            persona_id=reviewer_persona_id,
            objective_id=finding.objective_id,
            input_prompt=user_prompt,
            spawn_reason="peer_review",
            status="running",
        ).returning(agent_instances.c.instance_id)
    )
    instance_id = instance_result.scalar_one()

    last_structured_error: str | None = None
    last_output_content: str | None = None

    try:
        for attempt in range(2):
            attempt_prompt = user_prompt
            if attempt > 0:
                attempt_prompt += (
                    "\n\nIMPORTANT: Your previous response was invalid or incomplete JSON. "
                    "Return COMPLETE valid raw JSON only, with all strings closed and no "
                    "markdown fences or commentary."
                )

            try:
                kimi_response = await _call_with_review_breaker(
                    kimi_client.call_thinking,
                    system=system_prompt,
                    user=attempt_prompt,
                )
                last_output_content = kimi_response.content
                review_data = ResponseParser.parse_review(
                    kimi_response.content,
                    strict=True,
                )
                break
            except (MalformedModelResponseError, StructuredOutputError) as exc:
                last_structured_error = str(exc)
                logger.warning(
                    "review_structured_output_invalid",
                    finding_id=str(finding.finding_id),
                    reviewer_persona_id=str(reviewer_persona_id),
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt == 1:
                    raise
        else:
            raise StructuredOutputError(
                last_structured_error or "Review response remained invalid after retry"
            )

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
        return review_data, instance_id

    except pybreaker.CircuitBreakerError:
        logger.warning(
            "review_circuit_breaker_open",
            finding_id=str(finding.finding_id),
            reviewer_persona_id=str(reviewer_persona_id),
        )
        await conn.execute(
            agent_instances.update()
            .where(agent_instances.c.instance_id == instance_id)
            .values(status="failed", error_message="Circuit breaker open - review deferred for retry")
        )
        return None, None

    except (MalformedModelResponseError, StructuredOutputError) as exc:
        logger.error(
            "review_structured_output_failed",
            finding_id=str(finding.finding_id),
            reviewer_persona_id=str(reviewer_persona_id),
            error=str(exc),
        )
        await conn.execute(
            agent_instances.update()
            .where(agent_instances.c.instance_id == instance_id)
            .values(
                status="failed",
                output_content=last_output_content,
                error_message=str(exc)[:500],
            )
        )
        return None, None

    except Exception as exc:
        logger.exception(
            "review_call_failed",
            finding_id=str(finding.finding_id),
            reviewer_persona_id=str(reviewer_persona_id),
        )
        await conn.execute(
            agent_instances.update()
            .where(agent_instances.c.instance_id == instance_id)
            .values(status="failed", error_message=str(exc)[:500])
        )
        return None, None
