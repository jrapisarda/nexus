"""Unit tests for NEXUS evolution engine (Phase 6).

Tests the mutator, evaluator, and pruner modules.
"""

import pytest
from decimal import Decimal
from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from nexus_core.evolution.mutator import (
    MutationProposal,
    generate_mutation,
    _levenshtein_ratio,
)
from nexus_core.evolution.evaluator import EvalResult, evaluate_candidate
from nexus_core.evolution.pruner import prune_population, run_evolution_cycle


# ---------------------------------------------------------------------------
# MutationProposal dataclass
# ---------------------------------------------------------------------------

class TestMutationProposal:
    def test_creation(self):
        pid = uuid4()
        mp = MutationProposal(
            parent_persona_id=pid,
            mutated_prompt="You are a researcher.",
            changes_description="Added focus on methodology",
            expected_improvement="Better structured output",
            mutation_type="prompt_edit",
        )
        assert mp.parent_persona_id == pid
        assert mp.mutation_type == "prompt_edit"
        assert "researcher" in mp.mutated_prompt


# ---------------------------------------------------------------------------
# _levenshtein_ratio (word-level Jaccard distance)
# ---------------------------------------------------------------------------

class TestLevenshteinRatio:
    def test_identical_strings(self):
        assert _levenshtein_ratio("hello world", "hello world") == 0.0

    def test_completely_different(self):
        assert _levenshtein_ratio("hello world", "foo bar") == 1.0

    def test_both_empty(self):
        assert _levenshtein_ratio("", "") == 0.0

    def test_one_empty(self):
        assert _levenshtein_ratio("hello", "") == 1.0

    def test_partial_overlap(self):
        ratio = _levenshtein_ratio("hello world foo", "hello world bar")
        # Words: {hello, world, foo} vs {hello, world, bar}
        # union=4, intersection=2 -> 1 - 2/4 = 0.5
        assert ratio == pytest.approx(0.5)

    def test_case_insensitive(self):
        assert _levenshtein_ratio("Hello World", "hello world") == 0.0

    def test_small_change_within_threshold(self):
        base = "You are a specialized research agent focusing on biomedical literature analysis"
        mutated = "You are a specialized research agent focusing on biomedical literature synthesis"
        ratio = _levenshtein_ratio(base, mutated)
        # Only 1 word changed out of ~10
        assert ratio < 0.30

    def test_large_change_exceeds_threshold(self):
        base = "You are a researcher"
        mutated = "The system analyzes complex data patterns and generates novel insights"
        ratio = _levenshtein_ratio(base, mutated)
        assert ratio > 0.30


# ---------------------------------------------------------------------------
# EvalResult dataclass
# ---------------------------------------------------------------------------

class TestEvalResult:
    def test_creation(self):
        cid = uuid4()
        pid = uuid4()
        er = EvalResult(
            candidate_id=cid,
            parent_id=pid,
            candidate_score=0.45,
            parent_score=0.50,
            passed=True,
            reason="Candidate accepted (within threshold)",
        )
        assert er.candidate_id == cid
        assert er.passed is True

    def test_failed_result(self):
        er = EvalResult(
            candidate_id=uuid4(),
            parent_id=uuid4(),
            candidate_score=0.1,
            parent_score=0.8,
            passed=False,
            reason="Candidate below threshold",
        )
        assert er.passed is False


# ---------------------------------------------------------------------------
# generate_mutation (with mocked DB + LLM)
# ---------------------------------------------------------------------------

class TestGenerateMutation:
    @pytest.mark.asyncio
    async def test_returns_none_when_persona_not_found(self):
        conn = AsyncMock()
        # Simulate no rows returned
        result_mock = MagicMock()
        result_mock.first.return_value = None
        conn.execute = AsyncMock(return_value=result_mock)

        kimi_client = AsyncMock()
        persona_id = uuid4()

        result = await generate_mutation(conn, kimi_client, persona_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_mutation_proposal(self):
        persona_id = uuid4()
        base_prompt = "You are a specialized research agent focusing on biomedical literature analysis and synthesis of complex findings"

        # Mock persona row
        persona_row = MagicMock()
        persona_row.system_prompt_template = base_prompt
        persona_row.credit_balance = Decimal("100.00")
        persona_row.reputation_score = Decimal("0.500")

        conn = AsyncMock()
        result_mock = MagicMock()
        result_mock.first.return_value = persona_row
        conn.execute = AsyncMock(return_value=result_mock)

        # Small mutation (within 30% threshold)
        mutated_prompt = "You are a specialized research agent focusing on biomedical literature analysis and detailed synthesis of complex findings"

        # Mock Kimi response
        kimi_response = MagicMock()
        kimi_response.content = f'{{"mutated_prompt": "{mutated_prompt}", "changes_description": "Added detail focus", "expected_improvement": "More detailed output"}}'

        kimi_client = AsyncMock()
        kimi_client.call_instant = AsyncMock(return_value=kimi_response)

        with patch(
            "nexus_core.evolution.mutator.get_balance",
            new=AsyncMock(return_value=Decimal("100.00")),
        ):
            result = await generate_mutation(conn, kimi_client, persona_id)
        assert result is not None
        assert result.parent_persona_id == persona_id
        assert result.mutation_type == "prompt_edit"

    @pytest.mark.asyncio
    async def test_rejects_mutation_too_large(self):
        persona_id = uuid4()
        base_prompt = "You are a researcher"

        persona_row = MagicMock()
        persona_row.system_prompt_template = base_prompt
        persona_row.credit_balance = Decimal("100.00")
        persona_row.reputation_score = Decimal("0.500")

        conn = AsyncMock()
        result_mock = MagicMock()
        result_mock.first.return_value = persona_row
        conn.execute = AsyncMock(return_value=result_mock)

        # Completely different prompt (exceeds 30% threshold)
        mutated_prompt = "The system analyzes complex data patterns and generates novel insights about quantum computing in distributed environments"

        kimi_response = MagicMock()
        kimi_response.content = f'{{"mutated_prompt": "{mutated_prompt}", "changes_description": "Complete rewrite", "expected_improvement": "Unknown"}}'

        kimi_client = AsyncMock()
        kimi_client.call_instant = AsyncMock(return_value=kimi_response)

        with patch(
            "nexus_core.evolution.mutator.get_balance",
            new=AsyncMock(return_value=Decimal("100.00")),
        ):
            result = await generate_mutation(conn, kimi_client, persona_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_mutated_prompt(self):
        persona_id = uuid4()

        persona_row = MagicMock()
        persona_row.system_prompt_template = "Original prompt"
        persona_row.credit_balance = Decimal("50.00")
        persona_row.reputation_score = Decimal("0.500")

        conn = AsyncMock()
        result_mock = MagicMock()
        result_mock.first.return_value = persona_row
        conn.execute = AsyncMock(return_value=result_mock)

        kimi_response = MagicMock()
        kimi_response.content = '{"mutated_prompt": "", "changes_description": "Failed", "expected_improvement": ""}'

        kimi_client = AsyncMock()
        kimi_client.call_instant = AsyncMock(return_value=kimi_response)

        with patch(
            "nexus_core.evolution.mutator.get_balance",
            new=AsyncMock(return_value=Decimal("50.00")),
        ):
            result = await generate_mutation(conn, kimi_client, persona_id)
        assert result is None


# ---------------------------------------------------------------------------
# evaluate_candidate (with mocked DB)
# ---------------------------------------------------------------------------

class TestEvaluateCandidate:
    @pytest.mark.asyncio
    async def test_candidate_not_found(self):
        candidate_id = uuid4()
        parent_id = uuid4()

        conn = AsyncMock()
        # First call: calculate_fitness queries (multiple), then candidate lookup returns None
        call_count = 0

        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            # For count queries and scalar_one calls in calculate_fitness
            result.scalar_one.return_value = 0
            result.first.return_value = None
            return result

        conn.execute = mock_execute

        kimi_client = AsyncMock()

        result = await evaluate_candidate(conn, kimi_client, candidate_id, parent_id)
        assert result.passed is False
        assert "not found" in result.reason

    @pytest.mark.asyncio
    async def test_candidate_prompt_too_short(self):
        candidate_id = uuid4()
        parent_id = uuid4()

        candidate_row = MagicMock()
        candidate_row.system_prompt_template = "Short"

        call_count = 0

        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalar_one.return_value = 0
            # Return candidate row for the persona lookup
            result.first.return_value = candidate_row
            return result

        conn = AsyncMock()
        conn.execute = mock_execute

        kimi_client = AsyncMock()

        result = await evaluate_candidate(conn, kimi_client, candidate_id, parent_id)
        assert result.passed is False
        assert "too short" in result.reason

    @pytest.mark.asyncio
    async def test_candidate_passes_threshold(self):
        candidate_id = uuid4()
        parent_id = uuid4()

        candidate_row = MagicMock()
        candidate_row.system_prompt_template = "A" * 100  # >50 chars

        call_count = 0

        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalar_one.return_value = 0
            result.first.return_value = candidate_row
            return result

        conn = AsyncMock()
        conn.execute = mock_execute

        kimi_client = AsyncMock()

        result = await evaluate_candidate(conn, kimi_client, candidate_id, parent_id)
        # parent_score ≈ 0.2 (from 0 completions), candidate_score = 0.2 * 0.9 = 0.18
        # threshold = 0.2 - 0.1 = 0.1
        # 0.18 >= 0.1 => passed
        assert result.passed is True


# ---------------------------------------------------------------------------
# prune_population (with mocked DB)
# ---------------------------------------------------------------------------

class TestPrunePopulation:
    @pytest.mark.asyncio
    async def test_no_pruning_when_under_max(self):
        """No pruning needed when population is under max_active."""
        conn = AsyncMock()

        snapshots = [
            MagicMock(persona_id=uuid4(), composite_score=0.8, experimental_niche=False, role_class="researcher"),
            MagicMock(persona_id=uuid4(), composite_score=0.5, experimental_niche=False, role_class="critic"),
        ]
        with patch("nexus_core.evolution.pruner.rank_personas_with_snapshots", new=AsyncMock(return_value=snapshots)):
            result = await prune_population(conn, max_active=5, min_per_class=2)
            assert result == []

    @pytest.mark.asyncio
    async def test_no_pruning_when_equal_to_max(self):
        conn = AsyncMock()

        snapshots = [
            MagicMock(persona_id=uuid4(), composite_score=0.8, experimental_niche=False, role_class="researcher"),
            MagicMock(persona_id=uuid4(), composite_score=0.5, experimental_niche=False, role_class="critic"),
        ]
        with patch("nexus_core.evolution.pruner.rank_personas_with_snapshots", new=AsyncMock(return_value=snapshots)):
            result = await prune_population(conn, max_active=2, min_per_class=1)
            assert result == []


# ---------------------------------------------------------------------------
# run_evolution_cycle (integration-level mocks)
# ---------------------------------------------------------------------------

class TestRunEvolutionCycle:
    @pytest.mark.asyncio
    async def test_skips_when_no_personas(self):
        """Should skip gracefully when no top performers exist."""
        engine = AsyncMock()
        conn = AsyncMock()

        # Mock the engine.begin() context manager
        ctx_mgr = AsyncMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        engine.begin = MagicMock(return_value=ctx_mgr)

        from nexus_core.config import NexusSettings
        settings = NexusSettings(MOONSHOT_API_KEY="test-key")
        kimi_client = AsyncMock()

        with patch(
            "nexus_core.evolution.pruner.rank_personas_with_snapshots",
            new=AsyncMock(return_value=[]),
        ):
            await run_evolution_cycle(engine, kimi_client, settings)
            # Should not raise, just skip
