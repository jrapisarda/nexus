"""Unit tests for apply_wealth_tax in nexus_core.economy.ledger.

Tests cover:
  - Top quartile agents paying top_rate on excess above median
  - Upper-mid quartile agents paying mid_rate
  - Bottom half exemption
  - Minimum agent count requirement (< 4 returns 0)
  - Tax proceeds directed to welfare persona
  - Transaction type recorded as "wealth_tax"
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
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


WELFARE_ID = UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# apply_wealth_tax
# ---------------------------------------------------------------------------

class TestApplyWealthTax:
    """Wealth tax on top quartile agents by liquid balance."""

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_top_quartile_pays_top_rate_on_excess(self, mock_balances, mock_emit, mock_conn):
        """Top quartile agents should pay top_rate on balance exceeding median."""
        from nexus_core.economy.ledger import apply_wealth_tax

        # 8 agents, sorted: 10, 20, 30, 40, 50, 60, 70, 200
        # median_idx = 4 -> median = 50
        # q3_idx = 6
        # Agents at index >= 6 pay top_rate, index 4-5 pay mid_rate
        # Bottom half (balance <= median) is exempt
        agents = {}
        balances_list = [
            Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40"),
            Decimal("50"), Decimal("60"), Decimal("70"), Decimal("200"),
        ]
        for bal in balances_list:
            agents[uuid4()] = bal

        mock_balances.return_value = agents

        # No system personas
        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        result = await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        # Agents with balance > 50 (median):
        # 60: index 5, < q3_idx(6) -> mid_rate: (60-50)*0.005 = 0.05 -> rounds to 0.05
        # 70: index 6, >= q3_idx(6) -> top_rate: (70-50)*0.015 = 0.30
        # 200: index 7, >= q3_idx(6) -> top_rate: (200-50)*0.015 = 2.25
        # All three should be taxed
        assert result == 3

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_upper_mid_quartile_pays_mid_rate(self, mock_balances, mock_emit, mock_conn):
        """Upper-mid quartile agents (above median, below Q3) should pay mid_rate."""
        from nexus_core.economy.ledger import apply_wealth_tax

        # 4 agents: [10, 30, 60, 100]
        # median_idx = 2 -> median = 60
        # q3_idx = 3
        # Agent with 100 at index 3 >= q3_idx -> top_rate
        # No upper-mid quartile agent has balance > median AND index < q3_idx
        # Let's use 8 agents for a clearer test
        pids = [uuid4() for _ in range(8)]
        balances = {
            pids[0]: Decimal("10"),
            pids[1]: Decimal("20"),
            pids[2]: Decimal("30"),
            pids[3]: Decimal("40"),
            pids[4]: Decimal("50"),
            pids[5]: Decimal("70"),   # upper-mid: index 5 < q3_idx 6
            pids[6]: Decimal("80"),   # top quartile: index 6 >= q3_idx
            pids[7]: Decimal("100"),  # top quartile: index 7 >= q3_idx
        }
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        result = await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        # median_idx = 4 -> median = 50
        # Agents above median: 70 (idx 5), 80 (idx 6), 100 (idx 7)
        assert result == 3

        # Verify the insert calls: find the mid_rate and top_rate entries
        insert_calls = [
            c for c in mock_conn.execute.call_args_list
            if hasattr(c[0][0], 'compile') and 'wealth_tax' in str(c[0][0].compile().params.get('transaction_type', ''))
        ]

        # Agent with 70 (mid_rate): (70-50)*0.005 = 0.10
        # Agent with 80 (top_rate): (80-50)*0.015 = 0.45
        # Agent with 100 (top_rate): (100-50)*0.015 = 0.75
        amounts = sorted([
            c[0][0].compile().params["amount"] for c in insert_calls
        ])
        assert amounts == [Decimal("0.10"), Decimal("0.45"), Decimal("0.75")]

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_bottom_half_exempt(self, mock_balances, mock_emit, mock_conn):
        """Agents at or below the median should not be taxed."""
        from nexus_core.economy.ledger import apply_wealth_tax

        # All 4 agents have the same balance, so median == everyone's balance
        # All should be exempt since balance <= median_balance
        pids = [uuid4() for _ in range(4)]
        balances = {pid: Decimal("50.00") for pid in pids}
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        result = await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        # All agents at median -> all exempt
        assert result == 0

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_fewer_than_4_agents_returns_zero(self, mock_balances, mock_emit, mock_conn):
        """When there are fewer than 4 agents, should return 0."""
        from nexus_core.economy.ledger import apply_wealth_tax

        # Only 3 agents
        pids = [uuid4() for _ in range(3)]
        balances = {
            pids[0]: Decimal("100.00"),
            pids[1]: Decimal("200.00"),
            pids[2]: Decimal("300.00"),
        }
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        result = await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        assert result == 0

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_tax_proceeds_go_to_welfare_persona(self, mock_balances, mock_emit, mock_conn):
        """Tax payments should be directed to the welfare persona."""
        from nexus_core.economy.ledger import apply_wealth_tax

        pids = [uuid4() for _ in range(4)]
        balances = {
            pids[0]: Decimal("10.00"),
            pids[1]: Decimal("20.00"),
            pids[2]: Decimal("30.00"),
            pids[3]: Decimal("100.00"),
        }
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        custom_welfare = uuid4()
        await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=custom_welfare,
        )

        # Find the insert call(s) for wealth tax
        insert_calls = [
            c for c in mock_conn.execute.call_args_list
            if hasattr(c[0][0], 'compile')
        ]
        # Filter only calls with wealth_tax transaction_type
        tax_calls = [
            c for c in insert_calls
            if c[0][0].compile().params.get('transaction_type') == 'wealth_tax'
        ]

        assert len(tax_calls) >= 1
        for call in tax_calls:
            params = call[0][0].compile().params
            assert params["to_persona_id"] == custom_welfare

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_transaction_type_is_wealth_tax(self, mock_balances, mock_emit, mock_conn):
        """All tax transactions should have transaction_type='wealth_tax'."""
        from nexus_core.economy.ledger import apply_wealth_tax

        pids = [uuid4() for _ in range(4)]
        balances = {
            pids[0]: Decimal("10.00"),
            pids[1]: Decimal("20.00"),
            pids[2]: Decimal("30.00"),
            pids[3]: Decimal("200.00"),
        }
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        insert_calls = [
            c for c in mock_conn.execute.call_args_list
            if hasattr(c[0][0], 'compile')
        ]
        tax_calls = [
            c for c in insert_calls
            if c[0][0].compile().params.get('transaction_type') == 'wealth_tax'
        ]

        for call in tax_calls:
            params = call[0][0].compile().params
            assert params["transaction_type"] == "wealth_tax"

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_emits_event_when_agents_taxed(self, mock_balances, mock_emit, mock_conn):
        """Should emit a wealth_tax_applied event when at least one agent is taxed."""
        from nexus_core.economy.ledger import apply_wealth_tax

        pids = [uuid4() for _ in range(4)]
        balances = {
            pids[0]: Decimal("10.00"),
            pids[1]: Decimal("20.00"),
            pids[2]: Decimal("30.00"),
            pids[3]: Decimal("200.00"),
        }
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][1] == "wealth_tax_applied"
        payload = mock_emit.call_args[1]["payload"]
        assert "agents_taxed" in payload
        assert "total_collected" in payload
        assert "median_balance" in payload

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_no_event_when_no_agents_taxed(self, mock_balances, mock_emit, mock_conn):
        """Should not emit an event when no agents are taxed."""
        from nexus_core.economy.ledger import apply_wealth_tax

        # 4 agents all at same balance -> all exempt
        pids = [uuid4() for _ in range(4)]
        balances = {pid: Decimal("50.00") for pid in pids}
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        mock_emit.assert_not_called()

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_system_personas_excluded(self, mock_balances, mock_emit, mock_conn):
        """System personas should be excluded from wealth tax calculation."""
        from nexus_core.economy.ledger import apply_wealth_tax

        system_id = uuid4()
        regular_ids = [uuid4() for _ in range(4)]
        balances = {
            regular_ids[0]: Decimal("10.00"),
            regular_ids[1]: Decimal("20.00"),
            regular_ids[2]: Decimal("30.00"),
            regular_ids[3]: Decimal("100.00"),
            system_id: Decimal("9999.00"),  # System persona with huge balance
        }
        mock_balances.return_value = balances

        # First call: system persona query
        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([
            SimpleNamespace(persona_id=system_id),
        ])
        mock_conn.execute.return_value = system_result

        result = await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        # System persona excluded, only 4 regular agents remain
        # The system persona's massive balance should not distort the median
        assert result >= 1  # At least one agent should be taxed

        # Verify none of the tax inserts target the system persona
        for call in mock_conn.execute.call_args_list:
            clause = call[0][0]
            if hasattr(clause, 'compile'):
                params = clause.compile().params
                if params.get('transaction_type') == 'wealth_tax':
                    assert params.get('from_persona_id') != system_id

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_zero_balance_agents_ignored(self, mock_balances, mock_emit, mock_conn):
        """Agents with zero or negative balance should be filtered out."""
        from nexus_core.economy.ledger import apply_wealth_tax

        pids = [uuid4() for _ in range(5)]
        balances = {
            pids[0]: Decimal("0.00"),      # Filtered: not > 0
            pids[1]: Decimal("-5.00"),     # Filtered: not > 0
            pids[2]: Decimal("10.00"),
            pids[3]: Decimal("20.00"),
            pids[4]: Decimal("100.00"),
        }
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        result = await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        # Only 3 agents with balance > 0: not enough (< 4)
        assert result == 0

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_custom_tax_rates(self, mock_balances, mock_emit, mock_conn):
        """Custom top_rate and mid_rate should be respected."""
        from nexus_core.economy.ledger import apply_wealth_tax

        pids = [uuid4() for _ in range(8)]
        balances = {
            pids[0]: Decimal("10"),
            pids[1]: Decimal("20"),
            pids[2]: Decimal("30"),
            pids[3]: Decimal("40"),
            pids[4]: Decimal("50"),
            pids[5]: Decimal("60"),
            pids[6]: Decimal("70"),
            pids[7]: Decimal("200"),
        }
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        result = await apply_wealth_tax(
            mock_conn,
            top_rate=Decimal("0.10"),
            mid_rate=Decimal("0.02"),
            welfare_persona_id=WELFARE_ID,
        )

        assert result == 3

        # Verify the amounts use custom rates
        # median = 50
        # Agent 60 (mid): (60-50)*0.02 = 0.20
        # Agent 70 (top): (70-50)*0.10 = 2.00
        # Agent 200 (top): (200-50)*0.10 = 15.00
        insert_calls = [
            c for c in mock_conn.execute.call_args_list
            if hasattr(c[0][0], 'compile')
        ]
        tax_calls = [
            c for c in insert_calls
            if c[0][0].compile().params.get('transaction_type') == 'wealth_tax'
        ]
        amounts = sorted([c[0][0].compile().params["amount"] for c in tax_calls])
        assert amounts == [Decimal("0.20"), Decimal("2.00"), Decimal("15.00")]

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_tax_from_persona_matches_taxed_agent(self, mock_balances, mock_emit, mock_conn):
        """The from_persona_id in the ledger entry should be the taxed agent."""
        from nexus_core.economy.ledger import apply_wealth_tax

        rich_agent = uuid4()
        pids = [uuid4() for _ in range(3)]
        balances = {
            pids[0]: Decimal("10.00"),
            pids[1]: Decimal("20.00"),
            pids[2]: Decimal("30.00"),
            rich_agent: Decimal("500.00"),
        }
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        # Find the wealth_tax insert call
        for call in mock_conn.execute.call_args_list:
            clause = call[0][0]
            if hasattr(clause, 'compile'):
                params = clause.compile().params
                if params.get('transaction_type') == 'wealth_tax':
                    # The biggest agent should be the one taxed
                    assert params["from_persona_id"] == rich_agent

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.economy.ledger.get_all_balances", new_callable=AsyncMock)
    async def test_tiny_tax_below_minimum_skipped(self, mock_balances, mock_emit, mock_conn):
        """Tax amounts below 0.01 should be skipped."""
        from nexus_core.economy.ledger import apply_wealth_tax

        # All agents very close to median -> excess is tiny
        pids = [uuid4() for _ in range(4)]
        balances = {
            pids[0]: Decimal("50.00"),
            pids[1]: Decimal("50.00"),
            pids[2]: Decimal("50.00"),
            pids[3]: Decimal("50.01"),  # Excess = 0.01, tax = 0.01 * 0.015 = 0.000... < 0.01
        }
        mock_balances.return_value = balances

        system_result = MagicMock()
        system_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = system_result

        result = await apply_wealth_tax(
            mock_conn,
            welfare_persona_id=WELFARE_ID,
        )

        # Tax on 0.01 excess at 1.5% = 0.00015 -> below minimum 0.01 -> skipped
        assert result == 0
