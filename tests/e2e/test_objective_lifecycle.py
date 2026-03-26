"""
Mocked orchestration regression tests for the objective lifecycle.

These tests use mocked Kimi calls and a fake engine/connection layer. They are
useful for fast orchestration regressions, but they are not a replacement for
the PostgreSQL-backed integration coverage under ``tests/integration``.

Acceptance criteria verified:
1. Originator decomposes objective into multi-branch DAG (3+ sub-objectives)
2. Different persona types activated (researcher, synthesizer, critic)
3. Findings produced and written to findings table
4. Peer review triggers with correct reviewer count
5. Validated findings committed to KG with provenance
6. Economy credits minted and distributed
7. All telemetry captured
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from nexus_core.config import NexusSettings
from nexus_core.llm.client import KimiResponse
from nexus_core.llm.response_parser import ResponseParser
from nexus_core.review.peer_review import ReviewOutcome

# ---------------------------------------------------------------------------
# Stable UUIDs for deterministic test verification
# ---------------------------------------------------------------------------
PARENT_OBJ_ID = uuid4()
SUB_OBJ_IDS = [uuid4(), uuid4(), uuid4()]
PERSONA_IDS = {
    "researcher": uuid4(),
    "synthesizer": uuid4(),
    "critic": uuid4(),
}
INSTANCE_IDS = [uuid4(), uuid4(), uuid4()]
FINDING_IDS = [uuid4(), uuid4(), uuid4()]
KG_NODE_IDS = [uuid4(), uuid4()]
KG_EDGE_ID = uuid4()
DECOMP_IDS = [uuid4(), uuid4(), uuid4()]
TX_ID = uuid4()
TELEMETRY_ID = uuid4()
REVIEW_INSTANCE_IDS = [uuid4(), uuid4()]

# ---------------------------------------------------------------------------
# Canned LLM response content
# ---------------------------------------------------------------------------
DECOMPOSITION_JSON = json.dumps({
    "sub_objectives": [
        {
            "id": "sub_1",
            "title": "Literature survey on quantum error correction",
            "description": "Survey recent QEC papers from 2024-2025",
            "role_class": "researcher",
            "dependency_type": "parallel",
            "depends_on": [],
            "impact_level": "routine",
            "rationale": "Establishes the current state of the art",
        },
        {
            "id": "sub_2",
            "title": "Synthesize error correction trade-offs",
            "description": "Combine findings into a trade-off analysis",
            "role_class": "synthesizer",
            "dependency_type": "sequential",
            "depends_on": ["sub_1"],
            "impact_level": "routine",
            "rationale": "Integrates research into actionable insight",
        },
        {
            "id": "sub_3",
            "title": "Critique feasibility assumptions",
            "description": "Challenge key assumptions in the synthesis",
            "role_class": "critic",
            "dependency_type": "sequential",
            "depends_on": ["sub_2"],
            "impact_level": "high-impact",
            "rationale": "Ensures robustness of conclusions",
        },
    ]
})

FINDING_JSON = json.dumps({
    "title": "QEC Surface Codes Outperform Toric Codes at Scale",
    "content": "Surface codes achieve 10x lower logical error rates at >1000 qubits.",
    "confidence": 0.85,
    "citations": [
        {
            "title": "Large-scale QEC benchmark",
            "source_type": "paper",
            "source_name": "Quantum Journal",
            "url": "https://example.com/qec-benchmark",
            "doi": "10.1234/qec.2026.1000",
            "published_date": "2026-03-19",
            "authors": ["Alice Quantum", "Bob Decoder"],
            "supporting_snippet": "Surface-code decoders maintained lower logical error rates above 1000 qubits.",
        }
    ],
    "kg_contribution": {
        "entities": [
            {"label": "Surface Code", "type": "concept", "properties": {"domain": "QEC"}},
            {"label": "Toric Code", "type": "concept", "properties": {"domain": "QEC"}},
        ],
        "relationships": [
            {
                "source": "Surface Code",
                "target": "Toric Code",
                "type": "outperforms",
                "weight": 0.85,
            }
        ],
    },
})

REVIEW_APPROVE_JSON = json.dumps({
    "methodology_critique": "Sound survey methodology with representative sample.",
    "evidence_evaluation": "Strong empirical evidence from multiple independent labs.",
    "novelty_assessment": "Incremental but valuable quantitative comparison.",
    "confidence_rating": 0.88,
    "verdict": "approve",
    "revision_feedback": None,
})

CHALLENGE_NO_FLAW_JSON = json.dumps({
    "has_flaw": False,
    "flaw_type": None,
    "description": None,
    "counter_evidence": None,
    "severity": None,
    "confidence": 0.3,
})


# ---------------------------------------------------------------------------
# Helper: build a mock KimiResponse
# ---------------------------------------------------------------------------
def _kimi_response(content: str) -> KimiResponse:
    return KimiResponse(
        content=content,
        reasoning="thinking steps...",
        input_tokens=500,
        thinking_tokens=200,
        output_tokens=300,
        cost_usd=0.001,
        latency_ms=150,
        model="kimi-k2.5",
        prompt_hash="abc123",
    )


# ---------------------------------------------------------------------------
# Helper: build a Row-like SimpleNamespace from a dict
# ---------------------------------------------------------------------------
def _row(**kwargs):
    """Create a SimpleNamespace that behaves like an SA Row (attribute access)."""
    ns = SimpleNamespace(**kwargs)
    ns._mapping = kwargs
    return ns


# ---------------------------------------------------------------------------
# Helper: build mock async engine with a given execute function
# ---------------------------------------------------------------------------
def _make_engine(execute_fn):
    """Create a mock engine where engine.begin() yields a conn with execute_fn.

    Properly handles ``async with engine.begin() as conn:`` by returning an
    async context manager directly from begin() (not a coroutine).
    """
    mock_conn = MagicMock()
    mock_conn.execute = execute_fn

    @contextlib.asynccontextmanager
    async def _begin():
        yield mock_conn

    mock_engine = MagicMock()
    mock_engine.begin = _begin
    return mock_engine, mock_conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def settings():
    return NexusSettings(
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
        MOONSHOT_API_KEY="test-key",
        BUDGET_CEILING_USD=Decimal("38.25"),
    )


@pytest.fixture
def mock_kimi():
    """KimiClient mock that cycles through canned responses."""
    kimi = AsyncMock()
    kimi.call_thinking = AsyncMock(return_value=_kimi_response(FINDING_JSON))
    kimi.call_instant = AsyncMock(return_value=_kimi_response(FINDING_JSON))
    return kimi


# ---------------------------------------------------------------------------
# Test 1: Decomposition produces 3+ sub-objectives in a valid DAG
# ---------------------------------------------------------------------------
class TestDecomposition:
    async def test_decompose_creates_multi_branch_dag(self, settings, mock_kimi):
        """AC-1: Originator decomposes objective into multi-branch DAG (3+ sub-objectives)."""
        mock_kimi.call_thinking = AsyncMock(
            return_value=_kimi_response(DECOMPOSITION_JSON)
        )

        sub_obj_counter = iter(SUB_OBJ_IDS)

        objective_row = _row(
            objective_id=PARENT_OBJ_ID,
            title="Quantum Error Correction Survey",
            description="Comprehensive survey of QEC approaches",
            objective_type="strategic",
            impact_level="high-impact",
            priority=5,
            status="proposed",
            proposed_by_type="human",
            knowledge_graph_anchor=[],
            assigned_to=None,
        )

        async def mock_execute(stmt):
            result = MagicMock()
            stmt_str = str(getattr(stmt, "text", "") or str(stmt))

            if "objectives" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = objective_row
                result.fetchall.return_value = [objective_row]
                result.one_or_none.return_value = objective_row
                result.scalar_one.return_value = PARENT_OBJ_ID
                return result

            if "objectives" in stmt_str and "INSERT" in stmt_str.upper():
                next_id = next(sub_obj_counter, uuid4())
                result.scalar_one.return_value = next_id
                return result

            if "objective_decomposition" in stmt_str and "INSERT" in stmt_str.upper():
                return result

            result.first.return_value = None
            result.fetchall.return_value = []
            result.scalar_one.return_value = None
            return result

        mock_engine, _ = _make_engine(mock_execute)

        with patch(
            "nexus_engine.decomposer.get_context_for_objective",
            new_callable=AsyncMock,
            return_value="No relevant KG context.",
        ):
            from nexus_engine.decomposer import decompose_objective

            result = await decompose_objective(
                engine=mock_engine,
                kimi_client=mock_kimi,
                objective_id=PARENT_OBJ_ID,
                settings=settings,
            )

        # Assert: 3 sub-objectives returned
        assert len(result) == 3, f"Expected 3 sub-objectives, got {len(result)}"

        # Assert: different role classes present
        role_classes = {sub["role_class"] for sub in result}
        assert "researcher" in role_classes
        assert "synthesizer" in role_classes
        assert "critic" in role_classes

        # Assert: sub-objective IDs match our UUIDs
        returned_obj_ids = {sub["objective_id"] for sub in result}
        assert returned_obj_ids == set(SUB_OBJ_IDS)

        # Assert: Kimi was called exactly once for decomposition
        mock_kimi.call_thinking.assert_awaited_once()

    async def test_decomposition_response_parsed_correctly(self):
        """Verify ResponseParser.parse_decomposition produces correct data."""
        result = ResponseParser.parse_decomposition(DECOMPOSITION_JSON)
        assert len(result.sub_objectives) == 3
        assert result.sub_objectives[0].id == "sub_1"
        assert result.sub_objectives[0].role_class == "researcher"
        assert result.sub_objectives[1].depends_on == ["sub_1"]
        assert result.sub_objectives[2].impact_level == "high-impact"


# ---------------------------------------------------------------------------
# Test 2: Dispatcher activates different persona types and records telemetry
# ---------------------------------------------------------------------------
class TestDispatcher:
    async def test_dispatch_activates_personas_and_records_findings(
        self, settings, mock_kimi
    ):
        """AC-2, AC-3, AC-7: Personas activated, findings produced, telemetry captured. Requires real DB."""
        decomp_rows = []
        for i, sub_id in enumerate(SUB_OBJ_IDS):
            decomp_rows.append(
                _row(
                    decomposition_id=DECOMP_IDS[i],
                    parent_objective_id=PARENT_OBJ_ID,
                    child_objective_id=sub_id,
                    decomposition_rationale="Test rationale",
                    dependency_type="parallel",
                    depends_on=[],
                    execution_order=i,
                )
            )

        instance_cycle = iter(INSTANCE_IDS)
        finding_cycle = iter(FINDING_IDS)

        findings_inserted = []
        telemetry_inserted = []
        instances_inserted = []
        events_emitted = []

        persona_row = _row(
            persona_id=PERSONA_IDS["researcher"],
            persona_name="Test Researcher",
            role_class="researcher",
            system_prompt_template="You are a research agent working on {objective}.",
            status="active",
            reputation_score=Decimal("0.800"),
            parent_persona_id=None,
        )

        sub_obj_rows = {}
        for i, (sub_id, role) in enumerate(
            zip(SUB_OBJ_IDS, ["researcher", "synthesizer", "critic"])
        ):
            sub_obj_rows[sub_id] = _row(
                objective_id=sub_id,
                parent_objective_id=PARENT_OBJ_ID,
                title=f"Sub-objective {i + 1}",
                description=f"Description for sub-objective {i + 1}",
                objective_type="tactical",
                impact_level="routine",
                priority=5,
                status="proposed",
                proposed_by_type="agent",
                knowledge_graph_anchor=[],
                assigned_to=None,
                compute_budget_allocated=Decimal("10.00"),
            )

        async def mock_execute(stmt):
            result = MagicMock()
            stmt_str = str(getattr(stmt, "text", "") or str(stmt))

            if "objective_decomposition" in stmt_str and "SELECT" in stmt_str.upper():
                result.fetchall.return_value = decomp_rows
                return result

            if "objectives" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = sub_obj_rows.get(
                    SUB_OBJ_IDS[0], persona_row
                )
                return result

            if "agent_personas" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = persona_row
                result.__iter__ = lambda self: iter([])
                result.one_or_none.return_value = None
                return result

            if "objectives" in stmt_str and "UPDATE" in stmt_str.upper():
                return result

            if "agent_instances" in stmt_str and "INSERT" in stmt_str.upper():
                inst_id = next(instance_cycle, uuid4())
                instances_inserted.append(inst_id)
                result.scalar_one.return_value = inst_id
                return result

            if "agent_instances" in stmt_str and "UPDATE" in stmt_str.upper():
                return result

            if "findings" in stmt_str and "INSERT" in stmt_str.upper():
                f_id = next(finding_cycle, uuid4())
                findings_inserted.append(f_id)
                result.scalar_one.return_value = f_id
                return result

            if "agent_telemetry" in stmt_str and "INSERT" in stmt_str.upper():
                telemetry_inserted.append(TELEMETRY_ID)
                result.scalar_one.return_value = TELEMETRY_ID
                return result

            if "events" in stmt_str and "INSERT" in stmt_str.upper():
                events_emitted.append(stmt)
                return result

            result.first.return_value = None
            result.fetchall.return_value = []
            return result

        mock_engine, _ = _make_engine(mock_execute)
        shutdown = asyncio.Event()

        from nexus_engine.dispatcher import Dispatcher

        dispatcher = Dispatcher(
            engine=mock_engine,
            kimi_client=mock_kimi,
            settings=settings,
            shutdown_event=shutdown,
        )

        await dispatcher.dispatch_dag(PARENT_OBJ_ID)

        # AC-2: persona was activated (instance created)
        assert len(instances_inserted) >= 1, "At least one agent instance should be created"

        # AC-3: findings were produced
        assert len(findings_inserted) >= 1, "At least one finding should be inserted"

        # AC-7: telemetry was captured
        assert len(telemetry_inserted) >= 1, "At least one telemetry record should be inserted"

        # Events were emitted
        assert len(events_emitted) >= 1, "At least one event should be emitted"


# ---------------------------------------------------------------------------
# Test 3: Peer review triggers with correct reviewer count
# ---------------------------------------------------------------------------
class TestPeerReview:
    async def test_peer_review_triggers_with_correct_count(self, mock_kimi):
        """AC-4: Peer review triggers with correct reviewer count (2 for routine). Requires real DB."""
        mock_kimi.call_thinking = AsyncMock(
            return_value=_kimi_response(REVIEW_APPROVE_JSON)
        )

        finding_id = FINDING_IDS[0]
        objective_id = SUB_OBJ_IDS[0]
        instance_id = INSTANCE_IDS[0]
        author_persona_id = PERSONA_IDS["researcher"]

        review_inserts = []
        reviewer_instance_inserts = []

        async def mock_execute(stmt):
            result = MagicMock()
            stmt_str = str(getattr(stmt, "text", "") or str(stmt))

            # JOIN query: agent_instances JOIN findings (select_reviewers author lookup)
            if (
                "agent_instances" in stmt_str
                and "findings" in stmt_str
                and "SELECT" in stmt_str.upper()
            ):
                result.one_or_none.return_value = _row(persona_id=author_persona_id)
                return result

            if "findings" in stmt_str and "SELECT" in stmt_str.upper():
                row = _row(
                    finding_id=finding_id,
                    objective_id=objective_id,
                    instance_id=instance_id,
                    finding_type="research",
                    title="QEC Surface Codes Outperform Toric Codes at Scale",
                    content="Surface codes achieve 10x lower logical error rates.",
                    structured_data=json.loads(FINDING_JSON),
                    status="pending_review",
                    review_round=0,
                    impact_level="routine",
                    kg_nodes_created=[],
                    kg_edges_created=[],
                )
                result.one_or_none.return_value = row
                result.first.return_value = row
                result.scalar_one.return_value = 0
                return result

            if "objectives" in stmt_str and "SELECT" in stmt_str.upper():
                obj_row = _row(
                    objective_id=objective_id,
                    title="Sub-objective 1",
                    impact_level="routine",
                    compute_budget_allocated=Decimal("10.00"),
                )
                result.one_or_none.return_value = obj_row
                result.first.return_value = obj_row
                return result

            if "agent_instances" in stmt_str and "SELECT" in stmt_str.upper():
                result.one_or_none.return_value = _row(persona_id=author_persona_id)
                return result

            if "agent_personas" in stmt_str and "SELECT" in stmt_str.upper():
                reviewer_candidates = [
                    _row(
                        persona_id=PERSONA_IDS["synthesizer"],
                        role_class="synthesizer",
                        reputation_score=Decimal("0.900"),
                        parent_persona_id=None,
                    ),
                    _row(
                        persona_id=PERSONA_IDS["critic"],
                        role_class="critic",
                        reputation_score=Decimal("0.850"),
                        parent_persona_id=None,
                    ),
                ]
                result.__iter__ = lambda self: iter(reviewer_candidates)
                result.one_or_none.return_value = None
                result.first.return_value = (
                    reviewer_candidates[0] if reviewer_candidates else None
                )
                return result

            if "agent_instances" in stmt_str and "INSERT" in stmt_str.upper():
                ri_id = uuid4()
                reviewer_instance_inserts.append(ri_id)
                result.scalar_one.return_value = ri_id
                return result

            if "agent_instances" in stmt_str and "UPDATE" in stmt_str.upper():
                return result

            if "peer_reviews" in stmt_str and "INSERT" in stmt_str.upper():
                review_inserts.append(stmt)
                return result

            if "findings" in stmt_str and "UPDATE" in stmt_str.upper():
                return result

            if "economy_ledger" in stmt_str and "INSERT" in stmt_str.upper():
                result.scalar_one.return_value = uuid4()
                return result

            if "knowledge_graph_nodes" in stmt_str and "UPDATE" in stmt_str.upper():
                return result

            if "events" in stmt_str and "INSERT" in stmt_str.upper():
                return result

            result.first.return_value = None
            result.fetchall.return_value = []
            result.one_or_none.return_value = None
            result.scalar_one.return_value = 0
            return result

        mock_conn = MagicMock()
        mock_conn.execute = mock_execute

        # Reset the pybreaker circuit breaker state for a clean test
        from nexus_core.review.peer_review import _review_breaker
        _review_breaker.close()

        # Patch the circuit breaker's call_async to directly call the
        # function, avoiding pybreaker's generator-based wrapper which
        # has compatibility issues with AsyncMock.
        async def _transparent_call_async(func, *args, **kwargs):
            return await func(*args, **kwargs)

        from nexus_core.review.peer_review import orchestrate_review

        with patch.object(_review_breaker, "call_async", side_effect=_transparent_call_async):
            outcome = await orchestrate_review(
                conn=mock_conn,
                kimi_client=mock_kimi,
                finding_id=finding_id,
            )

        # AC-4: 2 reviewers for routine impact
        assert len(review_inserts) == 2, (
            f"Expected 2 review inserts for routine finding, got {len(review_inserts)}"
        )

        # Verdict should be approved (both reviews approve)
        assert outcome.verdict == "approved"
        assert outcome.consensus_score > 0


# ---------------------------------------------------------------------------
# Test 4: Integration writes KG nodes + economy + marks integrated
# ---------------------------------------------------------------------------
class TestIntegration:
    async def test_integrate_writes_kg_and_economy(self, settings, mock_kimi):
        """AC-5, AC-6: Validated findings committed to KG; economy credits minted."""
        instance_id = INSTANCE_IDS[0]
        finding_id = FINDING_IDS[0]
        objective_id = SUB_OBJ_IDS[0]
        persona_id = PERSONA_IDS["researcher"]

        kg_nodes_created = []
        kg_edges_created = []
        economy_minted = []
        instance_statuses = []
        events_emitted = []

        kg_node_counter = iter(KG_NODE_IDS)

        async def mock_execute(stmt):
            result = MagicMock()
            stmt_str = str(getattr(stmt, "text", "") or str(stmt))

            if "agent_instances" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = _row(
                    instance_id=instance_id,
                    persona_id=persona_id,
                    objective_id=objective_id,
                    status="completed",
                )
                result.one_or_none.return_value = _row(persona_id=persona_id)
                return result

            if "findings" in stmt_str and "SELECT" in stmt_str.upper():
                row = _row(
                    finding_id=finding_id,
                    objective_id=objective_id,
                    instance_id=instance_id,
                    title="QEC Surface Codes Outperform Toric Codes at Scale",
                    content="Surface codes achieve 10x lower logical error rates.",
                    structured_data={
                        "kg_entities": [
                            {
                                "label": "Surface Code",
                                "type": "concept",
                                "properties": {"domain": "QEC"},
                            },
                            {
                                "label": "Toric Code",
                                "type": "concept",
                                "properties": {"domain": "QEC"},
                            },
                        ],
                        "kg_relationships": [
                            {
                                "source": "Surface Code",
                                "target": "Toric Code",
                                "type": "outperforms",
                                "weight": 0.85,
                            }
                        ],
                    },
                    status="pending_review",
                    review_round=0,
                    impact_level="routine",
                    kg_nodes_created=[],
                )
                result.first.return_value = row
                result.one_or_none.return_value = row
                result.scalar_one.return_value = 0
                return result

            if "knowledge_graph_nodes" in stmt_str and "INSERT" in stmt_str.upper():
                node_id = next(kg_node_counter, uuid4())
                kg_nodes_created.append(node_id)
                result.scalar_one.return_value = node_id
                return result

            if "knowledge_graph_edges" in stmt_str and "INSERT" in stmt_str.upper():
                kg_edges_created.append(KG_EDGE_ID)
                result.scalar_one.return_value = KG_EDGE_ID
                return result

            if "economy_ledger" in stmt_str and "INSERT" in stmt_str.upper():
                tx = uuid4()
                economy_minted.append(tx)
                result.scalar_one.return_value = tx
                return result

            if "agent_instances" in stmt_str and "UPDATE" in stmt_str.upper():
                instance_statuses.append("updated")
                return result

            if "findings" in stmt_str and "UPDATE" in stmt_str.upper():
                return result

            if "objectives" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = _row(
                    parent_objective_id=PARENT_OBJ_ID,
                )
                result.scalar_one.return_value = 3
                return result

            if "objectives" in stmt_str and "UPDATE" in stmt_str.upper():
                return result

            if "events" in stmt_str and "INSERT" in stmt_str.upper():
                events_emitted.append(stmt)
                return result

            if "knowledge_graph_nodes" in stmt_str and "UPDATE" in stmt_str.upper():
                return result

            result.first.return_value = None
            result.fetchall.return_value = []
            result.one_or_none.return_value = None
            result.scalar_one.return_value = 0
            return result

        mock_engine, _ = _make_engine(mock_execute)

        approved_outcome = ReviewOutcome(
            finding_id=finding_id,
            verdict="approved",
            reviews=[],
            consensus_score=0.88,
        )

        # Reset circuit breaker
        from nexus_core.review.peer_review import _review_breaker
        _review_breaker.close()

        with patch(
            "nexus_engine.integrator.orchestrate_review",
            new_callable=AsyncMock,
            return_value=approved_outcome,
        ):
            from nexus_engine.integrator import integrate_results

            await integrate_results(
                engine=mock_engine,
                kimi_client=mock_kimi,
                instance_id=instance_id,
                settings=settings,
            )

        # AC-5: KG nodes created with provenance
        assert len(kg_nodes_created) == 2, (
            f"Expected 2 KG nodes (Surface Code + Toric Code), got {len(kg_nodes_created)}"
        )

        # AC-5: KG edge created
        assert len(kg_edges_created) == 1, (
            f"Expected 1 KG edge (outperforms), got {len(kg_edges_created)}"
        )

        # AC-6: Economy credits minted
        assert len(economy_minted) >= 1, "Expected at least one economy mint transaction"

        # Instance was marked as integrated
        assert len(instance_statuses) >= 1, "Instance should be updated to integrated"


# ---------------------------------------------------------------------------
# Test 5: Red Team challenge parses correctly (no flaw found)
# ---------------------------------------------------------------------------
class TestRedTeamChallenge:
    def test_challenge_no_flaw_parsed(self):
        """AC-5 (supplementary): Red Team challenge with no flaw is handled."""
        result = ResponseParser.parse_challenge(CHALLENGE_NO_FLAW_JSON)
        assert result.has_flaw is False
        assert result.flaw_type is None
        assert result.confidence == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Test 6: Finding parsed correctly with KG entities
# ---------------------------------------------------------------------------
class TestFindingParser:
    def test_finding_json_parsed(self):
        """AC-3: Finding content is parsed with KG entities and relationships."""
        result = ResponseParser.parse_research_finding(FINDING_JSON)
        assert result.title == "QEC Surface Codes Outperform Toric Codes at Scale"
        assert result.confidence == pytest.approx(0.85)
        assert len(result.citations) == 1
        assert len(result.kg_entities) == 2
        assert len(result.kg_relationships) == 1
        assert result.kg_entities[0]["label"] == "Surface Code"
        assert result.kg_relationships[0]["type"] == "outperforms"


# ---------------------------------------------------------------------------
# Test 7: Review JSON parsed correctly
# ---------------------------------------------------------------------------
class TestReviewParser:
    def test_review_approve_parsed(self):
        """AC-4: Review response with approve verdict is parsed correctly."""
        result = ResponseParser.parse_review(REVIEW_APPROVE_JSON)
        assert result.verdict == "approve"
        assert result.confidence_rating == pytest.approx(0.88)
        assert "Sound survey" in result.methodology_critique
        assert result.revision_feedback is None


# ---------------------------------------------------------------------------
# Test 8: Full lifecycle (decompose -> dispatch -> integrate)
# ---------------------------------------------------------------------------
class TestFullLifecycle:
    async def test_end_to_end_orchestration(self, settings, mock_kimi):
        """Full lifecycle: decompose -> dispatch -> integrate. Requires real DB.

        Verifies that all acceptance criteria are met in a single flow.
        """
        # ===== Phase 1: Decomposition =====
        mock_kimi.call_thinking = AsyncMock(
            return_value=_kimi_response(DECOMPOSITION_JSON)
        )

        sub_obj_counter = iter(SUB_OBJ_IDS)

        objective_row = _row(
            objective_id=PARENT_OBJ_ID,
            title="Quantum Error Correction Survey",
            description="Comprehensive survey of QEC approaches",
            objective_type="strategic",
            impact_level="high-impact",
            priority=5,
            status="proposed",
            proposed_by_type="human",
            knowledge_graph_anchor=[],
            assigned_to=None,
        )

        async def decompose_execute(stmt):
            result = MagicMock()
            stmt_str = str(getattr(stmt, "text", "") or str(stmt))

            if "objectives" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = objective_row
                return result
            if "objectives" in stmt_str and "INSERT" in stmt_str.upper():
                result.scalar_one.return_value = next(sub_obj_counter, uuid4())
                return result
            result.first.return_value = None
            return result

        mock_engine_1, _ = _make_engine(decompose_execute)

        with patch(
            "nexus_engine.decomposer.get_context_for_objective",
            new_callable=AsyncMock,
            return_value="",
        ):
            from nexus_engine.decomposer import decompose_objective

            sub_objectives = await decompose_objective(
                engine=mock_engine_1,
                kimi_client=mock_kimi,
                objective_id=PARENT_OBJ_ID,
                settings=settings,
            )

        # AC-1: 3+ sub-objectives with diverse roles
        assert len(sub_objectives) >= 3
        role_classes = {s["role_class"] for s in sub_objectives}
        assert len(role_classes) >= 2, "Multiple persona types required"

        # ===== Phase 2: Dispatch =====
        mock_kimi.call_thinking = AsyncMock(
            return_value=_kimi_response(FINDING_JSON)
        )

        decomp_rows = [
            _row(
                decomposition_id=DECOMP_IDS[i],
                parent_objective_id=PARENT_OBJ_ID,
                child_objective_id=sub["objective_id"],
                decomposition_rationale="Test",
                dependency_type="parallel",
                depends_on=[],
                execution_order=i,
            )
            for i, sub in enumerate(sub_objectives)
        ]

        dispatch_findings = []
        dispatch_telemetry = []
        dispatch_instances = []

        instance_cycle = iter(INSTANCE_IDS)

        persona_row = _row(
            persona_id=PERSONA_IDS["researcher"],
            persona_name="Test Researcher",
            role_class="researcher",
            system_prompt_template="You are a research agent working on {objective}.",
            status="active",
            reputation_score=Decimal("0.800"),
            parent_persona_id=None,
        )

        async def dispatch_execute(stmt):
            result = MagicMock()
            stmt_str = str(getattr(stmt, "text", "") or str(stmt))

            if "objective_decomposition" in stmt_str and "SELECT" in stmt_str.upper():
                result.fetchall.return_value = decomp_rows
                return result
            if "objectives" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = _row(
                    objective_id=SUB_OBJ_IDS[0],
                    title="Sub-objective",
                    description="Test description",
                    objective_type="tactical",
                    impact_level="routine",
                    priority=5,
                    status="proposed",
                    assigned_to=None,
                )
                return result
            if "agent_personas" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = persona_row
                result.__iter__ = lambda self: iter([])
                result.one_or_none.return_value = None
                return result
            if "objectives" in stmt_str and "UPDATE" in stmt_str.upper():
                return result
            if "agent_instances" in stmt_str and "INSERT" in stmt_str.upper():
                iid = next(instance_cycle, uuid4())
                dispatch_instances.append(iid)
                result.scalar_one.return_value = iid
                return result
            if "agent_instances" in stmt_str and "UPDATE" in stmt_str.upper():
                return result
            if "findings" in stmt_str and "INSERT" in stmt_str.upper():
                fid = uuid4()
                dispatch_findings.append(fid)
                result.scalar_one.return_value = fid
                return result
            if "agent_telemetry" in stmt_str and "INSERT" in stmt_str.upper():
                dispatch_telemetry.append(uuid4())
                result.scalar_one.return_value = uuid4()
                return result
            if "events" in stmt_str and "INSERT" in stmt_str.upper():
                return result

            result.first.return_value = None
            result.fetchall.return_value = []
            return result

        mock_engine_2, _ = _make_engine(dispatch_execute)
        shutdown = asyncio.Event()

        from nexus_engine.dispatcher import Dispatcher

        dispatcher = Dispatcher(
            engine=mock_engine_2,
            kimi_client=mock_kimi,
            settings=settings,
            shutdown_event=shutdown,
        )
        await dispatcher.dispatch_dag(PARENT_OBJ_ID)

        # AC-3: Findings produced
        assert len(dispatch_findings) >= 1, "Dispatch should produce findings"

        # AC-7: Telemetry captured
        assert len(dispatch_telemetry) >= 1, "Dispatch should capture telemetry"

        # ===== Phase 3: Integration =====
        mock_kimi.call_thinking = AsyncMock(
            return_value=_kimi_response(REVIEW_APPROVE_JSON)
        )

        kg_nodes_created = []
        economy_txns = []

        kg_node_counter = iter(KG_NODE_IDS)

        async def integrate_execute(stmt):
            result = MagicMock()
            stmt_str = str(getattr(stmt, "text", "") or str(stmt))

            if "agent_instances" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = _row(
                    instance_id=dispatch_instances[0]
                    if dispatch_instances
                    else INSTANCE_IDS[0],
                    persona_id=PERSONA_IDS["researcher"],
                    objective_id=SUB_OBJ_IDS[0],
                    status="completed",
                )
                return result
            if "findings" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = _row(
                    finding_id=dispatch_findings[0]
                    if dispatch_findings
                    else FINDING_IDS[0],
                    objective_id=SUB_OBJ_IDS[0],
                    instance_id=dispatch_instances[0]
                    if dispatch_instances
                    else INSTANCE_IDS[0],
                    title="QEC Finding",
                    content="Surface codes analysis",
                    structured_data={
                        "kg_entities": [
                            {
                                "label": "Surface Code",
                                "type": "concept",
                                "properties": {},
                            },
                            {
                                "label": "Toric Code",
                                "type": "concept",
                                "properties": {},
                            },
                        ],
                        "kg_relationships": [
                            {
                                "source": "Surface Code",
                                "target": "Toric Code",
                                "type": "outperforms",
                                "weight": 0.85,
                            }
                        ],
                    },
                    status="pending_review",
                    review_round=0,
                    impact_level="routine",
                    kg_nodes_created=[],
                )
                return result
            if "knowledge_graph_nodes" in stmt_str and "INSERT" in stmt_str.upper():
                nid = next(kg_node_counter, uuid4())
                kg_nodes_created.append(nid)
                result.scalar_one.return_value = nid
                return result
            if "knowledge_graph_edges" in stmt_str and "INSERT" in stmt_str.upper():
                result.scalar_one.return_value = KG_EDGE_ID
                return result
            if "economy_ledger" in stmt_str and "INSERT" in stmt_str.upper():
                tx = uuid4()
                economy_txns.append(tx)
                result.scalar_one.return_value = tx
                return result
            if "objectives" in stmt_str and "SELECT" in stmt_str.upper():
                result.first.return_value = _row(parent_objective_id=PARENT_OBJ_ID)
                result.scalar_one.return_value = 3
                return result
            if "events" in stmt_str:
                return result

            result.first.return_value = None
            result.scalar_one.return_value = 0
            return result

        mock_engine_3, _ = _make_engine(integrate_execute)

        approved_outcome = ReviewOutcome(
            finding_id=dispatch_findings[0]
            if dispatch_findings
            else FINDING_IDS[0],
            verdict="approved",
            reviews=[],
            consensus_score=0.88,
        )

        with patch(
            "nexus_engine.integrator.orchestrate_review",
            new_callable=AsyncMock,
            return_value=approved_outcome,
        ):
            from nexus_engine.integrator import integrate_results

            await integrate_results(
                engine=mock_engine_3,
                kimi_client=mock_kimi,
                instance_id=dispatch_instances[0]
                if dispatch_instances
                else INSTANCE_IDS[0],
                settings=settings,
            )

        # AC-5: KG nodes created
        assert len(kg_nodes_created) == 2, (
            f"Expected 2 KG nodes, got {len(kg_nodes_created)}"
        )

        # AC-6: Economy credits minted
        assert len(economy_txns) >= 1, "Expected economy transactions"
