"""Unit tests for nexus_core.economy.welfare.distribute_welfare()."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


WELFARE_PERSONA_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def mock_conn():
    """Create a mock async database connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    return conn


def _make_system_query_result(system_ids: set[UUID] | None = None):
    """Build a mock result for the system persona query."""
    ids = system_ids or set()
    rows = [MagicMock(persona_id=pid) for pid in ids]
    result = MagicMock()
    result.__iter__ = lambda self: iter(rows)
    return result


class TestDistributeWelfare:
    """Tests for distribute_welfare() — async function that allocates welfare credits."""

    @patch("nexus_core.economy.welfare.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_all_balances", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_balance", new_callable=AsyncMock)
    async def test_empty_pool_returns_zero(self, mock_get_balance, mock_get_all, mock_emit, mock_conn):
        """When the welfare persona has 0 balance, no distribution should occur."""
        from nexus_core.economy.welfare import distribute_welfare

        mock_get_balance.return_value = Decimal("0")

        result = await distribute_welfare(mock_conn, floor=Decimal("30"))

        assert result == 0
        # get_all_balances should NOT be called when pool is empty
        mock_get_all.assert_not_called()
        mock_emit.assert_not_called()

    @patch("nexus_core.economy.welfare.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_all_balances", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_balance", new_callable=AsyncMock)
    async def test_no_qualifying_recipients(self, mock_get_balance, mock_get_all, mock_emit, mock_conn):
        """When all agents are above the floor, nobody receives welfare."""
        from nexus_core.economy.welfare import distribute_welfare

        mock_get_balance.return_value = Decimal("100")

        p1, p2 = uuid4(), uuid4()
        mock_get_all.return_value = {
            p1: Decimal("50"),
            p2: Decimal("40"),
        }
        # System persona query returns empty set
        mock_conn.execute.return_value = _make_system_query_result(set())

        result = await distribute_welfare(mock_conn, floor=Decimal("30"))

        assert result == 0
        mock_emit.assert_not_called()

    @patch("nexus_core.economy.welfare.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_all_balances", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_balance", new_callable=AsyncMock)
    async def test_equal_distribution(self, mock_get_balance, mock_get_all, mock_emit, mock_conn):
        """Pool of 60 credits, 3 agents at balance 10 with floor 30 -> each gets 20."""
        from nexus_core.economy.welfare import distribute_welfare

        mock_get_balance.return_value = Decimal("60")

        p1, p2, p3 = uuid4(), uuid4(), uuid4()
        mock_get_all.return_value = {
            p1: Decimal("10"),
            p2: Decimal("10"),
            p3: Decimal("10"),
        }
        # System persona query returns empty set
        mock_conn.execute.return_value = _make_system_query_result(set())

        result = await distribute_welfare(mock_conn, floor=Decimal("30"))

        assert result == 3

        # Verify each transfer was for 20 credits
        # execute is called: 1 (system query) + 3 (transfers) = 4 times
        transfer_calls = mock_conn.execute.call_args_list[1:]  # skip system query
        assert len(transfer_calls) == 3

        for call in transfer_calls:
            insert_clause = call[0][0]
            params = insert_clause.compile().params
            assert params["amount"] == Decimal("20.00")
            assert params["from_persona_id"] == WELFARE_PERSONA_ID
            assert params["transaction_type"] == "welfare_distribution"

    @patch("nexus_core.economy.welfare.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_all_balances", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_balance", new_callable=AsyncMock)
    async def test_pool_smaller_than_total_deficit(self, mock_get_balance, mock_get_all, mock_emit, mock_conn):
        """Pool of 15 credits, 3 agents need 20 each -> each gets 5."""
        from nexus_core.economy.welfare import distribute_welfare

        mock_get_balance.return_value = Decimal("15")

        p1, p2, p3 = uuid4(), uuid4(), uuid4()
        mock_get_all.return_value = {
            p1: Decimal("10"),
            p2: Decimal("10"),
            p3: Decimal("10"),
        }
        # System persona query returns empty set
        mock_conn.execute.return_value = _make_system_query_result(set())

        result = await distribute_welfare(mock_conn, floor=Decimal("30"))

        assert result == 3

        transfer_calls = mock_conn.execute.call_args_list[1:]
        assert len(transfer_calls) == 3

        for call in transfer_calls:
            insert_clause = call[0][0]
            params = insert_clause.compile().params
            assert params["amount"] == Decimal("5.00")

    @patch("nexus_core.economy.welfare.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_all_balances", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_balance", new_callable=AsyncMock)
    async def test_cap_at_floor(self, mock_get_balance, mock_get_all, mock_emit, mock_conn):
        """Agent at 25 credits with floor 30 only gets 5 (not full equal share)."""
        from nexus_core.economy.welfare import distribute_welfare

        mock_get_balance.return_value = Decimal("100")

        p1 = uuid4()
        p2 = uuid4()
        mock_get_all.return_value = {
            p1: Decimal("25"),  # deficit = 5
            p2: Decimal("10"),  # deficit = 20
        }
        # System persona query returns empty set
        mock_conn.execute.return_value = _make_system_query_result(set())

        result = await distribute_welfare(mock_conn, floor=Decimal("30"))

        assert result == 2

        # Total deficit = 25, pool (100) > deficit (25), so distributable = 25
        # Equal share = 25 / 2 = 12.50
        # p1 gets min(12.50, 5) = 5.00  (capped at deficit)
        # p2 gets min(12.50, 20) = 12.50
        transfer_calls = mock_conn.execute.call_args_list[1:]
        amounts = []
        for call in transfer_calls:
            insert_clause = call[0][0]
            params = insert_clause.compile().params
            amounts.append(params["amount"])

        assert sorted(amounts) == [Decimal("5.00"), Decimal("12.50")]

    @patch("nexus_core.economy.welfare.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_all_balances", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_balance", new_callable=AsyncMock)
    async def test_system_personas_excluded(self, mock_get_balance, mock_get_all, mock_emit, mock_conn):
        """System personas should be excluded from welfare, even if below floor."""
        from nexus_core.economy.welfare import distribute_welfare

        mock_get_balance.return_value = Decimal("100")

        system_persona = uuid4()
        normal_persona = uuid4()
        mock_get_all.return_value = {
            system_persona: Decimal("5"),
            normal_persona: Decimal("10"),
        }
        # System persona query marks one as system
        mock_conn.execute.return_value = _make_system_query_result({system_persona})

        result = await distribute_welfare(mock_conn, floor=Decimal("30"))

        # Only the normal persona should receive welfare
        assert result == 1

    @patch("nexus_core.economy.welfare.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_all_balances", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_balance", new_callable=AsyncMock)
    async def test_negative_pool_returns_zero(self, mock_get_balance, mock_get_all, mock_emit, mock_conn):
        """A negative welfare pool balance should result in no distributions."""
        from nexus_core.economy.welfare import distribute_welfare

        mock_get_balance.return_value = Decimal("-5")

        result = await distribute_welfare(mock_conn, floor=Decimal("30"))

        assert result == 0
        mock_get_all.assert_not_called()

    @patch("nexus_core.economy.welfare.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_all_balances", new_callable=AsyncMock)
    @patch("nexus_core.economy.welfare.get_balance", new_callable=AsyncMock)
    async def test_emits_event_on_distribution(self, mock_get_balance, mock_get_all, mock_emit, mock_conn):
        """distribute_welfare should emit a welfare_distributed event when recipients exist."""
        from nexus_core.economy.welfare import distribute_welfare

        mock_get_balance.return_value = Decimal("60")

        p1 = uuid4()
        mock_get_all.return_value = {p1: Decimal("10")}
        mock_conn.execute.return_value = _make_system_query_result(set())

        await distribute_welfare(mock_conn, floor=Decimal("30"))

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][1] == "welfare_distributed"
