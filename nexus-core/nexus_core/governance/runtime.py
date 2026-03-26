"""Runtime governance helpers for persona activation and proposal processing."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
import structlog

from nexus_core.config import NexusSettings
from nexus_core.economy.ledger import mint_credits
from nexus_core.governance.proposals import create_proposal, get_pending_proposals
from nexus_core.governance.voting import execute_outcome, tally_votes, cast_vote
from nexus_core.models.governance import governance_votes
from nexus_core.models.personas import agent_personas
from nexus_core.utils.embeddings import EmbeddingService

logger = structlog.get_logger(__name__)


ROLE_TEMPLATES = {
    "researcher": (
        "You are a specialist research agent in the NEXUS civilization. "
        "Your job is to gather evidence, compare sources, and produce structured findings."
    ),
    "synthesizer": (
        "You are a systems synthesizer in the NEXUS civilization. "
        "Your job is to integrate multiple findings into coherent analysis and recommendations."
    ),
    "critic": (
        "You are a critical analysis agent in the NEXUS civilization. "
        "Your job is to stress-test assumptions, identify flaws, and strengthen conclusions."
    ),
    "scout": (
        "You are an external intelligence scout in the NEXUS civilization. "
        "Your job is to monitor external sources and report high-value developments."
    ),
    "debugger": (
        "You are a diagnostic debugger in the NEXUS civilization. "
        "Your job is to analyze failures and record corrective guidance."
    ),
    "governor": (
        "You are a governor in the NEXUS civilization. "
        "Your job is to evaluate proposals, balance risk, and protect system quality."
    ),
}


async def ensure_candidate_persona_approved(
    conn,
    objective,
    required_role_class: str,
    settings: NexusSettings,
):
    """Create and immediately process a candidate persona proposal when the roster has a gap."""
    candidate_name = _candidate_persona_name(required_role_class, objective.objective_id)
    existing = await conn.execute(
        agent_personas.select().where(agent_personas.c.persona_name == candidate_name)
    )
    persona = existing.first()
    if persona is None:
        proposer_id = await _select_proposer_persona(conn)
        if proposer_id is None:
            logger.warning(
                "candidate_persona_no_proposer",
                objective_id=str(objective.objective_id),
                required_role_class=required_role_class,
            )
            return None

        prompt = _build_candidate_prompt(
            required_role_class,
            objective.title,
            objective.description,
        )
        result = await conn.execute(
            agent_personas.insert()
            .values(
                persona_name=candidate_name,
                role_class=required_role_class,
                system_prompt_template=prompt,
                status="candidate",
                reputation_score=Decimal("0.500"),
                autonomy_level=3,
                specialization_vector=EmbeddingService.hash_encode(
                    f"{required_role_class} {objective.title} {objective.description}"
                ).tolist(),
                mutation_diff={
                    "source_objective_id": str(objective.objective_id),
                    "activation_reason": "persona_gap_for_dispatch",
                },
            )
            .returning(agent_personas.c.persona_id)
        )
        candidate_id = result.scalar_one()
        await mint_credits(
            conn,
            Decimal("50.00"),
            candidate_id,
            memo="Initial candidate persona balance",
        )
        proposal_id = await create_proposal(
            conn,
            proposer_id=proposer_id,
            proposal_type="activate_persona",
            title=f"Activate candidate {candidate_name}",
            description=(
                f"Objective '{objective.title}' requires a {required_role_class} persona, "
                f"and no sufficiently specialized active persona was available."
            ),
            rationale=(
                f"Create and activate a {required_role_class} candidate to execute "
                f"objective {objective.objective_id}."
            ),
            target_persona_id=candidate_id,
        )
        logger.info(
            "candidate_persona_proposed",
            candidate_id=str(candidate_id),
            proposal_id=str(proposal_id),
            objective_id=str(objective.objective_id),
            required_role_class=required_role_class,
        )
    else:
        candidate_id = persona.persona_id

    await process_pending_proposals(conn, settings)

    approved = await conn.execute(
        agent_personas.select().where(
            agent_personas.c.persona_id == candidate_id,
            agent_personas.c.status == "active",
        )
    )
    return approved.first()


async def process_pending_proposals(
    conn,
    settings: NexusSettings,
) -> list:
    """Apply lightweight governor voting to pending proposals and execute outcomes."""
    proposals = await get_pending_proposals(conn)
    if not proposals:
        return []

    governors_q = await conn.execute(
        sa.select(
            agent_personas.c.persona_id,
            agent_personas.c.persona_name,
            agent_personas.c.reputation_score,
        )
        .where(
            agent_personas.c.role_class == "governor",
            agent_personas.c.status == "active",
        )
        .order_by(agent_personas.c.reputation_score.desc())
        .limit(3)
    )
    governors = list(governors_q)
    outcomes = []

    if not governors:
        logger.warning("governance_cycle_no_active_governors", pending=len(proposals))
        return outcomes

    for proposal in proposals:
        existing_votes_q = await conn.execute(
            sa.select(governance_votes.c.voter_persona_id).where(
                governance_votes.c.proposal_id == proposal["proposal_id"]
            )
        )
        existing_voters = {row.voter_persona_id for row in existing_votes_q}

        for governor in governors:
            if governor.persona_id in existing_voters:
                continue
            vote, reasoning = await _recommend_vote(
                conn,
                proposal,
                governor.persona_name,
                settings,
            )
            await cast_vote(
                conn,
                proposal_id=proposal["proposal_id"],
                voter_persona_id=governor.persona_id,
                vote=vote,
                reasoning=reasoning,
            )

        outcome = await tally_votes(conn, proposal["proposal_id"])
        await execute_outcome(conn, proposal["proposal_id"], outcome)
        outcomes.append(outcome)

    return outcomes


async def _recommend_vote(
    conn,
    proposal: dict,
    governor_name: str,
    settings: NexusSettings,
) -> tuple[str, str]:
    """Apply deterministic governance heuristics for proposal voting."""
    proposal_type = proposal["proposal_type"]

    if proposal_type == "activate_persona" and proposal.get("target_persona_id") is not None:
        persona_q = await conn.execute(
            agent_personas.select().where(
                agent_personas.c.persona_id == proposal["target_persona_id"]
            )
        )
        persona = persona_q.first()
        if persona is None:
            return "reject", f"{governor_name}: target persona does not exist."

        active_count_q = await conn.execute(
            sa.select(sa.func.count())
            .select_from(agent_personas)
            .where(
                agent_personas.c.role_class == persona.role_class,
                agent_personas.c.status == "active",
            )
        )
        active_count = active_count_q.scalar_one()

        quality_score = 0
        reasons = []
        if persona.status == "candidate":
            quality_score += 1
            reasons.append("candidate persona exists")
        if len(persona.system_prompt_template or "") >= 180:
            quality_score += 1
            reasons.append("prompt is sufficiently detailed")
        if persona.specialization_vector is not None:
            quality_score += 1
            reasons.append("specialization vector is present")
        if active_count < settings.MIN_PERSONAS_PER_ROLE_CLASS:
            quality_score += 1
            reasons.append("role class is below minimum population")
        if persona.mutation_diff:
            quality_score += 1
            reasons.append("proposal includes objective provenance")

        vote = "approve" if quality_score >= 3 else "reject"
        rationale = (
            f"{governor_name}: {vote} activation for role {persona.role_class}; "
            + ", ".join(reasons or ["candidate quality is insufficient"])
        )
        return vote, rationale

    if proposal_type == "deprecate_persona":
        return "approve", f"{governor_name}: approve deprecation proposal."

    if proposal_type in {"rule_change", "parameter_update"}:
        return "abstain", f"{governor_name}: abstain pending explicit operator review."

    return "reject", f"{governor_name}: unsupported proposal type {proposal_type!r}."


async def _select_proposer_persona(conn) -> UUID | None:
    """Select a governance-capable proposer persona for a new proposal."""
    for role_class in ("governor", "originator"):
        result = await conn.execute(
            sa.select(agent_personas.c.persona_id)
            .where(
                agent_personas.c.role_class == role_class,
                agent_personas.c.status == "active",
            )
            .order_by(agent_personas.c.reputation_score.desc())
            .limit(1)
        )
        row = result.one_or_none()
        if row is not None:
            return row.persona_id

    result = await conn.execute(
        sa.select(agent_personas.c.persona_id)
        .where(agent_personas.c.status == "active")
        .order_by(agent_personas.c.reputation_score.desc())
        .limit(1)
    )
    row = result.one_or_none()
    return row.persona_id if row is not None else None


def _candidate_persona_name(required_role_class: str, objective_id: UUID) -> str:
    return f"Candidate {required_role_class.title()} {str(objective_id)[:8]}"


def _build_candidate_prompt(
    required_role_class: str,
    objective_title: str,
    objective_description: str,
) -> str:
    base_prompt = ROLE_TEMPLATES.get(
        required_role_class,
        "You are a specialist agent in the NEXUS civilization.",
    )
    return (
        f"{base_prompt}\n\n"
        f"Primary assignment profile:\n"
        f"- Role class: {required_role_class}\n"
        f"- Focus objective: {objective_title}\n"
        f"- Objective context: {objective_description}\n\n"
        f"Produce disciplined, evidence-oriented outputs and preserve provenance."
    )
