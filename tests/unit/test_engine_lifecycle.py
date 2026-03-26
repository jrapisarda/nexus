from __future__ import annotations

import asyncio
import contextlib
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus_core.config import NexusSettings
from nexus_core.llm.client import KimiResponse, MalformedModelResponseError


def _row(**kwargs):
    row = SimpleNamespace(**kwargs)
    row._mapping = kwargs
    return row


def _make_engine(execute_fn):
    mock_conn = MagicMock()
    mock_conn.execute = execute_fn

    @contextlib.asynccontextmanager
    async def _begin():
        yield mock_conn

    mock_engine = MagicMock()
    mock_engine.begin = _begin
    return mock_engine, mock_conn


def _kimi_response(content: str) -> KimiResponse:
    return KimiResponse(
        content=content,
        reasoning="reasoning",
        input_tokens=100,
        thinking_tokens=25,
        output_tokens=75,
        cost_usd=Decimal("0.012345"),
        latency_ms=123,
        model="kimi-k2.5",
        prompt_hash="hash123",
    )


@pytest.fixture
def settings():
    return NexusSettings(
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
        MOONSHOT_API_KEY="test-key",
        BUDGET_CEILING_USD=Decimal("38.25"),
        REPORTS_DIR="reports-test",
    )


@pytest.mark.asyncio
async def test_decompose_objective_persists_child_uuid_dependencies(settings):
    parent_id = uuid4()
    child_1 = uuid4()
    child_2 = uuid4()
    objective_row = _row(
        objective_id=parent_id,
        title="Parent Objective",
        description="Parent description",
        objective_type="strategic",
        impact_level="routine",
        priority=5,
        status="proposed",
        proposed_by_type="human",
        knowledge_graph_anchor=[],
    )
    decomposition_payload = json.dumps(
        {
            "sub_objectives": [
                {
                    "id": "research",
                    "title": "Research branch",
                    "description": "Gather evidence",
                    "role_class": "researcher",
                    "dependency_type": "parallel",
                    "depends_on": [],
                    "impact_level": "routine",
                    "rationale": "Need evidence first",
                },
                {
                    "id": "synthesis",
                    "title": "Synthesis branch",
                    "description": "Combine the evidence",
                    "role_class": "synthesizer",
                    "dependency_type": "sequential",
                    "depends_on": ["research"],
                    "impact_level": "routine",
                    "rationale": "Depends on the evidence",
                },
            ]
        }
    )

    created_ids = iter([child_1, child_2])
    decomposition_inserts = []

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "SELECT" in stmt_str.upper() and "objectives" in stmt_str:
            result.first.return_value = objective_row
            return result

        if "INSERT INTO objectives" in stmt_str:
            result.scalar_one.return_value = next(created_ids)
            return result

        if "INSERT INTO objective_decomposition" in stmt_str:
            decomposition_inserts.append(stmt.compile().params)
            return result

        result.first.return_value = None
        return result

    engine, _ = _make_engine(mock_execute)
    kimi = AsyncMock()
    kimi.call_thinking = AsyncMock(return_value=_kimi_response(decomposition_payload))

    with patch(
        "nexus_engine.decomposer.get_context_for_objective",
        new_callable=AsyncMock,
        return_value="",
    ):
        from nexus_engine.decomposer import decompose_objective

        result = await decompose_objective(
            engine=engine,
            kimi_client=kimi,
            objective_id=parent_id,
            settings=settings,
        )

    assert result[1]["depends_on"] == [str(child_1)]
    assert decomposition_inserts[1]["depends_on"] == [str(child_1)]


@pytest.mark.asyncio
async def test_decompose_objective_retries_after_empty_final_content(settings):
    parent_id = uuid4()
    child_id = uuid4()
    objective_row = _row(
        objective_id=parent_id,
        title="Parent Objective",
        description="Parent description",
        objective_type="strategic",
        impact_level="routine",
        priority=5,
        status="proposed",
        proposed_by_type="human",
        knowledge_graph_anchor=[],
    )
    decomposition_payload = json.dumps(
        {
            "sub_objectives": [
                {
                    "id": "research",
                    "title": "Research branch",
                    "description": "Gather evidence",
                    "role_class": "researcher",
                    "dependency_type": "parallel",
                    "depends_on": [],
                    "impact_level": "routine",
                    "rationale": "Need evidence first",
                },
            ]
        }
    )

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "SELECT" in stmt_str.upper() and "objectives" in stmt_str:
            result.first.return_value = objective_row
            return result

        if "INSERT INTO objectives" in stmt_str:
            result.scalar_one.return_value = child_id
            return result

        if "INSERT INTO objective_decomposition" in stmt_str:
            return result

        result.first.return_value = None
        return result

    engine, _ = _make_engine(mock_execute)
    kimi = AsyncMock()
    kimi.call_thinking = AsyncMock(
        side_effect=[
            MalformedModelResponseError("Model returned empty final content"),
            _kimi_response(decomposition_payload),
        ]
    )

    with patch(
        "nexus_engine.decomposer.get_context_for_objective",
        new_callable=AsyncMock,
        return_value="",
    ):
        from nexus_engine.decomposer import decompose_objective

        result = await decompose_objective(
            engine=engine,
            kimi_client=kimi,
            objective_id=parent_id,
            settings=settings,
        )

    assert len(result) == 1
    assert kimi.call_thinking.await_count == 2


def test_dispatcher_build_dependency_graph_uses_persisted_depends_on():
    child_1 = uuid4()
    child_2 = uuid4()
    child_3 = uuid4()

    from nexus_engine.dispatcher import Dispatcher

    graph = Dispatcher._build_dependency_graph(
        [
            _row(
                child_objective_id=child_1,
                dependency_type="parallel",
                depends_on=[],
                execution_order=0,
            ),
            _row(
                child_objective_id=child_2,
                dependency_type="parallel",
                depends_on=[str(child_1)],
                execution_order=2,
            ),
            _row(
                child_objective_id=child_3,
                dependency_type="parallel",
                depends_on=[],
                execution_order=1,
            ),
        ]
    )

    assert graph[str(child_1)] == set()
    assert graph[str(child_2)] == {str(child_1)}
    assert graph[str(child_3)] == set()


@pytest.mark.asyncio
async def test_dispatcher_supersedes_prior_revision_requested_findings():
    updates = []

    async def mock_execute(stmt):
        result = MagicMock()
        updates.append(stmt.compile().params)
        return result

    conn = MagicMock()
    conn.execute = mock_execute

    from nexus_engine.dispatcher import _supersede_revision_requested_findings

    objective_id = uuid4()
    await _supersede_revision_requested_findings(conn, objective_id)

    assert updates[-1]["objective_id_1"] == objective_id
    assert updates[-1]["status_1"] == "revision_requested"
    assert updates[-1]["status"] == "superseded"


@pytest.mark.asyncio
async def test_dispatcher_marks_objective_revision_requested_after_contract_violation(settings):
    objective_id = uuid4()
    persona_id = uuid4()
    instance_id = uuid4()
    objective_updates = []
    instance_updates = []

    objective_row = _row(
        objective_id=objective_id,
        title="Research Objective",
        description="Investigate a topic with structured evidence.",
        objective_type="tactical",
        impact_level="routine",
        priority=5,
        status="proposed",
        assigned_to=None,
    )
    persona_row = _row(
        persona_id=persona_id,
        persona_name="Research Persona",
        role_class="researcher",
        system_prompt_template="You are a research agent for {objective}.",
        status="active",
    )

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "FROM objectives" in stmt_str and "SELECT" in stmt_str:
            result.first.return_value = objective_row
            return result

        if "INSERT INTO agent_instances" in stmt_str:
            result.scalar_one.return_value = instance_id
            return result

        if "UPDATE objectives SET" in stmt_str:
            objective_updates.append(stmt.compile().params)
            return result

        if "UPDATE agent_instances SET" in stmt_str:
            instance_updates.append(stmt.compile().params)
            return result

        if "INSERT INTO findings" in stmt_str or "INSERT INTO agent_telemetry" in stmt_str:
            raise AssertionError("Schema-invalid findings must not be persisted")

        result.first.return_value = None
        result.fetchall.return_value = []
        return result

    engine, _ = _make_engine(mock_execute)
    kimi = AsyncMock()
    kimi.call_thinking = AsyncMock(return_value=_kimi_response("plain text only"))

    from nexus_engine.dispatcher import Dispatcher

    dispatcher = Dispatcher(
        engine=engine,
        kimi_client=kimi,
        settings=settings,
        shutdown_event=asyncio.Event(),
    )

    with patch.object(
        dispatcher,
        "_select_persona",
        new=AsyncMock(return_value=persona_row),
    ), patch.object(
        dispatcher,
        "_build_prompt_context",
        new=AsyncMock(return_value=("", "")),
    ), patch(
        "nexus_engine.dispatcher.emit_event",
        new_callable=AsyncMock,
    ) as emit_event, patch(
        "nexus_engine.dispatcher.diagnose_failure",
        new_callable=AsyncMock,
    ) as diagnose_failure:
        result = await dispatcher.dispatch_objective(objective_id)

    assert result is False
    assert kimi.call_thinking.await_count == 2
    assert any(update["status"] == "revision_requested" for update in objective_updates)
    assert any(update["status"] == "failed" for update in instance_updates)
    assert "## Correction Required" in kimi.call_thinking.await_args_list[1].args[1]
    assert "did not contain valid JSON" in kimi.call_thinking.await_args_list[1].args[1]
    assert any(call.args[1] == "research_output_contract_violation" for call in emit_event.await_args_list)
    diagnose_failure.assert_not_awaited()


@pytest.mark.asyncio
async def test_originator_processes_top_level_exploratory_objectives(settings):
    exploratory = _row(
        objective_id=uuid4(),
        parent_objective_id=None,
        title="Dream Cycle Proposal",
        description="Investigate an emergent pattern",
        objective_type="exploratory",
        impact_level="routine",
        priority=3,
        status="proposed",
        proposed_by_type="agent",
        approved_by_type=None,
    )

    async def mock_execute(stmt):
        result = MagicMock()
        result.fetchall.return_value = [exploratory]
        return result

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.originator import OriginatorLoop

    loop = OriginatorLoop(
        engine=engine,
        kimi_client=AsyncMock(),
        settings=settings,
        shutdown_event=asyncio.Event(),
    )
    loop._process_objective = AsyncMock()

    await loop._process_pending_objectives()

    loop._process_objective.assert_awaited_once_with(exploratory)


@pytest.mark.asyncio
async def test_originator_resumes_revision_requested_objectives(settings):
    revision_objective = _row(
        objective_id=uuid4(),
        parent_objective_id=uuid4(),
        title="Revise economic transition model",
        description="Address peer review gaps",
        objective_type="tactical",
        impact_level="routine",
        priority=8,
        status="revision_requested",
        proposed_by_type="system",
        approved_by_type="system",
    )

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)
        if "FROM objectives" in stmt_str and "ORDER BY objectives.priority DESC" in stmt_str:
            result.fetchall.return_value = [revision_objective]
            return result
        result.fetchall.return_value = []
        return result

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.originator import OriginatorLoop

    loop = OriginatorLoop(
        engine=engine,
        kimi_client=AsyncMock(),
        settings=settings,
        shutdown_event=asyncio.Event(),
    )
    loop._dispatcher.dispatch_objective = AsyncMock(return_value=True)

    await loop._resume_revision_requested_objectives()

    loop._dispatcher.dispatch_objective.assert_awaited_once_with(
        revision_objective.objective_id
    )


@pytest.mark.asyncio
async def test_originator_reconciles_stranded_validated_objectives(settings):
    stranded_objective = _row(
        objective_id=uuid4(),
        title="Recover stranded objective",
    )
    validated_finding = _row(
        finding_id=uuid4(),
        status="validated",
    )

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "FROM objectives" in stmt_str and "NOT (EXISTS" in stmt_str:
            result.fetchall.return_value = [stranded_objective]
            return result

        if "FROM findings" in stmt_str:
            result.first.return_value = validated_finding
            return result

        result.fetchall.return_value = []
        result.first.return_value = None
        return result

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.originator import OriginatorLoop

    loop = OriginatorLoop(
        engine=engine,
        kimi_client=AsyncMock(),
        settings=settings,
        shutdown_event=asyncio.Event(),
    )

    with patch(
        "nexus_engine.originator._reconcile_objective_state_from_finding",
        new_callable=AsyncMock,
        return_value="completed",
    ) as reconcile:
        await loop._reconcile_stranded_objectives()

    reconcile.assert_awaited_once_with(
        engine,
        loop._kimi,
        objective_id=stranded_objective.objective_id,
        finding_status="validated",
        finding_id=validated_finding.finding_id,
        settings=settings,
        recovery_reason="originator_stranded_objective_sweep",
    )


def test_originator_classifies_review_prompt_instances():
    from nexus_engine.originator import OriginatorLoop

    review_instance = _row(
        spawn_reason=None,
        input_prompt="## Finding to Review\n**Title:** Test finding",
    )
    challenge_instance = _row(
        spawn_reason=None,
        input_prompt="## Validated Finding to Challenge\n**Title:** Test finding",
    )
    infiltration_instance = _row(
        spawn_reason=None,
        input_prompt="Generate a plausible-but-wrong finding as JSON:\n{}",
    )
    default_instance = _row(
        spawn_reason=None,
        input_prompt="## Objective\nInvestigate labor policy transitions",
    )

    assert OriginatorLoop._classify_instance_work(review_instance) == "peer_review"
    assert OriginatorLoop._classify_instance_work(challenge_instance) == "red_team_challenge"
    assert OriginatorLoop._classify_instance_work(infiltration_instance) == "infiltration_test"
    assert OriginatorLoop._classify_instance_work(default_instance) == "objective_execution"


@pytest.mark.asyncio
async def test_originator_recovers_stale_objective_execution_instances(settings):
    stale_instance = _row(
        instance_id=uuid4(),
        objective_id=uuid4(),
        spawn_reason=None,
        input_prompt="## Objective\nRecover this task",
        objective_status="active",
    )
    updates = []

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "SELECT agent_instances.instance_id" in stmt_str and "last_heartbeat" in stmt_str:
            result.fetchall.return_value = [stale_instance]
            return result

        if "UPDATE agent_instances SET" in stmt_str:
            updates.append(("instance", stmt.compile().params))
            result.rowcount = 1
            return result

        if "UPDATE objectives SET assigned_to=:assigned_to" in stmt_str:
            updates.append(("objective", stmt.compile().params))
            result.rowcount = 1
            return result

        result.fetchall.return_value = []
        result.rowcount = 0
        return result

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.originator import OriginatorLoop

    loop = OriginatorLoop(
        engine=engine,
        kimi_client=AsyncMock(),
        settings=settings,
        shutdown_event=asyncio.Event(),
    )
    loop._dispatcher.dispatch_objective = AsyncMock(return_value=True)

    with patch("nexus_engine.originator.emit_event", new_callable=AsyncMock):
        await loop._recover_stale_running_instances()

    loop._dispatcher.dispatch_objective.assert_awaited_once_with(stale_instance.objective_id)
    assert any(kind == "instance" for kind, _ in updates)
    assert any(kind == "objective" for kind, _ in updates)


@pytest.mark.asyncio
async def test_advance_parent_objective_triggers_synthesis_when_children_complete():
    parent_id = uuid4()
    child_id = uuid4()
    sibling_id = uuid4()

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "SELECT objectives.parent_objective_id" in stmt_str:
            result.first.return_value = _row(parent_objective_id=parent_id)
            return result

        if "SELECT objectives.objective_id, objectives.status" in stmt_str:
            result.fetchall.return_value = [
                _row(objective_id=child_id, status="completed"),
                _row(objective_id=sibling_id, status="completed"),
            ]
            return result

        if "UPDATE objectives SET status=:status" in stmt_str:
            result.rowcount = 1
            return result

        result.first.return_value = None
        result.fetchall.return_value = []
        result.rowcount = 0
        return result

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.integrator import _advance_parent_objective
    kimi = AsyncMock()

    with patch(
        "nexus_engine.integrator._synthesize_parent_objective",
        new_callable=AsyncMock,
    ) as synthesize:
        await _advance_parent_objective(
            engine=engine,
            kimi_client=kimi,
            objective_id=child_id,
        )

    synthesize.assert_awaited_once_with(
        engine,
        kimi,
        parent_id,
        settings=None,
    )


@pytest.mark.asyncio
async def test_advance_parent_objective_redispatches_parent_dag_when_children_remain():
    parent_id = uuid4()
    child_id = uuid4()
    proposed_sibling = uuid4()

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "SELECT objectives.parent_objective_id" in stmt_str:
            result.first.return_value = _row(parent_objective_id=parent_id)
            return result

        if "SELECT objectives.objective_id, objectives.status" in stmt_str:
            result.fetchall.return_value = [
                _row(objective_id=child_id, status="completed"),
                _row(objective_id=proposed_sibling, status="proposed"),
            ]
            return result

        result.first.return_value = None
        result.fetchall.return_value = []
        result.rowcount = 0
        return result

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.integrator import _advance_parent_objective
    kimi = AsyncMock()
    dispatcher = SimpleNamespace(dispatch_dag=AsyncMock())

    with patch(
        "nexus_engine.integrator._make_dispatcher",
        return_value=dispatcher,
    ), patch(
        "nexus_engine.integrator._synthesize_parent_objective",
        new_callable=AsyncMock,
    ) as synthesize:
        await _advance_parent_objective(
            engine=engine,
            kimi_client=kimi,
            objective_id=child_id,
        )

    dispatcher.dispatch_dag.assert_awaited_once_with(parent_id)
    synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_objective_state_from_validated_finding_completes_objective(settings):
    objective_id = uuid4()
    finding_id = uuid4()
    objective_updates = []

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "SELECT objectives.status" in stmt_str:
            result.first.return_value = _row(status="active")
            return result

        if "UPDATE objectives SET" in stmt_str:
            objective_updates.append(stmt.compile().params)
            result.rowcount = 1
            return result

        result.first.return_value = None
        result.fetchall.return_value = []
        result.rowcount = 0
        return result

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.integrator import _reconcile_objective_state_from_finding

    with patch(
        "nexus_engine.integrator.emit_event",
        new_callable=AsyncMock,
    ) as emit_event, patch(
        "nexus_engine.integrator._advance_parent_objective",
        new_callable=AsyncMock,
    ) as advance:
        recovered_status = await _reconcile_objective_state_from_finding(
            engine,
            AsyncMock(),
            objective_id=objective_id,
            finding_status="validated",
            finding_id=finding_id,
            settings=settings,
        )

    assert recovered_status == "completed"
    assert objective_updates[-1]["status"] == "completed"
    assert objective_updates[-1]["assigned_to"] is None
    assert any(call.args[1] == "objective_completed" for call in emit_event.await_args_list)
    advance.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_dag_skips_already_active_and_completed_nodes(settings):
    parent_id = uuid4()
    completed_child = uuid4()
    active_child = uuid4()
    proposed_child = uuid4()

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "FROM objective_decomposition" in stmt_str:
            result.fetchall.return_value = [
                _row(
                    parent_objective_id=parent_id,
                    child_objective_id=completed_child,
                    depends_on=[],
                    dependency_type="parallel",
                    execution_order=0,
                ),
                _row(
                    parent_objective_id=parent_id,
                    child_objective_id=active_child,
                    depends_on=[str(completed_child)],
                    dependency_type="parallel",
                    execution_order=1,
                ),
                _row(
                    parent_objective_id=parent_id,
                    child_objective_id=proposed_child,
                    depends_on=[str(active_child)],
                    dependency_type="parallel",
                    execution_order=2,
                ),
            ]
            return result

        if "SELECT objectives.objective_id, objectives.status" in stmt_str:
            result.fetchall.return_value = [
                _row(objective_id=completed_child, status="completed"),
                _row(objective_id=active_child, status="active"),
                _row(objective_id=proposed_child, status="proposed"),
            ]
            return result

        result.fetchall.return_value = []
        result.first.return_value = None
        result.rowcount = 0
        return result

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.dispatcher import Dispatcher

    dispatcher = Dispatcher(
        engine=engine,
        kimi_client=AsyncMock(),
        settings=settings,
        shutdown_event=asyncio.Event(),
    )
    dispatcher._dispatch_single = AsyncMock(return_value=True)

    await dispatcher.dispatch_dag(parent_id)

    dispatcher._dispatch_single.assert_awaited_once_with(proposed_child)


@pytest.mark.asyncio
async def test_synthesize_parent_objective_writes_synthesis_artifact():
    parent_id = uuid4()
    child_1 = uuid4()
    child_2 = uuid4()
    synthesis_instance_id = uuid4()
    synthesis_finding_id = uuid4()
    synthesis_persona_id = uuid4()

    inserted_findings = []
    telemetry_inserts = []
    objective_updates = []

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "SELECT objectives.objective_id, objectives.parent_objective_id" in stmt_str or (
            "FROM objectives" in stmt_str and "WHERE objectives.objective_id" in stmt_str
        ):
            result.first.return_value = _row(
                objective_id=parent_id,
                parent_objective_id=uuid4(),
                title="Parent Objective",
                impact_level="high-impact",
                status="synthesizing",
            )
            return result

        if "SELECT objectives.objective_id" in stmt_str and "parent_objective_id" in stmt_str:
            result.__iter__ = lambda self: iter(
                [_row(objective_id=child_1), _row(objective_id=child_2)]
            )
            return result

        if "SELECT findings.finding_id" in stmt_str:
            result.fetchall.return_value = [
                _row(
                    finding_id=uuid4(),
                    objective_id=child_1,
                    objective_title="Child Objective A",
                    title="Finding A",
                    content="Alpha",
                    kg_nodes_created=["node-a"],
                    kg_edges_created=["edge-a"],
                ),
                _row(
                    finding_id=uuid4(),
                    objective_id=child_2,
                    objective_title="Child Objective B",
                    title="Finding B",
                    content="Beta",
                    kg_nodes_created=["node-b"],
                    kg_edges_created=["edge-b"],
                ),
            ]
            return result

        if "FROM agent_personas" in stmt_str and "SELECT" in stmt_str.upper():
            result.first.return_value = _row(
                persona_id=synthesis_persona_id,
                persona_name="Systems Synthesizer",
                role_class="synthesizer",
                reputation_score=Decimal("0.900"),
                status="active",
            )
            return result

        if "INSERT INTO agent_instances" in stmt_str:
            result.scalar_one.return_value = synthesis_instance_id
            return result

        if "INSERT INTO findings" in stmt_str:
            inserted_findings.append(stmt.compile().params)
            result.scalar_one.return_value = synthesis_finding_id
            return result

        if "INSERT INTO agent_telemetry" in stmt_str:
            telemetry_inserts.append(stmt.compile().params)
            return result

        if "UPDATE objectives SET status=:status" in stmt_str:
            objective_updates.append(stmt.compile().params)
            return result

        if "INSERT INTO events" in stmt_str:
            return result

        result.first.return_value = None
        result.fetchall.return_value = []
        return result

    engine, _ = _make_engine(mock_execute)
    kimi = AsyncMock()
    kimi.call_thinking = AsyncMock(
        return_value=_kimi_response("# Final Synthesis\n\nCombined result.")
    )

    from nexus_engine.integrator import _synthesize_parent_objective

    with patch(
        "nexus_engine.integrator._advance_parent_objective",
        new_callable=AsyncMock,
    ), patch(
        "nexus_engine.integrator._publish_recommendation_report",
        new_callable=AsyncMock,
    ):
        await _synthesize_parent_objective(
            engine=engine,
            kimi_client=kimi,
            parent_id=parent_id,
        )

    assert inserted_findings[0]["finding_type"] == "synthesis"
    assert inserted_findings[0]["status"] == "validated"
    assert telemetry_inserts, "Synthesis should emit telemetry"
    assert objective_updates[-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_write_to_kg_skips_unlabeled_entities():
    objective_id = uuid4()
    instance_id = uuid4()
    node_id = uuid4()
    finding_updates = []
    finding = _row(
        finding_id=uuid4(),
        structured_data={
            "kg_entities": [
                {"label": "", "type": "concept", "properties": {}},
                {"type": "concept", "properties": {"score": 0.9}},
                {"label": "Automation Exposure", "type": "concept", "properties": {"score": 0.9}},
            ],
            "kg_relationships": [],
        },
    )
    instance = _row(
        objective_id=objective_id,
        instance_id=instance_id,
    )

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "SELECT knowledge_graph_nodes.label" in stmt_str:
            result.first.return_value = _row(
                label="Automation Exposure",
                node_type="concept",
            )
            return result

        if "UPDATE findings SET" in stmt_str:
            finding_updates.append(stmt.compile().params)
            return result

        return result

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.integrator import _write_to_kg

    with patch(
        "nexus_engine.integrator.create_node",
        new=AsyncMock(return_value=(node_id, True)),
    ) as create_node, patch(
        "nexus_engine.integrator.create_edge",
        new=AsyncMock(),
    ) as create_edge:
        summary = await _write_to_kg(engine, finding, instance)

    create_node.assert_awaited_once()
    assert create_node.await_args.kwargs["label"] == "Automation Exposure"
    create_edge.assert_not_called()
    assert len(summary.nodes) == 1
    assert summary.nodes[0].label == "Automation Exposure"
    assert finding_updates[-1]["kg_nodes_created"] == [str(node_id)]
    assert finding_updates[-1]["kg_edges_created"] == []


@pytest.mark.asyncio
async def test_write_to_kg_returns_edge_summary_and_persists_edge_ids():
    objective_id = uuid4()
    instance_id = uuid4()
    source_node_id = uuid4()
    target_node_id = uuid4()
    edge_id = uuid4()
    finding_updates = []
    finding = _row(
        finding_id=uuid4(),
        structured_data={
            "kg_entities": [
                {"label": "Automation", "type": "concept", "properties": {"score": 0.8}},
                {"label": "Job Loss", "type": "finding", "properties": {"severity": "high"}},
            ],
            "kg_relationships": [
                {"source": "Automation", "target": "Job Loss", "type": "causes", "weight": 0.9}
            ],
        },
    )
    instance = _row(objective_id=objective_id, instance_id=instance_id)

    node_rows = {
        source_node_id: _row(label="Automation", node_type="concept"),
        target_node_id: _row(label="Job Loss", node_type="finding"),
    }

    async def mock_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)

        if "SELECT knowledge_graph_nodes.label" in stmt_str:
            node_id = stmt.compile().params["node_id_1"]
            result.first.return_value = node_rows[node_id]
            return result

        if "UPDATE findings SET" in stmt_str:
            finding_updates.append(stmt.compile().params)
            return result

        return result

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.integrator import _write_to_kg

    with patch(
        "nexus_engine.integrator.create_node",
        new=AsyncMock(side_effect=[(source_node_id, True), (target_node_id, False)]),
    ), patch(
        "nexus_engine.integrator.create_edge",
        new=AsyncMock(return_value=edge_id),
    ):
        summary = await _write_to_kg(engine, finding, instance)

    assert [node.action for node in summary.nodes] == ["created", "merged"]
    assert len(summary.edges) == 1
    assert summary.edges[0].relationship_type == "causes"
    assert finding_updates[-1]["kg_nodes_created"] == [
        str(source_node_id),
        str(target_node_id),
    ]
    assert finding_updates[-1]["kg_edges_created"] == [str(edge_id)]
