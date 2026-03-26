"""Operational scout workflow: topic derivation, persistence, and objective proposal."""

from __future__ import annotations

import math
from collections import Counter
from decimal import Decimal
from itertools import cycle

import sqlalchemy as sa
import structlog

from nexus_core.civilization.service import record_capability_signal, register_scout_source_run
from nexus_core.governance.runtime import ensure_candidate_persona_approved
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.objectives import objectives
from nexus_core.models.personas import agent_personas
from nexus_core.scouts import (
    BioRxivScout,
    ClinicalTrialsScout,
    GooglePatentsScout,
    PubMedScout,
    USPTOScout,
)
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)


SCOUT_SOURCES = {
    "pubmed": lambda settings: PubMedScout(api_key=settings.PUBMED_API_KEY),
    "clinicaltrials": lambda settings: ClinicalTrialsScout(),
    "biorxiv": lambda settings: BioRxivScout(),
    "uspto": lambda settings: USPTOScout(api_key=settings.USPTO_API_KEY),
    "google_patents": lambda settings: GooglePatentsScout(),
}


async def run_scout_sweep(
    engine,
    settings,
    source: str | None = None,
    limit_per_topic: int = 3,
) -> dict:
    """Run a scout sweep, persist relevant intelligence, and propose exploratory work."""
    if source:
        active_scouts = [SCOUT_SOURCES[source](settings)] if source in SCOUT_SOURCES else []
    else:
        active_scouts = [factory(settings) for factory in SCOUT_SOURCES.values()]

    async with engine.begin() as conn:
        active_objectives_q = await conn.execute(
            sa.select(
                objectives.c.objective_id,
                objectives.c.title,
                objectives.c.description,
            )
            .where(objectives.c.status.in_(["proposed", "active", "synthesizing"]))
            .order_by(objectives.c.priority.desc(), objectives.c.created_at.asc())
            .limit(10)
        )
        active_objectives = list(active_objectives_q)
        scout_persona_q = await conn.execute(
            sa.select(agent_personas.c.persona_id, agent_personas.c.persona_name)
            .where(
                agent_personas.c.role_class == "scout",
                agent_personas.c.status == "active",
            )
            .order_by(agent_personas.c.reputation_score.desc())
            .limit(3)
        )
        scout_personas = list(scout_persona_q)

        if active_objectives and len(scout_personas) < 2:
            await emit_event(
                conn,
                "scout_coverage_gap",
                entity_id=None,
                entity_type="scout_roster",
                payload={"active_scouts": len(scout_personas), "required_scouts": 2},
            )
            await ensure_candidate_persona_approved(
                conn,
                active_objectives[0],
                "scout",
                settings,
            )
            refreshed = await conn.execute(
                sa.select(agent_personas.c.persona_id, agent_personas.c.persona_name)
                .where(
                    agent_personas.c.role_class == "scout",
                    agent_personas.c.status == "active",
                )
                .order_by(agent_personas.c.reputation_score.desc())
                .limit(3)
            )
            scout_personas = list(refreshed)

    if not active_objectives or not scout_personas:
        return {
            "topics": [],
            "raw_findings": [],
            "persisted_findings": [],
            "proposed_objectives": 0,
        }

    topics = _derive_topics(active_objectives)
    persisted_findings = []
    proposed_objectives = 0
    raw_findings = []
    persona_cycle = cycle(scout_personas)

    try:
        for scout in active_scouts:
            persisted_for_source = 0
            proposed_for_source = 0
            try:
                results = await scout.scan_for_topics(topics, limit_per_topic=limit_per_topic)
            except NotImplementedError:
                logger.warning("scout_source_not_implemented", source=scout.source_name)
                async with engine.begin() as conn:
                    await register_scout_source_run(
                        conn,
                        source_name=scout.source_name,
                        succeeded=False,
                    )
                continue
            except Exception:
                async with engine.begin() as conn:
                    await register_scout_source_run(
                        conn,
                        source_name=scout.source_name,
                        succeeded=False,
                    )
                raise
            raw_findings.extend(results)

            for result in results:
                scout_persona = next(persona_cycle)
                matched_objective, relevance = _match_objective(result, active_objectives)
                if matched_objective is None or relevance < settings.SCOUT_RELEVANCE_THRESHOLD:
                    continue

                async with engine.begin() as conn:
                    duplicate_q = await conn.execute(
                        sa.select(findings.c.finding_id).where(
                            findings.c.finding_type == "external_intelligence",
                            findings.c.title == result.title,
                            findings.c.objective_id == matched_objective.objective_id,
                        )
                    )
                    if duplicate_q.first() is not None:
                        continue

                    report_content = _build_intelligence_report(result, relevance, matched_objective.title)
                    inst_result = await conn.execute(
                        agent_instances.insert()
                        .values(
                            persona_id=scout_persona.persona_id,
                            objective_id=matched_objective.objective_id,
                            input_prompt=f"Scout sweep: {result.source_type} -> {result.title}",
                            spawn_reason="scout_sweep",
                            status="completed",
                            output_content=report_content,
                            completed_at=sa.func.now(),
                        )
                        .returning(agent_instances.c.instance_id)
                    )
                    instance_id = inst_result.scalar_one()

                    finding_result = await conn.execute(
                        findings.insert()
                        .values(
                            objective_id=matched_objective.objective_id,
                            instance_id=instance_id,
                            finding_type="external_intelligence",
                            title=result.title,
                            content=report_content,
                            structured_data={
                                "citations": [_build_structured_citation(result)],
                                "source_url": result.source_url,
                                "source_type": result.source_type,
                                "source_name": _source_name_for_result(result.source_type),
                                "authors": result.authors,
                                "published_date": result.published_date,
                                "doi": result.doi,
                                "relevance_score": round(relevance, 3),
                                "abstract": result.abstract,
                            },
                            status="validated",
                            impact_level="routine",
                        )
                        .returning(findings.c.finding_id)
                    )
                    finding_id = finding_result.scalar_one()

                    await conn.execute(
                        objectives.insert().values(
                            title=f"Explore external signal: {result.title[:120]}",
                            description=(
                                f"Scout source: {result.source_type}\n"
                                f"Source URL: {result.source_url}\n"
                                f"Matched objective: {matched_objective.title}\n\n"
                                f"Abstract:\n{result.abstract}"
                            ),
                            objective_type="exploratory",
                            impact_level="routine",
                            priority=matched_objective.priority if hasattr(matched_objective, "priority") else 3,
                            status="proposed",
                            proposed_by_type="agent",
                            approved_by_type="self",
                            acceptance_criteria=(
                                f"Investigate intelligence report {finding_id} from {result.source_type} "
                                f"and determine whether it should alter active research direction."
                            ),
                            output_type="intelligence",
                        )
                    )
                    await emit_event(
                        conn,
                        "scout_intelligence_ingested",
                        entity_id=finding_id,
                        entity_type="finding",
                        payload={
                            "source": result.source_type,
                            "objective_id": str(matched_objective.objective_id),
                            "relevance": round(relevance, 3),
                        },
                    )
                    await record_capability_signal(
                        conn,
                        persona_id=scout_persona.persona_id,
                        capability="scout",
                        outcome="success",
                        magnitude=Decimal(str(max(relevance, 0.25))),
                    )

                proposed_objectives += 1
                persisted_for_source += 1
                proposed_for_source += 1
                persisted_findings.append(
                    {
                        "title": result.title,
                        "source": result.source_type,
                        "url": result.source_url,
                        "relevance": round(relevance, 3),
                    }
                )
            async with engine.begin() as conn:
                await register_scout_source_run(
                    conn,
                    source_name=scout.source_name,
                    succeeded=True,
                    findings_ingested=persisted_for_source,
                    objectives_proposed=proposed_for_source,
                )
    finally:
        for scout in active_scouts:
            close = getattr(scout, "close", None)
            if close is not None:
                await close()

    logger.info(
        "scout_sweep_completed",
        topics=topics,
        raw_count=len(raw_findings),
        persisted_count=len(persisted_findings),
        proposed_objectives=proposed_objectives,
    )
    return {
        "topics": topics,
        "raw_findings": raw_findings,
        "persisted_findings": persisted_findings,
        "proposed_objectives": proposed_objectives,
    }


def _derive_topics(active_objectives) -> list[str]:
    terms = []
    for objective in active_objectives:
        terms.extend(objective.title.split())
        terms.extend(objective.description.split())

    keywords = []
    stop_words = {
        "the", "and", "for", "with", "that", "this", "from", "into", "your",
        "have", "will", "what", "where", "when", "which", "about", "should",
    }
    counts = Counter(token.strip(".,:;()[]{}").lower() for token in terms if len(token) >= 4)
    for token, _count in counts.most_common(8):
        if token not in stop_words:
            keywords.append(token)

    return keywords or [objective.title for objective in active_objectives[:3]]


def _match_objective(result, active_objectives):
    best = None
    best_score = 0.0
    result_tokens = _token_set(f"{result.title} {result.abstract}")
    for objective in active_objectives:
        objective_tokens = _token_set(f"{objective.title} {objective.description}")
        if not objective_tokens:
            continue
        overlap = len(result_tokens.intersection(objective_tokens))
        score = overlap / math.sqrt(len(result_tokens) * len(objective_tokens))
        if score > best_score:
            best = objective
            best_score = score
    return best, best_score


def _token_set(text: str) -> set[str]:
    return {
        token.strip(".,:;()[]{}").lower()
        for token in text.split()
        if len(token.strip(".,:;()[]{}")) >= 4
    }


def _build_intelligence_report(result, relevance: float, matched_objective_title: str) -> str:
    return (
        f"# External Intelligence Report\n\n"
        f"## Source\n"
        f"- Type: {result.source_type}\n"
        f"- URL: {result.source_url}\n"
        f"- Published: {result.published_date or 'unknown'}\n"
        f"- Relevance: {relevance:.3f}\n\n"
        f"## Matched Objective\n"
        f"{matched_objective_title}\n\n"
        f"## Summary\n"
        f"{result.abstract or 'No abstract provided.'}"
    )


def _source_name_for_result(source_type: str) -> str:
    return {
        "pubmed": "PubMed",
        "clinicaltrials": "ClinicalTrials.gov",
        "biorxiv": "bioRxiv",
        "medrxiv": "medRxiv",
        "uspto": "USPTO",
        "google_patents": "Google Patents",
    }.get(source_type, source_type)


def _citation_source_type(source_type: str) -> str:
    return {
        "pubmed": "paper",
        "biorxiv": "paper",
        "medrxiv": "paper",
        "clinicaltrials": "trial",
        "uspto": "patent",
        "google_patents": "patent",
    }.get(source_type, "report")


def _build_structured_citation(result) -> dict:
    return {
        "title": result.title,
        "source_type": _citation_source_type(result.source_type),
        "source_name": _source_name_for_result(result.source_type),
        "url": result.source_url,
        "doi": result.doi or "",
        "published_date": result.published_date or "",
        "authors": list(result.authors or []),
        "supporting_snippet": result.abstract or "",
    }
