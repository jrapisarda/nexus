"""Unit tests for nexus_core.economy.ledger — mint_credits, distribute_bounty, and helpers."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_conn():
    """Create a mock async database connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    return conn


# ---------------------------------------------------------------------------
# mint_credits
# ---------------------------------------------------------------------------

class TestMintCredits:

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_mint_credits_inserts_row(self, mock_emit, mock_conn):
        """mint_credits should execute an INSERT and return a transaction_id."""
        from nexus_core.economy.ledger import mint_credits

        tx_id = uuid4()
        persona_id = uuid4()

        # Mock the result of the INSERT returning a transaction_id
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = tx_id
        mock_conn.execute.return_value = mock_result

        result = await mint_credits(
            conn=mock_conn,
            amount=Decimal("100.00"),
            to_persona_id=persona_id,
            memo="Initial credits",
        )

        assert result == tx_id
        # execute should have been called at least once for the insert
        assert mock_conn.execute.call_count >= 1
        # emit_event should have been called with economy_mint
        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        assert call_kwargs[0][1] == "economy_mint"

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_mint_credits_with_objective_reference(self, mock_emit, mock_conn):
        """mint_credits with reference_objective_id should pass it through."""
        from nexus_core.economy.ledger import mint_credits

        tx_id = uuid4()
        persona_id = uuid4()
        objective_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = tx_id
        mock_conn.execute.return_value = mock_result

        result = await mint_credits(
            conn=mock_conn,
            amount=Decimal("50.00"),
            to_persona_id=persona_id,
            reference_objective_id=objective_id,
            memo="Objective bounty",
        )

        assert result == tx_id
        # Verify the insert call was made
        insert_call = mock_conn.execute.call_args_list[0]
        insert_clause = insert_call[0][0]
        compiled = insert_clause.compile()
        params = compiled.params
        assert params["to_persona_id"] == persona_id
        assert params["amount"] == Decimal("50.00")
        assert params["transaction_type"] == "mint"
        assert params["reference_objective_id"] == objective_id

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_mint_credits_from_persona_is_none(self, mock_emit, mock_conn):
        """System mints should have from_persona_id=None."""
        from nexus_core.economy.ledger import mint_credits

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = uuid4()
        mock_conn.execute.return_value = mock_result

        await mint_credits(
            conn=mock_conn,
            amount=Decimal("10.00"),
            to_persona_id=uuid4(),
        )

        insert_call = mock_conn.execute.call_args_list[0]
        insert_clause = insert_call[0][0]
        compiled = insert_clause.compile()
        params = compiled.params
        assert params["from_persona_id"] is None


# ---------------------------------------------------------------------------
# distribute_bounty
# ---------------------------------------------------------------------------

class TestDistributeBounty:

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_distribute_bounty_70_30_split(self, mock_emit, mock_conn):
        """Quality-adjusted bounty flow pays 70% to the completer and 30% to reviewers."""
        from nexus_core.economy.ledger import distribute_bounty

        objective_id = uuid4()
        finding_id = uuid4()
        completer_id = uuid4()
        reviewer_id = uuid4()
        total_bounty = Decimal("100.00")

        tx_ids = [uuid4() for _ in range(2)]
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            mock_result = MagicMock()
            if call_count < len(tx_ids):
                mock_result.scalar_one.return_value = tx_ids[call_count]
            call_count += 1
            return mock_result

        mock_conn.execute.side_effect = side_effect

        result = await distribute_bounty(
            conn=mock_conn,
            objective_id=objective_id,
            finding_id=finding_id,
            completer_persona_id=completer_id,
            reviewer_persona_ids=[reviewer_id],
            red_team_persona_ids=[uuid4()],
            total_bounty=total_bounty,
        )

        assert len(result) == 2
        insert_calls = mock_conn.execute.call_args_list

        # First call: 70% to completer = $70.00
        first_insert = insert_calls[0][0][0].compile().params
        assert first_insert["amount"] == Decimal("70.00")
        assert first_insert["to_persona_id"] == completer_id
        assert first_insert["transaction_type"] == "bounty_claim"

        # Second call: 30% to reviewer = $30.00
        second_insert = insert_calls[1][0][0].compile().params
        assert second_insert["amount"] == Decimal("30.00")
        assert second_insert["to_persona_id"] == reviewer_id
        assert second_insert["transaction_type"] == "peer_review_fee"

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_distribute_bounty_red_team_list_is_ignored(self, mock_emit, mock_conn):
        """Automatic red-team participation no longer changes payout structure."""
        from nexus_core.economy.ledger import distribute_bounty

        completer_id = uuid4()
        reviewer_id = uuid4()
        total_bounty = Decimal("200.00")

        call_count = 0
        tx_ids = [uuid4() for _ in range(2)]

        def side_effect(*args, **kwargs):
            nonlocal call_count
            mock_result = MagicMock()
            if call_count < len(tx_ids):
                mock_result.scalar_one.return_value = tx_ids[call_count]
            call_count += 1
            return mock_result

        mock_conn.execute.side_effect = side_effect

        result = await distribute_bounty(
            conn=mock_conn,
            objective_id=uuid4(),
            finding_id=uuid4(),
            completer_persona_id=completer_id,
            reviewer_persona_ids=[reviewer_id],
            red_team_persona_ids=[uuid4(), uuid4()],
            total_bounty=total_bounty,
        )

        assert len(result) == 2

        insert_calls = mock_conn.execute.call_args_list
        first_insert = insert_calls[0][0][0].compile().params
        second_insert = insert_calls[1][0][0].compile().params
        assert first_insert["amount"] == Decimal("140.00")
        assert second_insert["amount"] == Decimal("60.00")

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_distribute_bounty_multiple_reviewers_split(self, mock_emit, mock_conn):
        """Reviewer share should be split evenly among multiple reviewers."""
        from nexus_core.economy.ledger import distribute_bounty

        reviewer_ids = [uuid4(), uuid4()]
        total_bounty = Decimal("100.00")

        tx_ids = [uuid4() for _ in range(3)]
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            mock_result = MagicMock()
            if call_count < len(tx_ids):
                mock_result.scalar_one.return_value = tx_ids[call_count]
            call_count += 1
            return mock_result

        mock_conn.execute.side_effect = side_effect

        result = await distribute_bounty(
            conn=mock_conn,
            objective_id=uuid4(),
            finding_id=uuid4(),
            completer_persona_id=uuid4(),
            reviewer_persona_ids=reviewer_ids,
            red_team_persona_ids=[uuid4()],
            total_bounty=total_bounty,
        )

        assert len(result) == 3

        # 30% of 100 = 30, split between 2 = 15 each
        for i in [1, 2]:
            insert_params = mock_conn.execute.call_args_list[i][0][0].compile().params
            assert insert_params["amount"] == Decimal("15.00")

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_distribute_bounty_no_reviewers(self, mock_emit, mock_conn):
        """When there are no reviewers, only the primary completer share is paid."""
        from nexus_core.economy.ledger import distribute_bounty

        total_bounty = Decimal("100.00")

        tx_ids = [uuid4()]
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            mock_result = MagicMock()
            if call_count < len(tx_ids):
                mock_result.scalar_one.return_value = tx_ids[call_count]
            call_count += 1
            return mock_result

        mock_conn.execute.side_effect = side_effect

        result = await distribute_bounty(
            conn=mock_conn,
            objective_id=uuid4(),
            finding_id=uuid4(),
            completer_persona_id=uuid4(),
            reviewer_persona_ids=[],
            red_team_persona_ids=[uuid4()],
            total_bounty=total_bounty,
        )

        assert len(result) == 1
        insert_params = mock_conn.execute.call_args_list[0][0][0].compile().params
        assert insert_params["amount"] == Decimal("70.00")

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_distribute_bounty_emits_event(self, mock_emit, mock_conn):
        """distribute_bounty should emit a bounty_distributed event."""
        from nexus_core.economy.ledger import distribute_bounty

        tx_ids = [uuid4() for _ in range(3)]
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            mock_result = MagicMock()
            if call_count < len(tx_ids):
                mock_result.scalar_one.return_value = tx_ids[call_count]
            call_count += 1
            return mock_result

        mock_conn.execute.side_effect = side_effect

        await distribute_bounty(
            conn=mock_conn,
            objective_id=uuid4(),
            finding_id=uuid4(),
            completer_persona_id=uuid4(),
            reviewer_persona_ids=[uuid4()],
            red_team_persona_ids=[],
            total_bounty=Decimal("50.00"),
        )

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][1] == "bounty_distributed"


# ---------------------------------------------------------------------------
# get_balance
# ---------------------------------------------------------------------------

class TestGetBalance:

    async def test_get_balance_credits_minus_debits(self, mock_conn):
        """Balance should be credits received minus debits sent."""
        from nexus_core.economy.ledger import get_balance

        persona_id = uuid4()

        result = MagicMock()
        result.scalar_one.return_value = Decimal("120.00")
        mock_conn.execute.return_value = result

        balance = await get_balance(mock_conn, persona_id)
        assert balance == Decimal("120.00")

    async def test_get_balance_zero_credits(self, mock_conn):
        """With no credits and no debits, balance should be 0."""
        from nexus_core.economy.ledger import get_balance

        result = MagicMock()
        result.scalar_one.return_value = Decimal("0")
        mock_conn.execute.return_value = result

        balance = await get_balance(mock_conn, uuid4())
        assert balance == Decimal("0")


# ---------------------------------------------------------------------------
# apply_novelty_bonus
# ---------------------------------------------------------------------------

class TestApplyNoveltyBonus:

    async def test_apply_novelty_bonus_returns_tx_id(self, mock_conn):
        """apply_novelty_bonus should return the transaction_id."""
        from nexus_core.economy.ledger import apply_novelty_bonus

        tx_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = tx_id
        mock_conn.execute.return_value = mock_result

        result = await apply_novelty_bonus(
            conn=mock_conn,
            persona_id=uuid4(),
            bonus_amount=Decimal("5.00"),
        )
        assert result == tx_id

    async def test_apply_novelty_bonus_inserts_correct_type(self, mock_conn):
        """The inserted row should have transaction_type='novelty_bonus'."""
        from nexus_core.economy.ledger import apply_novelty_bonus

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = uuid4()
        mock_conn.execute.return_value = mock_result

        await apply_novelty_bonus(
            conn=mock_conn,
            persona_id=uuid4(),
            bonus_amount=Decimal("3.00"),
        )

        insert_clause = mock_conn.execute.call_args[0][0]
        params = insert_clause.compile().params
        assert params["transaction_type"] == "novelty_bonus"


# ---------------------------------------------------------------------------
# get_personas_below_threshold
# ---------------------------------------------------------------------------

class TestGetPersonasBelowThreshold:

    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_returns_personas_below_threshold(self, mock_get_all, mock_conn):
        """Should return only persona IDs with balance below the threshold."""
        from nexus_core.economy.ledger import get_personas_below_threshold

        p1, p2, p3 = uuid4(), uuid4(), uuid4()
        mock_get_all.return_value = {
            p1: Decimal("5.00"),   # below 10
            p2: Decimal("15.00"),  # above 10
            p3: Decimal("9.99"),   # below 10
        }

        result = await get_personas_below_threshold(mock_conn, Decimal("10.00"))
        assert set(result) == {p1, p3}

    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_returns_empty_when_all_above(self, mock_get_all, mock_conn):
        from nexus_core.economy.ledger import get_personas_below_threshold

        mock_get_all.return_value = {
            uuid4(): Decimal("100.00"),
            uuid4(): Decimal("200.00"),
        }

        result = await get_personas_below_threshold(mock_conn, Decimal("10.00"))
        assert result == []
