from __future__ import annotations

import json
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa

from nexus_core.economy.ledger import mint_credits
from nexus_core.knowledge.graph_ops import create_edge, create_node, normalize_canonical_label
from nexus_core.knowledge.repair import repair_duplicate_nodes
from nexus_core.knowledge.query import find_similar_nodes
from nexus_core.llm.client import KimiResponse
from nexus_core.models.decomposition import objective_decomposition
from nexus_core.models.economy import economy_ledger
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.knowledge_graph import knowledge_graph_edges, knowledge_graph_nodes
from nexus_core.models.objectives import objectives
from nexus_core.models.peer_reviews import peer_reviews
from nexus_core.models.personas import agent_personas
from nexus_core.models.telemetry import agent_telemetry
from nexus_core.review.peer_review import _review_breaker
from nexus_core.utils.embeddings import EmbeddingService


DECOMPOSITION_JSON = json.dumps(
    {
        "sub_objectives": [
            {
                "id": "research_branch",
                "title": "Survey recent quantum decoder literature",
                "description": "Collect recent evidence about neural and surface-code decoders.",
                "role_class": "researcher",
                "dependency_type": "parallel",
                "depends_on": [],
                "impact_level": "routine",
                "rationale": "Establishes the evidence base.",
            },
            {
                "id": "synthesis_branch",
                "title": "Synthesize decoder trade-offs",
                "description": "Combine the literature into a trade-off analysis.",
                "role_class": "synthesizer",
                "dependency_type": "sequential",
                "depends_on": ["research_branch"],
                "impact_level": "routine",
                "rationale": "Turns findings into actionable synthesis.",
            },
            {
                "id": "critique_branch",
                "title": "Critique scaling assumptions",
                "description": "Stress-test the scaling assumptions in the synthesis.",
                "role_class": "critic",
                "dependency_type": "sequential",
                "depends_on": ["synthesis_branch"],
                "impact_level": "routine",
                "rationale": "Ensures the conclusion is robust.",
            },
        ]
    }
)

FINDING_PAYLOADS = [
    {
        "title": "Neural decoders reduce logical error rates",
        "content": "Neural decoders showed lower logical error rates in large surface-code simulations.",
        "confidence": 0.81,
        "citations": [
            {
                "title": "Neural decoder benchmark",
                "source_type": "paper",
                "source_name": "Quantum Journal",
                "url": "https://example.com/neural-decoder",
                "doi": "10.1234/qec.2026.0001",
                "published_date": "2026-03-19",
                "authors": ["Researcher A"],
                "supporting_snippet": "Neural decoders lowered logical error rates in simulation.",
            }
        ],
        "kg_contribution": {
            "entities": [
                {"label": "Neural Decoder", "type": "concept", "properties": {"domain": "QEC"}},
                {"label": "Surface Code", "type": "concept", "properties": {"domain": "QEC"}},
            ],
            "relationships": [
                {
                    "source": "Neural Decoder",
                    "target": "Surface Code",
                    "type": "improves",
                    "weight": 0.81,
                }
            ],
        },
    },
    {
        "title": "Surface-code decoders trade throughput for fidelity",
        "content": "The best-performing decoders increase fidelity but add latency at scale.",
        "confidence": 0.79,
        "citations": [
            {
                "title": "Decoder throughput benchmark",
                "source_type": "paper",
                "source_name": "arXiv",
                "url": "https://example.com/decoder-throughput",
                "doi": "",
                "published_date": "2026-03-18",
                "authors": ["Researcher B"],
                "supporting_snippet": "Higher-fidelity decoders incurred more latency at scale.",
            }
        ],
        "kg_contribution": {
            "entities": [
                {"label": "Decoder Latency", "type": "metric", "properties": {"domain": "QEC"}},
                {"label": "Logical Fidelity", "type": "metric", "properties": {"domain": "QEC"}},
            ],
            "relationships": [
                {
                    "source": "Decoder Latency",
                    "target": "Logical Fidelity",
                    "type": "trades_off_with",
                    "weight": 0.79,
                }
            ],
        },
    },
    {
        "title": "Hardware assumptions remain underconstrained",
        "content": "Several published decoder benchmarks rely on hardware assumptions that remain unverified.",
        "confidence": 0.76,
        "citations": [
            {
                "title": "Hardware assumption critique",
                "source_type": "report",
                "source_name": "NEXUS Internal Review",
                "url": "https://example.com/hardware-assumptions",
                "doi": "",
                "published_date": "2026-03-17",
                "authors": ["Reviewer C"],
                "supporting_snippet": "Published decoder benchmarks rely on unverified hardware assumptions.",
            }
        ],
        "kg_contribution": {
            "entities": [
                {"label": "Hardware Assumption", "type": "risk", "properties": {"domain": "QEC"}},
                {"label": "Benchmark Validity", "type": "concept", "properties": {"domain": "QEC"}},
            ],
            "relationships": [
                {
                    "source": "Hardware Assumption",
                    "target": "Benchmark Validity",
                    "type": "constrains",
                    "weight": 0.76,
                }
            ],
        },
    },
]

REVIEW_APPROVE_JSON = json.dumps(
    {
        "methodology_critique": "The methodology is disciplined and appropriately scoped.",
        "evidence_evaluation": "The evidence is sufficient for a routine finding.",
        "novelty_assessment": "The contribution is incremental but useful.",
        "confidence_rating": 0.85,
        "verdict": "approve",
        "revision_feedback": None,
    }
)

SYNTHESIS_MARKDOWN = """# Final Synthesis

Neural decoders improve fidelity, but the gains come with latency trade-offs and unresolved hardware assumptions.
"""


def _kimi_response(content: str) -> KimiResponse:
    return KimiResponse(
        content=content,
        reasoning="reasoning",
        input_tokens=200,
        thinking_tokens=120,
        output_tokens=160,
        cost_usd=Decimal("0.000000"),
        latency_ms=180,
        model="kimi-k2.5",
        prompt_hash=str(uuid4()).replace("-", ""),
    )


async def _seed_persona(conn, *, name: str, role_class: str, reputation: str) -> None:
    result = await conn.execute(
        agent_personas.insert()
        .values(
            persona_name=name,
            role_class=role_class,
            system_prompt_template=f"You are the {role_class} persona for NEXUS.",
            reputation_score=Decimal(reputation),
            status="active",
        )
        .returning(agent_personas.c.persona_id)
    )
    persona_id = result.scalar_one()
    await mint_credits(
        conn,
        Decimal("100.00"),
        persona_id,
        memo=f"Seed balance for {name}",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_objective_lifecycle_runs_against_real_postgres(clean_database, settings):
    engine = clean_database
    parent_objective_id = uuid4()

    async with engine.begin() as conn:
        await _seed_persona(conn, name="Research Persona", role_class="researcher", reputation="0.900")
        await _seed_persona(conn, name="Synthesis Persona", role_class="synthesizer", reputation="0.850")
        await _seed_persona(conn, name="Critic Persona", role_class="critic", reputation="0.800")
        await conn.execute(
            objectives.insert().values(
                objective_id=parent_objective_id,
                title="Evaluate quantum decoder strategies",
                description="Assess decoder quality, trade-offs, and scaling risks.",
                objective_type="strategic",
                impact_level="routine",
                priority=8,
                status="proposed",
                proposed_by_type="human",
                compute_budget_allocated=Decimal("30.00"),
            )
        )

    kimi = AsyncMock()
    kimi.call_thinking = AsyncMock(
        side_effect=[
            _kimi_response(DECOMPOSITION_JSON),
            *[_kimi_response(json.dumps(payload)) for payload in FINDING_PAYLOADS],
            *[_kimi_response(REVIEW_APPROVE_JSON) for _ in range(6)],
            _kimi_response(SYNTHESIS_MARKDOWN),
        ]
    )

    from nexus_engine.decomposer import decompose_objective
    from nexus_engine.dispatcher import Dispatcher
    from nexus_engine.integrator import integrate_results

    _review_breaker.close()

    sub_objectives = await decompose_objective(
        engine=engine,
        kimi_client=kimi,
        objective_id=parent_objective_id,
        settings=settings,
    )
    assert len(sub_objectives) == 3

    dispatcher = Dispatcher(
        engine=engine,
        kimi_client=kimi,
        settings=settings,
        shutdown_event=asyncio.Event(),
    )
    await dispatcher.dispatch_dag(parent_objective_id)

    async with engine.begin() as conn:
        decomposition_count = await conn.scalar(
            sa.select(sa.func.count()).select_from(objective_decomposition)
        )
        pending_findings = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(findings)
            .where(findings.c.status == "pending_review")
        )
        dispatched_instances = (
            await conn.execute(
                sa.select(agent_instances.c.instance_id)
                .join(objectives, objectives.c.objective_id == agent_instances.c.objective_id)
                .where(objectives.c.parent_objective_id == parent_objective_id)
                .order_by(agent_instances.c.started_at.asc())
            )
        ).scalars().all()

    assert decomposition_count == 3
    assert pending_findings == 3
    assert len(dispatched_instances) == 3

    for instance_id in dispatched_instances:
        await integrate_results(
            engine=engine,
            kimi_client=kimi,
            instance_id=instance_id,
            settings=settings,
        )

    async with engine.begin() as conn:
        parent = (
            await conn.execute(
                sa.select(objectives).where(objectives.c.objective_id == parent_objective_id)
            )
        ).first()
        child_statuses = (
            await conn.execute(
                sa.select(objectives.c.status)
                .where(objectives.c.parent_objective_id == parent_objective_id)
            )
        ).scalars().all()
        review_count = await conn.scalar(
            sa.select(sa.func.count()).select_from(peer_reviews)
        )
        telemetry_count = await conn.scalar(
            sa.select(sa.func.count()).select_from(agent_telemetry)
        )
        kg_node_count = await conn.scalar(
            sa.select(sa.func.count()).select_from(knowledge_graph_nodes)
        )
        economy_count = await conn.scalar(
            sa.select(sa.func.count()).select_from(economy_ledger)
        )
        synthesis_findings = (
            await conn.execute(
                sa.select(findings.c.finding_type, findings.c.status)
                .where(findings.c.objective_id == parent_objective_id)
            )
        ).all()

    assert parent.status == "completed"
    assert child_statuses == ["completed", "completed", "completed"]
    assert review_count == 6
    assert telemetry_count == 4
    assert kg_node_count >= 2
    assert economy_count >= 3
    assert ("synthesis", "validated") in synthesis_findings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_knowledge_graph_embeddings_support_real_dedup_and_similarity(clean_database):
    engine = clean_database
    objective_id = uuid4()
    persona_id = uuid4()

    async with engine.begin() as conn:
        await conn.execute(
            agent_personas.insert().values(
                persona_id=persona_id,
                persona_name="KG Persona",
                role_class="researcher",
                system_prompt_template="You work on knowledge graph ingestion.",
                status="active",
            )
        )
        await conn.execute(
            objectives.insert().values(
                objective_id=objective_id,
                title="KG objective",
                description="Support KG dedup tests.",
                objective_type="strategic",
                status="proposed",
                proposed_by_type="human",
            )
        )
        instance_id = await conn.scalar(
            agent_instances.insert()
            .values(
                persona_id=persona_id,
                objective_id=objective_id,
                input_prompt="Insert KG nodes",
                status="completed",
            )
            .returning(agent_instances.c.instance_id)
        )

        node_id, is_new = await create_node(
            conn,
            label="Surface Code",
            node_type="concept",
            properties={"domain": "QEC"},
            confidence=0.8,
            objective_id=objective_id,
            instance_id=instance_id,
        )
        duplicate_id, duplicate_is_new = await create_node(
            conn,
            label="Surface-Code",
            node_type="concept",
            properties={"domain": "QEC", "source": "paper"},
            confidence=0.9,
            objective_id=objective_id,
            instance_id=instance_id,
        )

        node_count = await conn.scalar(
            sa.select(sa.func.count()).select_from(knowledge_graph_nodes)
        )
        stored_embedding = await conn.scalar(
            sa.select(knowledge_graph_nodes.c.properties_embedding)
            .where(knowledge_graph_nodes.c.node_id == node_id)
        )
        node_row = (
            await conn.execute(
                sa.select(
                    knowledge_graph_nodes.c.canonical_label,
                    knowledge_graph_nodes.c.properties,
                ).where(knowledge_graph_nodes.c.node_id == node_id)
            )
        ).first()
        similar_nodes = await find_similar_nodes(
            conn,
            EmbeddingService.hash_encode('concept Surface Code {"domain": "QEC"}'),
            threshold=0.80,
            limit=3,
        )

    assert is_new is True
    assert duplicate_is_new is False
    assert duplicate_id == node_id
    assert node_count == 1
    assert stored_embedding is not None
    assert node_row.canonical_label == "surface code"
    assert node_row.properties["source"] == "paper"
    assert sorted(node_row.properties["aliases"]) == ["Surface Code", "Surface-Code"]
    assert any(row["node_id"] == node_id for row in similar_nodes)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_edge_merges_duplicate_edges(clean_database):
    engine = clean_database
    objective_id = uuid4()
    persona_id = uuid4()

    async with engine.begin() as conn:
        await conn.execute(
            agent_personas.insert().values(
                persona_id=persona_id,
                persona_name="Edge Persona",
                role_class="researcher",
                system_prompt_template="You work on knowledge graph ingestion.",
                status="active",
            )
        )
        await conn.execute(
            objectives.insert().values(
                objective_id=objective_id,
                title="KG edge objective",
                description="Support KG edge merge tests.",
                objective_type="strategic",
                status="proposed",
                proposed_by_type="human",
            )
        )
        instance_id = await conn.scalar(
            agent_instances.insert()
            .values(
                persona_id=persona_id,
                objective_id=objective_id,
                input_prompt="Insert KG edges",
                status="completed",
            )
            .returning(agent_instances.c.instance_id)
        )
        source_id, _ = await create_node(
            conn,
            label="Senolytic",
            node_type="intervention",
            properties={},
            confidence=0.8,
            objective_id=objective_id,
            instance_id=instance_id,
        )
        target_id, _ = await create_node(
            conn,
            label="Inflammaging",
            node_type="mechanism",
            properties={},
            confidence=0.8,
            objective_id=objective_id,
            instance_id=instance_id,
        )

        edge_id = await create_edge(
            conn,
            source_node_id=source_id,
            target_node_id=target_id,
            relationship_type="improves",
            weight=0.61,
            confidence=0.67,
            evidence_ids=["finding-a"],
            objective_id=objective_id,
        )
        duplicate_edge_id = await create_edge(
            conn,
            source_node_id=source_id,
            target_node_id=target_id,
            relationship_type="improves",
            weight=0.75,
            confidence=0.71,
            evidence_ids=["finding-b"],
            objective_id=objective_id,
        )

        edge_rows = (
            await conn.execute(sa.select(knowledge_graph_edges))
        ).fetchall()

    assert duplicate_edge_id == edge_id
    assert len(edge_rows) == 1
    assert float(edge_rows[0].weight) == pytest.approx(0.75)
    assert float(edge_rows[0].confidence_score) == pytest.approx(0.71)
    assert edge_rows[0].evidence_ids == ["finding-a", "finding-b"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repair_duplicate_nodes_rewrites_refs_and_is_idempotent(clean_database):
    engine = clean_database
    objective_id = uuid4()
    persona_id = uuid4()

    async with engine.begin() as conn:
        await conn.execute(
            agent_personas.insert().values(
                persona_id=persona_id,
                persona_name="Repair Persona",
                role_class="researcher",
                system_prompt_template="You repair the KG.",
                status="active",
            )
        )
        await conn.execute(
            objectives.insert().values(
                objective_id=objective_id,
                title="KG repair objective",
                description="Support KG repair tests.",
                objective_type="strategic",
                status="proposed",
                proposed_by_type="human",
            )
        )
        instance_id = await conn.scalar(
            agent_instances.insert()
            .values(
                persona_id=persona_id,
                objective_id=objective_id,
                input_prompt="Repair KG",
                status="completed",
            )
            .returning(agent_instances.c.instance_id)
        )

        primary_node_id = await conn.scalar(
            knowledge_graph_nodes.insert()
            .values(
                node_type="mechanism",
                label="IL-6",
                canonical_label=normalize_canonical_label("IL-6"),
                properties={"aliases": ["Interleukin 6"]},
                confidence_score=Decimal("0.800"),
                discovered_by_objective_id=objective_id,
                discovered_by_instance_id=instance_id,
                status="validated",
            )
            .returning(knowledge_graph_nodes.c.node_id)
        )
        duplicate_node_id = await conn.scalar(
            knowledge_graph_nodes.insert()
            .values(
                node_type="mechanism",
                label="IL 6",
                canonical_label=normalize_canonical_label("IL 6"),
                properties={},
                confidence_score=Decimal("0.900"),
                discovered_by_objective_id=objective_id,
                discovered_by_instance_id=instance_id,
                status="validated",
            )
            .returning(knowledge_graph_nodes.c.node_id)
        )
        target_node_id = await conn.scalar(
            knowledge_graph_nodes.insert()
            .values(
                node_type="outcome",
                label="Inflammation",
                canonical_label=normalize_canonical_label("Inflammation"),
                properties={},
                confidence_score=Decimal("0.700"),
                discovered_by_objective_id=objective_id,
                discovered_by_instance_id=instance_id,
                status="validated",
            )
            .returning(knowledge_graph_nodes.c.node_id)
        )

        primary_edge_id = await conn.scalar(
            knowledge_graph_edges.insert()
            .values(
                source_node_id=primary_node_id,
                target_node_id=target_node_id,
                relationship_type="causes",
                weight=Decimal("0.600"),
                confidence_score=Decimal("0.610"),
                evidence_ids=["finding-primary"],
                discovered_by_objective_id=objective_id,
                status="validated",
            )
            .returning(knowledge_graph_edges.c.edge_id)
        )
        duplicate_edge_id = await conn.scalar(
            knowledge_graph_edges.insert()
            .values(
                source_node_id=duplicate_node_id,
                target_node_id=target_node_id,
                relationship_type="causes",
                weight=Decimal("0.900"),
                confidence_score=Decimal("0.920"),
                evidence_ids=["finding-duplicate"],
                discovered_by_objective_id=objective_id,
                status="validated",
            )
            .returning(knowledge_graph_edges.c.edge_id)
        )

        finding_id = await conn.scalar(
            findings.insert()
            .values(
                objective_id=objective_id,
                instance_id=instance_id,
                finding_type="research",
                title="IL-6 supports inflammaging",
                content="Structured finding for repair testing.",
                structured_data={
                    "citations": [],
                    "kg_entities": [],
                    "kg_relationships": [],
                },
                status="validated",
                kg_nodes_created=[str(primary_node_id), str(duplicate_node_id)],
                kg_edges_created=[str(primary_edge_id), str(duplicate_edge_id)],
            )
            .returning(findings.c.finding_id)
        )

        summary = await repair_duplicate_nodes(conn, dry_run=False)
        second_summary = await repair_duplicate_nodes(conn, dry_run=False)

        remaining_nodes = (
            await conn.execute(
                sa.select(
                    knowledge_graph_nodes.c.node_id,
                    knowledge_graph_nodes.c.label,
                    knowledge_graph_nodes.c.properties,
                ).order_by(knowledge_graph_nodes.c.label.asc())
            )
        ).fetchall()
        remaining_edges = (
            await conn.execute(sa.select(knowledge_graph_edges))
        ).fetchall()
        finding_row = (
            await conn.execute(
                sa.select(findings.c.kg_nodes_created, findings.c.kg_edges_created)
                .where(findings.c.finding_id == finding_id)
            )
        ).first()

    assert summary.merged_node_count == 1
    assert summary.deleted_node_count == 1
    assert summary.deleted_edge_count >= 1
    assert second_summary.merged_node_count == 0
    assert second_summary.deleted_node_count == 0
    assert len(remaining_nodes) == 2
    assert len(remaining_edges) == 1
    surviving_mechanism = next(
        row
        for row in remaining_nodes
        if row.label in {"IL-6", "IL 6"}
    )
    assert set(surviving_mechanism.properties["aliases"]) >= {"IL-6", "IL 6", "Interleukin 6"}
    assert finding_row.kg_nodes_created == [str(surviving_mechanism.node_id)]
    assert finding_row.kg_edges_created == [str(remaining_edges[0].edge_id)]
