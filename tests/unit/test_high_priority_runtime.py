from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus_core.config import NexusSettings
from nexus_core.llm.client import KimiResponse
from nexus_core.llm.response_parser import ReviewData
from nexus_core.scouts.base import ScoutFinding


def _row(**kwargs):
    row = SimpleNamespace(**kwargs)
    row._mapping = kwargs
    return row


class _Result:
    def __init__(
        self,
        *,
        first=None,
        one_or_none=None,
        scalar_one=None,
        rows=None,
        rowcount=0,
    ):
        self._first = first
        self._one_or_none = first if one_or_none is None else one_or_none
        self._scalar_one = scalar_one
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def first(self):
        return self._first

    def one_or_none(self):
        return self._one_or_none

    def scalar_one(self):
        return self._scalar_one

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


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
        thinking_tokens=0,
        output_tokens=50,
        cost_usd=Decimal("0.001000"),
        latency_ms=123,
        model="kimi-k2.5",
        prompt_hash="hash123",
    )


@pytest.fixture
def settings():
    return NexusSettings(
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
        MOONSHOT_API_KEY="test-key",
        MIN_PERSONAS_PER_ROLE_CLASS=2,
        GOVERNANCE_INTERVAL_TICKS=1,
        EVOLUTION_INTERVAL_TICKS=1,
        INFILTRATION_INTERVAL_TICKS=1,
        SCOUT_SWEEP_INTERVAL_TICKS=1,
    )


@pytest.mark.asyncio
async def test_ensure_candidate_persona_approved_creates_candidate(settings):
    candidate_id = uuid4()
    proposal_id = uuid4()
    governor_id = uuid4()
    objective = _row(
        objective_id=uuid4(),
        title="Harden review pipeline",
        description="Need adversarial critique coverage",
    )
    inserted_candidates = []
    active_candidate = _row(
        persona_id=candidate_id,
        persona_name="Candidate Critic",
        role_class="critic",
        system_prompt_template="candidate prompt",
        status="active",
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt)

        if "FROM agent_personas" in stmt_str and "WHERE agent_personas.persona_name" in stmt_str:
            return _Result(first=None)

        if "FROM agent_personas" in stmt_str and "WHERE agent_personas.role_class" in stmt_str:
            return _Result(one_or_none=_row(persona_id=governor_id))

        if "INSERT INTO agent_personas" in stmt_str:
            inserted_candidates.append(stmt.compile().params)
            return _Result(scalar_one=candidate_id)

        if (
            "FROM agent_personas" in stmt_str
            and "persona_id" in stmt_str
            and "status" in stmt_str
        ):
            return _Result(first=active_candidate)

        return _Result()

    from nexus_core.governance.runtime import ensure_candidate_persona_approved

    conn = AsyncMock()
    conn.execute = mock_execute

    with patch(
        "nexus_core.governance.runtime.create_proposal",
        new=AsyncMock(return_value=proposal_id),
    ) as create_proposal, patch(
        "nexus_core.governance.runtime.process_pending_proposals",
        new=AsyncMock(return_value=[]),
    ) as process_pending:
        result = await ensure_candidate_persona_approved(
            conn,
            objective,
            "critic",
            settings,
        )

    assert result is active_candidate
    assert inserted_candidates[0]["role_class"] == "critic"
    assert inserted_candidates[0]["status"] == "candidate"
    create_proposal.assert_awaited_once()
    process_pending.assert_awaited_once_with(conn, settings)


@pytest.mark.asyncio
async def test_dispatcher_select_persona_requests_candidate_on_role_gap(settings):
    objective = _row(
        objective_id=uuid4(),
        title="Stress test assumptions",
        description="Need a critical reviewer",
        assigned_to=None,
        acceptance_criteria="Required role class: critic",
    )
    researcher = _row(
        persona_id=uuid4(),
        persona_name="Researcher",
        role_class="researcher",
        system_prompt_template="research prompt",
        reputation_score=Decimal("0.900"),
        specialization_vector=None,
    )
    candidate = _row(
        persona_id=uuid4(),
        persona_name="Candidate Critic",
        role_class="critic",
        system_prompt_template="critic prompt",
        reputation_score=Decimal("0.500"),
    )

    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=_Result(first=researcher, rows=[researcher]))

    from nexus_engine.dispatcher import Dispatcher

    dispatcher = Dispatcher(
        engine=MagicMock(),
        kimi_client=AsyncMock(),
        settings=settings,
        shutdown_event=asyncio.Event(),
    )

    with patch(
        "nexus_engine.dispatcher.ensure_candidate_persona_approved",
        new=AsyncMock(return_value=candidate),
    ) as ensure_candidate:
        selected = await dispatcher._select_persona(conn, objective)

    assert selected is candidate
    ensure_candidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatcher_uses_debugger_after_second_execution_failure(settings):
    objective_id = uuid4()
    instance_id = uuid4()
    objective_updates = []
    instance_updates = []
    persona = _row(
        persona_id=uuid4(),
        persona_name="Researcher",
        role_class="researcher",
        system_prompt_template="You are a researcher.",
        reputation_score=Decimal("0.900"),
        specialization_vector=None,
    )
    objective = _row(
        objective_id=objective_id,
        title="Collect evidence",
        description="Gather supporting literature.",
        impact_level="routine",
        assigned_to=None,
        knowledge_graph_anchor=[],
        acceptance_criteria="Required role class: researcher",
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt)

        if "FROM objectives" in stmt_str and "SELECT" in stmt_str:
            return _Result(first=objective)

        if "FROM agent_personas" in stmt_str and "SELECT" in stmt_str:
            return _Result(first=persona, rows=[persona])

        if "FROM institutional_memory" in stmt_str and "SELECT" in stmt_str:
            return _Result(rows=[])

        if "UPDATE objectives SET" in stmt_str:
            objective_updates.append(stmt.compile().params)
            return _Result(rowcount=1)

        if "INSERT INTO agent_instances" in stmt_str:
            return _Result(scalar_one=instance_id)

        if "UPDATE agent_instances SET" in stmt_str:
            instance_updates.append(stmt.compile().params)
            return _Result()

        if "INSERT INTO events" in stmt_str:
            return _Result()

        return _Result()

    engine, _ = _make_engine(mock_execute)
    kimi = AsyncMock()
    kimi.call_thinking = AsyncMock(
        side_effect=[RuntimeError("first boom"), RuntimeError("second boom")]
    )

    from nexus_engine.dispatcher import Dispatcher

    dispatcher = Dispatcher(
        engine=engine,
        kimi_client=kimi,
        settings=settings,
        shutdown_event=asyncio.Event(),
    )

    with patch(
        "nexus_engine.dispatcher.diagnose_failure",
        new=AsyncMock(return_value=None),
    ) as diagnose_failure:
        success = await dispatcher.dispatch_objective(objective_id)

    assert success is False
    assert instance_updates[-1]["status"] == "failed"
    assert objective_updates[-1]["status"] == "failed"
    diagnose_failure.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrate_review_requests_single_revision_on_first_failed_round():
    finding_id = uuid4()
    objective_id = uuid4()
    finding_updates = []
    review = ReviewData(
        methodology_critique="Issue",
        evidence_evaluation="Weak evidence",
        novelty_assessment="Limited novelty",
        confidence_rating=0.3,
        verdict="reject",
        revision_feedback="Tighten the evidence chain.",
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt)

        if "FROM findings" in stmt_str and "SELECT findings.review_round" not in stmt_str:
            return _Result(
                one_or_none=_row(
                    finding_id=finding_id,
                    objective_id=objective_id,
                    impact_level="routine",
                    kg_nodes_created=[],
                    instance_id=uuid4(),
                )
            )

        if "FROM objectives" in stmt_str and "SELECT" in stmt_str:
            return _Result(
                one_or_none=_row(
                    objective_id=objective_id,
                    compute_budget_allocated=Decimal("10.00"),
                    impact_level="routine",
                )
            )

        if "INSERT INTO peer_reviews" in stmt_str:
            return _Result()

        if "SELECT findings.review_round" in stmt_str:
            return _Result(scalar_one=0)

        if "UPDATE findings SET" in stmt_str:
            finding_updates.append(stmt.compile().params)
            return _Result()

        return _Result()

    conn = AsyncMock()
    conn.execute = mock_execute

    from nexus_core.review.peer_review import orchestrate_review

    with patch(
        "nexus_core.review.peer_review.classify_impact",
        new=AsyncMock(return_value="routine"),
    ), patch(
        "nexus_core.review.peer_review.select_reviewers",
        new=AsyncMock(return_value=[uuid4(), uuid4()]),
    ), patch(
        "nexus_core.review.peer_review._dispatch_single_review",
        new=AsyncMock(side_effect=[(review, uuid4()), (review, uuid4())]),
    ), patch(
        "nexus_core.review.peer_review.emit_event",
        new=AsyncMock(),
    ) as emit_event:
        outcome = await orchestrate_review(conn, AsyncMock(), finding_id)

    assert outcome.verdict == "rejected"
    assert outcome.mean_review_confidence == 0.3
    assert outcome.approval_count == 0
    assert outcome.reviewer_count == 2
    assert outcome.verdict_breakdown == {"reject": 2}
    assert outcome.required_consensus == "majority support"
    assert outcome.reject_count == 2
    assert outcome.support_count == 0
    assert outcome.support_ratio == 0.0
    assert finding_updates[-1]["status"] == "revision_requested"
    assert finding_updates[-1]["review_round"] == 1
    finding_reviewed_call = next(
        call for call in emit_event.await_args_list if call.args[1] == "finding_reviewed"
    )
    payload = finding_reviewed_call.kwargs["payload"]
    assert payload["mean_review_confidence"] == 0.3
    assert payload["approval_count"] == 0
    assert payload["reviewer_count"] == 2
    assert payload["verdict_breakdown"] == {"reject": 2}
    assert payload["required_consensus"] == "majority support"
    assert payload["reject_count"] == 2
    assert payload["support_count"] == 0
    assert payload["support_ratio"] == 0.0


@pytest.mark.asyncio
async def test_orchestrate_review_escalates_after_second_failed_round():
    finding_id = uuid4()
    objective_id = uuid4()
    finding_updates = []
    review = ReviewData(
        methodology_critique="Issue",
        evidence_evaluation="Weak evidence",
        novelty_assessment="Limited novelty",
        confidence_rating=0.2,
        verdict="reject",
        revision_feedback="Still not correct.",
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt)

        if "FROM findings" in stmt_str and "SELECT findings.review_round" not in stmt_str:
            return _Result(
                one_or_none=_row(
                    finding_id=finding_id,
                    objective_id=objective_id,
                    impact_level="routine",
                    kg_nodes_created=[],
                    instance_id=uuid4(),
                )
            )

        if "FROM objectives" in stmt_str and "SELECT" in stmt_str:
            return _Result(
                one_or_none=_row(
                    objective_id=objective_id,
                    compute_budget_allocated=Decimal("10.00"),
                    impact_level="routine",
                )
            )

        if "INSERT INTO peer_reviews" in stmt_str:
            return _Result()

        if "SELECT findings.review_round" in stmt_str:
            return _Result(scalar_one=1)

        if "UPDATE findings SET" in stmt_str:
            finding_updates.append(stmt.compile().params)
            return _Result()

        return _Result()

    conn = AsyncMock()
    conn.execute = mock_execute

    from nexus_core.review.peer_review import orchestrate_review

    with patch(
        "nexus_core.review.peer_review.classify_impact",
        new=AsyncMock(return_value="routine"),
    ), patch(
        "nexus_core.review.peer_review.select_reviewers",
        new=AsyncMock(return_value=[uuid4(), uuid4()]),
    ), patch(
        "nexus_core.review.peer_review._dispatch_single_review",
        new=AsyncMock(side_effect=[(review, uuid4()), (review, uuid4())]),
    ), patch(
        "nexus_core.review.peer_review.emit_event",
        new=AsyncMock(),
    ) as emit_event:
        outcome = await orchestrate_review(conn, AsyncMock(), finding_id)

    assert outcome.verdict == "escalated"
    assert outcome.mean_review_confidence == 0.2
    assert outcome.approval_count == 0
    assert outcome.reviewer_count == 2
    assert outcome.verdict_breakdown == {"reject": 2}
    assert outcome.required_consensus == "majority support"
    assert outcome.reject_count == 2
    assert outcome.support_count == 0
    assert outcome.support_ratio == 0.0
    assert finding_updates[-1]["status"] == "escalated"
    assert finding_updates[-1]["review_round"] == 2
    assert any(call.args[1] == "review_escalated" for call in emit_event.await_args_list)


@pytest.mark.asyncio
async def test_orchestrate_review_defers_when_review_quorum_unmet():
    finding_id = uuid4()
    objective_id = uuid4()
    finding_updates = []
    review = ReviewData(
        methodology_critique="Solid enough to parse",
        evidence_evaluation="Evidence is directional",
        novelty_assessment="Reasonable synthesis",
        confidence_rating=0.7,
        verdict="revise",
        revision_feedback="Tighten the boundary conditions.",
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt)

        if "FROM findings" in stmt_str and "SELECT findings.review_round" not in stmt_str:
            return _Result(
                one_or_none=_row(
                    finding_id=finding_id,
                    objective_id=objective_id,
                    impact_level="high-impact",
                    kg_nodes_created=[],
                    instance_id=uuid4(),
                )
            )

        if "FROM objectives" in stmt_str and "SELECT" in stmt_str:
            return _Result(
                one_or_none=_row(
                    objective_id=objective_id,
                    compute_budget_allocated=Decimal("10.00"),
                    impact_level="high-impact",
                )
            )

        if "UPDATE findings SET" in stmt_str:
            finding_updates.append(stmt.compile().params)
            return _Result()

        if "INSERT INTO peer_reviews" in stmt_str:
            return _Result()

        return _Result()

    conn = AsyncMock()
    conn.execute = mock_execute

    from nexus_core.review.peer_review import ReviewDeferredError, orchestrate_review

    reviewers = [uuid4(), uuid4(), uuid4()]
    with patch(
        "nexus_core.review.peer_review.classify_impact",
        new=AsyncMock(return_value="high-impact"),
    ), patch(
        "nexus_core.review.peer_review.select_reviewers",
        new=AsyncMock(return_value=reviewers),
    ), patch(
        "nexus_core.review.peer_review._dispatch_single_review",
        new=AsyncMock(side_effect=[(review, uuid4()), (None, None), (None, None)]),
    ), patch(
        "nexus_core.review.peer_review.emit_event",
        new=AsyncMock(),
    ) as emit_event:
        with pytest.raises(ReviewDeferredError, match="Peer review quorum not reached"):
            await orchestrate_review(conn, AsyncMock(), finding_id)

    assert not any("status" in update for update in finding_updates)
    emit_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_orchestrate_review_defers_when_all_review_calls_fail():
    finding_id = uuid4()
    objective_id = uuid4()
    finding_updates = []

    async def mock_execute(stmt):
        stmt_str = str(stmt)

        if "FROM findings" in stmt_str and "SELECT findings.review_round" not in stmt_str:
            return _Result(
                one_or_none=_row(
                    finding_id=finding_id,
                    objective_id=objective_id,
                    impact_level="routine",
                    kg_nodes_created=[],
                    instance_id=uuid4(),
                )
            )

        if "FROM objectives" in stmt_str and "SELECT" in stmt_str:
            return _Result(
                one_or_none=_row(
                    objective_id=objective_id,
                    compute_budget_allocated=Decimal("10.00"),
                    impact_level="routine",
                )
            )

        if "UPDATE findings SET" in stmt_str:
            finding_updates.append(stmt.compile().params)
            return _Result()

        if "INSERT INTO peer_reviews" in stmt_str:
            return _Result()

        return _Result()

    conn = AsyncMock()
    conn.execute = mock_execute

    from nexus_core.review.peer_review import ReviewDeferredError, orchestrate_review

    with patch(
        "nexus_core.review.peer_review.classify_impact",
        new=AsyncMock(return_value="routine"),
    ), patch(
        "nexus_core.review.peer_review.select_reviewers",
        new=AsyncMock(return_value=[uuid4(), uuid4()]),
    ), patch(
        "nexus_core.review.peer_review._dispatch_single_review",
        new=AsyncMock(side_effect=[(None, None), (None, None)]),
    ), patch(
        "nexus_core.review.peer_review.emit_event",
        new=AsyncMock(),
    ) as emit_event:
        with pytest.raises(ReviewDeferredError, match="Peer review quorum not reached"):
            await orchestrate_review(conn, AsyncMock(), finding_id)

    assert not any("status" in update for update in finding_updates)
    emit_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_orchestrate_review_high_impact_accepts_strong_revise_consensus():
    finding_id = uuid4()
    objective_id = uuid4()
    author_persona_id = uuid4()
    finding_updates = []
    review = ReviewData(
        methodology_critique="Solid framing with minor gaps",
        evidence_evaluation="Evidence is directionally strong",
        novelty_assessment="Useful synthesis",
        confidence_rating=0.72,
        verdict="revise",
        revision_feedback="Tighten one claim before archival.",
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt)

        if "FROM findings" in stmt_str and "SELECT findings.review_round" not in stmt_str:
            return _Result(
                one_or_none=_row(
                    finding_id=finding_id,
                    objective_id=objective_id,
                    impact_level="high-impact",
                    kg_nodes_created=[],
                    instance_id=uuid4(),
                )
            )

        if "FROM objectives" in stmt_str and "SELECT" in stmt_str:
            return _Result(
                one_or_none=_row(
                    objective_id=objective_id,
                    compute_budget_allocated=Decimal("10.00"),
                    impact_level="high-impact",
                )
            )

        if "WHERE agent_instances.instance_id =" in stmt_str:
            return _Result(one_or_none=_row(persona_id=author_persona_id))

        if "INSERT INTO peer_reviews" in stmt_str:
            return _Result()

        if "SELECT findings.review_round" in stmt_str:
            return _Result(scalar_one=0)

        if "UPDATE findings SET" in stmt_str:
            finding_updates.append(stmt.compile().params)
            return _Result()

        return _Result()

    conn = AsyncMock()
    conn.execute = mock_execute

    from nexus_core.review.peer_review import orchestrate_review

    reviewers = [uuid4(), uuid4(), uuid4()]
    with patch(
        "nexus_core.review.peer_review.classify_impact",
        new=AsyncMock(return_value="high-impact"),
    ), patch(
        "nexus_core.review.peer_review.select_reviewers",
        new=AsyncMock(return_value=reviewers),
    ), patch(
        "nexus_core.review.peer_review._dispatch_single_review",
        new=AsyncMock(side_effect=[(review, uuid4()), (review, uuid4()), (review, uuid4())]),
    ), patch(
        "nexus_core.review.peer_review.distribute_bounty",
        new=AsyncMock(),
    ), patch(
        "nexus_core.review.peer_review.emit_event",
        new=AsyncMock(),
    ) as emit_event:
        outcome = await orchestrate_review(conn, AsyncMock(), finding_id)

    assert outcome.verdict == "approved"
    assert outcome.mean_review_confidence == 0.72
    assert outcome.approval_count == 0
    assert outcome.revise_count == 3
    assert outcome.reject_count == 0
    assert outcome.support_count == 3
    assert outcome.support_ratio == 0.7
    assert outcome.verdict_breakdown == {"revise": 3}
    assert outcome.required_consensus == "two-thirds support with no rejects"
    assert finding_updates[-1]["status"] == "validated"
    assert finding_updates[-1]["review_round"] == 1
    finding_reviewed_call = next(
        call for call in emit_event.await_args_list if call.args[1] == "finding_reviewed"
    )
    payload = finding_reviewed_call.kwargs["payload"]
    assert payload["approval_count"] == 0
    assert payload["revise_count"] == 3
    assert payload["reject_count"] == 0
    assert payload["support_count"] == 3
    assert payload["support_ratio"] == 0.7
    assert payload["required_consensus"] == "two-thirds support with no rejects"


@pytest.mark.asyncio
async def test_dispatch_single_review_retries_once_after_invalid_json():
    finding = _row(
        finding_id=uuid4(),
        objective_id=uuid4(),
        title="Test finding",
        content="Test content",
    )
    reviewer_persona_id = uuid4()
    reviewer_instance_id = uuid4()
    instance_updates = []

    async def mock_execute(stmt):
        stmt_str = str(stmt)

        if "INSERT INTO agent_instances" in stmt_str:
            return _Result(scalar_one=reviewer_instance_id)

        if "UPDATE agent_instances SET" in stmt_str:
            instance_updates.append(stmt.compile().params)
            return _Result()

        return _Result()

    conn = AsyncMock()
    conn.execute = mock_execute
    kimi_client = AsyncMock()
    kimi_client.call_thinking = AsyncMock(
        side_effect=[
            _kimi_response('{"methodology_critique": "broken'),
            _kimi_response(
                '{"methodology_critique": "Solid", '
                '"evidence_evaluation": "Good", '
                '"novelty_assessment": "Useful", '
                '"confidence_rating": 0.8, '
                '"verdict": "approve", '
                '"revision_feedback": null}'
            ),
        ]
    )

    from nexus_core.review.peer_review import _dispatch_single_review

    review_data, instance_id = await _dispatch_single_review(
        conn,
        kimi_client,
        finding,
        "routine",
        reviewer_persona_id,
    )

    assert instance_id == reviewer_instance_id
    assert review_data is not None
    assert review_data.verdict == "approve"
    assert kimi_client.call_thinking.await_count == 2
    assert instance_updates[-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_scheduler_runs_high_priority_periodic_hooks(settings):
    objective_id = uuid4()

    async def mock_execute(stmt):
        stmt_str = str(stmt)
        if "FROM objectives" in stmt_str and "SELECT" in stmt_str:
            return _Result(one_or_none=_row(objective_id=objective_id))
        return _Result()

    engine, _ = _make_engine(mock_execute)

    from nexus_engine.scheduler import SchedulerLoop

    scheduler = SchedulerLoop(
        engine=engine,
        kimi_client=AsyncMock(),
        settings=settings,
        shutdown_event=asyncio.Event(),
    )
    scheduler._tick_count = 1

    with patch(
        "nexus_engine.scheduler.process_pending_proposals",
        new=AsyncMock(return_value=["approved"]),
    ) as process_pending, patch(
        "nexus_engine.scheduler.select_findings_for_challenge",
        new=AsyncMock(return_value=[uuid4()]),
    ) as select_findings, patch(
        "nexus_engine.scheduler.dispatch_challenge",
        new=AsyncMock(return_value=object()),
    ) as dispatch_challenge, patch(
        "nexus_engine.scheduler.process_challenge",
        new=AsyncMock(),
    ) as process_challenge, patch(
        "nexus_engine.scheduler.inject_infiltration",
        new=AsyncMock(return_value=uuid4()),
    ) as inject_infiltration, patch(
        "nexus_engine.scheduler.run_evolution_cycle",
        new=AsyncMock(),
    ) as run_evolution_cycle, patch(
        "nexus_engine.scheduler.run_scout_sweep",
        new=AsyncMock(
            return_value={
                "topics": ["quantum"],
                "raw_findings": [],
                "persisted_findings": [{"title": "signal"}],
                "proposed_objectives": 1,
            }
        ),
    ) as run_scout_sweep:
        await scheduler._run_governance_cycle()
        await scheduler._run_red_team_cycle()
        await scheduler._maybe_infiltration_test()
        await scheduler._maybe_run_evolution()
        await scheduler._maybe_run_scout_cycle()

    process_pending.assert_awaited_once()
    select_findings.assert_awaited_once()
    dispatch_challenge.assert_awaited_once()
    process_challenge.assert_awaited_once()
    inject_infiltration.assert_awaited_once()
    run_evolution_cycle.assert_awaited_once()
    run_scout_sweep.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_scout_sweep_persists_findings_and_exploratory_objectives(settings):
    objective_id = uuid4()
    scout_persona_id = uuid4()
    scout_persona_id_2 = uuid4()
    instance_id = uuid4()
    finding_id = uuid4()
    inserted_findings = []
    inserted_objectives = []

    objective = _row(
        objective_id=objective_id,
        title="Quantum error correction roadmap",
        description="Investigate neural decoder patents and decoder methods",
        priority=7,
    )
    scout_persona = _row(
        persona_id=scout_persona_id,
        persona_name="Scout",
    )
    scout_persona_2 = _row(
        persona_id=scout_persona_id_2,
        persona_name="Scout Two",
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt)

        if "FROM objectives" in stmt_str and "SELECT" in stmt_str:
            return _Result(rows=[objective])

        if "FROM agent_personas" in stmt_str and "SELECT" in stmt_str:
            return _Result(rows=[scout_persona, scout_persona_2])

        if "SELECT findings.finding_id" in stmt_str:
            return _Result(first=None)

        if "INSERT INTO agent_instances" in stmt_str:
            return _Result(scalar_one=instance_id)

        if "INSERT INTO findings" in stmt_str:
            inserted_findings.append(stmt.compile().params)
            return _Result(scalar_one=finding_id)

        if "INSERT INTO objectives" in stmt_str:
            inserted_objectives.append(stmt.compile().params)
            return _Result()

        if "INSERT INTO events" in stmt_str:
            return _Result()

        return _Result()

    engine, _ = _make_engine(mock_execute)

    class _FakeScout:
        source_name = "google_patents"

        async def scan_for_topics(self, topics, limit_per_topic=5):
            return [
                ScoutFinding(
                    title="Quantum error correction decoder patent",
                    abstract="Neural decoder method for quantum error correction circuits.",
                    source_url="https://patents.google.com/patent/US123/en",
                    source_type="google_patents",
                )
            ]

        async def close(self):
            return None

    from nexus_core.scouts.workflow import run_scout_sweep

    with patch.dict(
        "nexus_core.scouts.workflow.SCOUT_SOURCES",
        {"google_patents": lambda _settings: _FakeScout()},
        clear=True,
    ):
        summary = await run_scout_sweep(
            engine,
            settings,
            source="google_patents",
            limit_per_topic=1,
        )

    assert summary["proposed_objectives"] == 1
    assert inserted_findings[0]["finding_type"] == "external_intelligence"
    assert inserted_findings[0]["structured_data"]["citations"][0]["source_name"] == "Google Patents"
    assert inserted_findings[0]["structured_data"]["citations"][0]["source_type"] == "patent"
    assert inserted_objectives[0]["objective_type"] == "exploratory"
    assert inserted_objectives[0]["approved_by_type"] == "self"
