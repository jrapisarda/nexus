"""Unit tests for OBI price discovery functions in nexus_core.market.service.

Tests cover:
  - _compute_obi: order book imbalance calculation
  - _compute_vwap: volume-weighted average price
  - _compute_finding_quality_mark: continuous quality mark for finding notes
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

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
# _compute_obi
# ---------------------------------------------------------------------------

class TestComputeOBI:
    """Order Book Imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol)."""

    async def test_only_bids_returns_positive_one(self, mock_conn):
        """When only buy orders exist, OBI should be +1.0."""
        from nexus_core.market.service import _compute_obi

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            bid_vol=Decimal("100.00"),
            ask_vol=Decimal("0.00"),
        )
        mock_conn.execute.return_value = mock_result

        obi = await _compute_obi(mock_conn, uuid4())

        assert obi == Decimal("1")

    async def test_only_asks_returns_negative_one(self, mock_conn):
        """When only sell orders exist, OBI should be -1.0."""
        from nexus_core.market.service import _compute_obi

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            bid_vol=Decimal("0.00"),
            ask_vol=Decimal("50.00"),
        )
        mock_conn.execute.return_value = mock_result

        obi = await _compute_obi(mock_conn, uuid4())

        assert obi == Decimal("-1")

    async def test_equal_bid_ask_volume_returns_zero(self, mock_conn):
        """When bid and ask volumes are equal, OBI should be 0."""
        from nexus_core.market.service import _compute_obi

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            bid_vol=Decimal("75.00"),
            ask_vol=Decimal("75.00"),
        )
        mock_conn.execute.return_value = mock_result

        obi = await _compute_obi(mock_conn, uuid4())

        assert obi == Decimal("0")

    async def test_no_orders_returns_zero(self, mock_conn):
        """When there are no orders, OBI should be 0."""
        from nexus_core.market.service import _compute_obi

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            bid_vol=Decimal("0.00"),
            ask_vol=Decimal("0.00"),
        )
        mock_conn.execute.return_value = mock_result

        obi = await _compute_obi(mock_conn, uuid4())

        assert obi == Decimal("0")

    async def test_obi_bounded_between_negative_one_and_positive_one(self, mock_conn):
        """OBI should always be in [-1, +1] for any combination of volumes."""
        from nexus_core.market.service import _compute_obi

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            bid_vol=Decimal("300.00"),
            ask_vol=Decimal("100.00"),
        )
        mock_conn.execute.return_value = mock_result

        obi = await _compute_obi(mock_conn, uuid4())

        assert Decimal("-1") <= obi <= Decimal("1")

    async def test_obi_returns_decimal_type(self, mock_conn):
        """Return type should be Decimal, not float."""
        from nexus_core.market.service import _compute_obi

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            bid_vol=Decimal("60.00"),
            ask_vol=Decimal("40.00"),
        )
        mock_conn.execute.return_value = mock_result

        obi = await _compute_obi(mock_conn, uuid4())

        assert isinstance(obi, Decimal)

    async def test_obi_with_asymmetric_volumes(self, mock_conn):
        """For bid=80, ask=20 the OBI should be 0.6 = (80-20)/(80+20)."""
        from nexus_core.market.service import _compute_obi

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            bid_vol=Decimal("80.00"),
            ask_vol=Decimal("20.00"),
        )
        mock_conn.execute.return_value = mock_result

        obi = await _compute_obi(mock_conn, uuid4())

        assert obi == Decimal("60") / Decimal("100")

    async def test_obi_when_row_is_none(self, mock_conn):
        """When the query returns no row, OBI should be 0."""
        from nexus_core.market.service import _compute_obi

        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_conn.execute.return_value = mock_result

        obi = await _compute_obi(mock_conn, uuid4())

        assert obi == Decimal("0")


# ---------------------------------------------------------------------------
# _compute_vwap
# ---------------------------------------------------------------------------

class TestComputeVWAP:
    """Volume-weighted average price of the last 20 trades."""

    async def test_vwap_returns_weighted_average(self, mock_conn):
        """VWAP should be sum(price*quantity) / sum(quantity)."""
        from nexus_core.market.service import _compute_vwap

        # Simulating aggregated result of trades: pq_sum=500, q_sum=10 -> VWAP=50.00
        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            pq_sum=Decimal("500.00"),
            q_sum=Decimal("10.00"),
        )
        mock_conn.execute.return_value = mock_result

        vwap = await _compute_vwap(mock_conn, uuid4())

        assert vwap == Decimal("50.00")

    async def test_vwap_no_trades_returns_none(self, mock_conn):
        """When there are no trades, VWAP should be None."""
        from nexus_core.market.service import _compute_vwap

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            pq_sum=None,
            q_sum=None,
        )
        mock_conn.execute.return_value = mock_result

        vwap = await _compute_vwap(mock_conn, uuid4())

        assert vwap is None

    async def test_vwap_zero_quantity_returns_none(self, mock_conn):
        """When total quantity is zero, VWAP should be None."""
        from nexus_core.market.service import _compute_vwap

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            pq_sum=Decimal("0"),
            q_sum=0,
        )
        mock_conn.execute.return_value = mock_result

        vwap = await _compute_vwap(mock_conn, uuid4())

        assert vwap is None

    async def test_vwap_returns_decimal_type(self, mock_conn):
        """Return type should be Decimal."""
        from nexus_core.market.service import _compute_vwap

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            pq_sum=Decimal("1000.00"),
            q_sum=Decimal("5.00"),
        )
        mock_conn.execute.return_value = mock_result

        vwap = await _compute_vwap(mock_conn, uuid4())

        assert isinstance(vwap, Decimal)
        assert vwap == Decimal("200.00")

    async def test_vwap_when_row_is_none(self, mock_conn):
        """When the query returns no row at all, VWAP should be None."""
        from nexus_core.market.service import _compute_vwap

        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_conn.execute.return_value = mock_result

        vwap = await _compute_vwap(mock_conn, uuid4())

        assert vwap is None

    async def test_vwap_quantized_to_two_decimal_places(self, mock_conn):
        """VWAP should be quantized to 0.01 precision."""
        from nexus_core.market.service import _compute_vwap

        # 333.33 / 7.00 = 47.618... -> quantized to 47.62
        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            pq_sum=Decimal("333.33"),
            q_sum=Decimal("7.00"),
        )
        mock_conn.execute.return_value = mock_result

        vwap = await _compute_vwap(mock_conn, uuid4())

        assert vwap == Decimal("47.62")


# ---------------------------------------------------------------------------
# _compute_finding_quality_mark
# ---------------------------------------------------------------------------

class TestComputeFindingQualityMark:
    """Continuous quality-based mark for a finding note."""

    async def test_validated_finding_high_confidence_high_mark(self, mock_conn):
        """A validated finding with high confidence and validations should score >70."""
        from nexus_core.market.service import _compute_finding_quality_mark

        finding_id = uuid4()
        node_id = str(uuid4())

        call_count = 0

        def make_side_effect():
            nonlocal call_count

            async def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                mock_result = MagicMock()
                if call_count == 1:
                    # Finding query: validated with KG nodes
                    mock_result.first.return_value = SimpleNamespace(
                        status="validated",
                        kg_nodes_created=[node_id],
                    )
                elif call_count == 2:
                    # KG node quality metrics: high confidence, validations, no challenges
                    mock_result.first.return_value = SimpleNamespace(
                        avg_confidence=Decimal("0.92"),
                        avg_validations=Decimal("5"),
                        avg_challenges=Decimal("0"),
                        avg_failures=Decimal("0"),
                    )
                elif call_count == 3:
                    # Citation count: several citations
                    mock_result.scalar_one.return_value = 4
                else:
                    mock_result.first.return_value = None
                return mock_result
            return side_effect

        mock_conn.execute = AsyncMock(side_effect=make_side_effect())

        mark = await _compute_finding_quality_mark(mock_conn, finding_id)

        # base=60 + validations(5*3=15) + citations(4*2=8) + confidence((0.92-0.5)*20=8.4)
        # = 60 + 15 + 8 + 8.4 = 91.4 -> clamped to 91.40
        assert mark > Decimal("70")
        assert isinstance(mark, Decimal)

    async def test_proposed_finding_no_validations_base_50(self, mock_conn):
        """A proposed finding with no validations should produce base mark around 50."""
        from nexus_core.market.service import _compute_finding_quality_mark

        finding_id = uuid4()
        node_id = str(uuid4())

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    status="proposed",
                    kg_nodes_created=[node_id],
                )
            elif call_count == 2:
                # Average confidence at neutral 0.5, no validations
                mock_result.first.return_value = SimpleNamespace(
                    avg_confidence=Decimal("0.5"),
                    avg_validations=Decimal("0"),
                    avg_challenges=Decimal("0"),
                    avg_failures=Decimal("0"),
                )
            elif call_count == 3:
                mock_result.scalar_one.return_value = 0
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        mark = await _compute_finding_quality_mark(mock_conn, finding_id)

        # base=50, no bonuses, no penalties -> 50.00
        assert mark == Decimal("50.00")

    async def test_failed_finding_mark_near_10(self, mock_conn):
        """A failed finding should have a mark near 10."""
        from nexus_core.market.service import _compute_finding_quality_mark

        finding_id = uuid4()
        node_id = str(uuid4())

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    status="failed",
                    kg_nodes_created=[node_id],
                )
            elif call_count == 2:
                # Low confidence, some challenges and failures
                mock_result.first.return_value = SimpleNamespace(
                    avg_confidence=Decimal("0.2"),
                    avg_validations=Decimal("0"),
                    avg_challenges=Decimal("2"),
                    avg_failures=Decimal("1"),
                )
            elif call_count == 3:
                mock_result.scalar_one.return_value = 0
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        mark = await _compute_finding_quality_mark(mock_conn, finding_id)

        # base=10 + confidence((0.2-0.5)*20 = -6) + challenges(-2*2.5=-5) + failures(-1*5=-5)
        # = 10 - 6 - 5 - 5 = -6 -> clamped to floor 5.00
        assert mark <= Decimal("10.00")

    async def test_finding_not_found_returns_50(self, mock_conn):
        """When the finding does not exist, return the default mark of 50."""
        from nexus_core.market.service import _compute_finding_quality_mark

        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_conn.execute.return_value = mock_result

        mark = await _compute_finding_quality_mark(mock_conn, uuid4())

        assert mark == Decimal("50.00")

    async def test_finding_with_no_kg_nodes_returns_base_status_mark(self, mock_conn):
        """A finding with no KG nodes should return the clamped base status mark."""
        from nexus_core.market.service import _compute_finding_quality_mark

        finding_id = uuid4()

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            status="validated",
            kg_nodes_created=[],
        )
        mock_conn.execute.return_value = mock_result

        mark = await _compute_finding_quality_mark(mock_conn, finding_id)

        # base=60 for validated, but no KG nodes -> clamped between 5 and 95 -> 60
        assert mark == Decimal("60.00")

    async def test_finding_with_none_kg_nodes_returns_base_status_mark(self, mock_conn):
        """When kg_nodes_created is None, should return the base status mark."""
        from nexus_core.market.service import _compute_finding_quality_mark

        finding_id = uuid4()

        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            status="proposed",
            kg_nodes_created=None,
        )
        mock_conn.execute.return_value = mock_result

        mark = await _compute_finding_quality_mark(mock_conn, finding_id)

        # base=50, no KG nodes -> 50.00
        assert mark == Decimal("50.00")

    async def test_mark_clamped_to_ceiling_95(self, mock_conn):
        """Even with extreme quality metrics, mark should not exceed 95."""
        from nexus_core.market.service import _compute_finding_quality_mark

        finding_id = uuid4()
        node_id = str(uuid4())

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    status="validated",
                    kg_nodes_created=[node_id],
                )
            elif call_count == 2:
                # Maximum quality metrics
                mock_result.first.return_value = SimpleNamespace(
                    avg_confidence=Decimal("1.0"),
                    avg_validations=Decimal("50"),
                    avg_challenges=Decimal("0"),
                    avg_failures=Decimal("0"),
                )
            elif call_count == 3:
                mock_result.scalar_one.return_value = 100
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        mark = await _compute_finding_quality_mark(mock_conn, finding_id)

        assert mark == Decimal("95.00")

    async def test_mark_floored_at_5(self, mock_conn):
        """Even with terrible metrics, mark should not go below 5."""
        from nexus_core.market.service import _compute_finding_quality_mark

        finding_id = uuid4()
        node_id = str(uuid4())

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    status="failed",
                    kg_nodes_created=[node_id],
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    avg_confidence=Decimal("0.0"),
                    avg_validations=Decimal("0"),
                    avg_challenges=Decimal("20"),
                    avg_failures=Decimal("15"),
                )
            elif call_count == 3:
                mock_result.scalar_one.return_value = 0
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        mark = await _compute_finding_quality_mark(mock_conn, finding_id)

        assert mark == Decimal("5.00")

    async def test_escalated_finding_base_is_10(self, mock_conn):
        """An escalated finding should use base=10."""
        from nexus_core.market.service import _compute_finding_quality_mark

        finding_id = uuid4()
        node_id = str(uuid4())

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    status="escalated",
                    kg_nodes_created=[node_id],
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    avg_confidence=Decimal("0.5"),
                    avg_validations=Decimal("0"),
                    avg_challenges=Decimal("0"),
                    avg_failures=Decimal("0"),
                )
            elif call_count == 3:
                mock_result.scalar_one.return_value = 0
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        mark = await _compute_finding_quality_mark(mock_conn, finding_id)

        # base=10, no bonuses, no penalties -> 10.00
        assert mark == Decimal("10.00")

    async def test_unknown_status_defaults_to_base_50(self, mock_conn):
        """An unrecognized status should fall back to base=50."""
        from nexus_core.market.service import _compute_finding_quality_mark

        finding_id = uuid4()
        node_id = str(uuid4())

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    status="some_unknown_status",
                    kg_nodes_created=[node_id],
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    avg_confidence=Decimal("0.5"),
                    avg_validations=Decimal("0"),
                    avg_challenges=Decimal("0"),
                    avg_failures=Decimal("0"),
                )
            elif call_count == 3:
                mock_result.scalar_one.return_value = 0
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        mark = await _compute_finding_quality_mark(mock_conn, finding_id)

        assert mark == Decimal("50.00")

    async def test_citations_boost_mark(self, mock_conn):
        """More citations should increase the mark."""
        from nexus_core.market.service import _compute_finding_quality_mark

        finding_id = uuid4()
        node_id = str(uuid4())

        # Test with 0 citations
        call_count_a = 0

        async def side_effect_a(*args, **kwargs):
            nonlocal call_count_a
            call_count_a += 1
            mock_result = MagicMock()
            if call_count_a == 1:
                mock_result.first.return_value = SimpleNamespace(
                    status="validated",
                    kg_nodes_created=[node_id],
                )
            elif call_count_a == 2:
                mock_result.first.return_value = SimpleNamespace(
                    avg_confidence=Decimal("0.5"),
                    avg_validations=Decimal("0"),
                    avg_challenges=Decimal("0"),
                    avg_failures=Decimal("0"),
                )
            elif call_count_a == 3:
                mock_result.scalar_one.return_value = 0
            return mock_result

        mock_conn_a = AsyncMock()
        mock_conn_a.execute = AsyncMock(side_effect=side_effect_a)
        mark_no_citations = await _compute_finding_quality_mark(mock_conn_a, finding_id)

        # Test with 10 citations
        call_count_b = 0

        async def side_effect_b(*args, **kwargs):
            nonlocal call_count_b
            call_count_b += 1
            mock_result = MagicMock()
            if call_count_b == 1:
                mock_result.first.return_value = SimpleNamespace(
                    status="validated",
                    kg_nodes_created=[node_id],
                )
            elif call_count_b == 2:
                mock_result.first.return_value = SimpleNamespace(
                    avg_confidence=Decimal("0.5"),
                    avg_validations=Decimal("0"),
                    avg_challenges=Decimal("0"),
                    avg_failures=Decimal("0"),
                )
            elif call_count_b == 3:
                mock_result.scalar_one.return_value = 10
            return mock_result

        mock_conn_b = AsyncMock()
        mock_conn_b.execute = AsyncMock(side_effect=side_effect_b)
        mark_with_citations = await _compute_finding_quality_mark(mock_conn_b, finding_id)

        assert mark_with_citations > mark_no_citations
