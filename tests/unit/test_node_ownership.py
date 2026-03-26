"""Unit tests for KG Node Ownership in nexus_core.market.node_ownership.

Tests cover:
  - compute_node_value: fair value based on edges, confidence, centrality
  - purchase_node: purchase flow with all guard rails
  - distribute_node_yields: proportional yield distribution
  - apply_node_depreciation: confidence decay on neglected nodes
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


# ---------------------------------------------------------------------------
# compute_node_value
# ---------------------------------------------------------------------------

class TestComputeNodeValue:
    """Fair value: base + (edge_count * mean_weight * confidence) * multiplier + centrality."""

    async def test_node_with_edges_high_confidence(self, mock_conn):
        """Node with 10 edges at weight 0.9, confidence 0.85 should produce value ~89."""
        from nexus_core.market.node_ownership import compute_node_value

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # Node info: confidence=0.85, betweenness=0, validation_count=0
                mock_result.first.return_value = SimpleNamespace(
                    confidence_score=Decimal("0.85"),
                    betweenness_score=Decimal("0"),
                    validation_count=0,
                )
            elif call_count == 2:
                # Edge info: 10 edges, mean weight 0.9
                mock_result.first.return_value = SimpleNamespace(
                    edge_count=10,
                    mean_weight=Decimal("0.9"),
                )
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        value = await compute_node_value(mock_conn, uuid4())

        # base=5 + (10 * 0.9 * 0.85) * 10 + (0 * 50) + (0 * 1.5)
        # = 5 + 76.5 + 0 + 0 = 81.50
        # _money rounds to 2 decimal places
        expected = Decimal("81.50")
        assert value == expected

    async def test_node_with_zero_edges_returns_base_price(self, mock_conn):
        """Node with 0 edges should return the base_price."""
        from nexus_core.market.node_ownership import compute_node_value

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    confidence_score=Decimal("0.5"),
                    betweenness_score=Decimal("0"),
                    validation_count=0,
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    edge_count=0,
                    mean_weight=Decimal("0.5"),
                )
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        value = await compute_node_value(mock_conn, uuid4())

        # base=5, edge_quality=0, centrality=0, validation_bonus=0 -> 5.00
        assert value == Decimal("5.00")

    async def test_node_not_found_returns_min_price(self, mock_conn):
        """When node does not exist, should return min_price."""
        from nexus_core.market.node_ownership import compute_node_value

        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_conn.execute.return_value = mock_result

        value = await compute_node_value(mock_conn, uuid4())

        assert value == Decimal("5.00")

    async def test_centrality_bonus_increases_value(self, mock_conn):
        """A node with betweenness_score should get a centrality premium."""
        from nexus_core.market.node_ownership import compute_node_value

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    confidence_score=Decimal("0.5"),
                    betweenness_score=Decimal("0.5"),
                    validation_count=0,
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    edge_count=0,
                    mean_weight=Decimal("0.5"),
                )
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        value = await compute_node_value(mock_conn, uuid4())

        # base=5 + 0 + (0.5 * 50) + 0 = 30.00
        assert value == Decimal("30.00")

    async def test_validation_count_adds_bonus(self, mock_conn):
        """validation_count should add 1.5 per validation."""
        from nexus_core.market.node_ownership import compute_node_value

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    confidence_score=Decimal("0.5"),
                    betweenness_score=Decimal("0"),
                    validation_count=4,
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    edge_count=0,
                    mean_weight=Decimal("0.5"),
                )
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        value = await compute_node_value(mock_conn, uuid4())

        # base=5 + 0 + 0 + (4 * 1.5) = 11.00
        assert value == Decimal("11.00")

    async def test_value_capped_at_max_price(self, mock_conn):
        """Value should not exceed max_price (500)."""
        from nexus_core.market.node_ownership import compute_node_value

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    confidence_score=Decimal("1.0"),
                    betweenness_score=Decimal("10.0"),
                    validation_count=100,
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    edge_count=100,
                    mean_weight=Decimal("1.0"),
                )
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        value = await compute_node_value(mock_conn, uuid4())

        assert value == Decimal("500.00")

    async def test_value_returns_decimal(self, mock_conn):
        """Return type should always be Decimal."""
        from nexus_core.market.node_ownership import compute_node_value

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    confidence_score=Decimal("0.7"),
                    betweenness_score=Decimal("0"),
                    validation_count=0,
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    edge_count=5,
                    mean_weight=Decimal("0.8"),
                )
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        value = await compute_node_value(mock_conn, uuid4())

        assert isinstance(value, Decimal)


# ---------------------------------------------------------------------------
# purchase_node
# ---------------------------------------------------------------------------

class TestPurchaseNode:
    """Agent purchases an unowned KG node with all guard rails."""

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.get_balance", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.compute_node_value", new_callable=AsyncMock)
    async def test_successful_purchase(self, mock_value, mock_balance, mock_emit, mock_conn):
        """Happy path: purchase debits credits and sets ownership."""
        from nexus_core.market.node_ownership import purchase_node

        persona_id = uuid4()
        node_id = uuid4()
        mock_value.return_value = Decimal("50.00")
        mock_balance.return_value = Decimal("200.00")

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # Node check: unowned, validated
                mock_result.first.return_value = SimpleNamespace(
                    node_id=node_id,
                    label="Test Node Label for Research",
                    owner_persona_id=None,
                    status="validated",
                )
            elif call_count == 2:
                # Persona check: not system, good reputation
                mock_result.first.return_value = SimpleNamespace(
                    role_class="researcher",
                    reputation_score=Decimal("0.80"),
                )
            elif call_count == 3:
                # Owned count
                mock_result.scalar_one.return_value = 0
            else:
                # Insert and update calls
                mock_result.rowcount = 1
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        result = await purchase_node(mock_conn, persona_id, node_id)

        assert result["node_id"] == str(node_id)
        assert result["label"] == "Test Node Label for Research"
        assert Decimal(result["purchase_price"]) == Decimal("50.00")
        assert result["owned_count"] == 1

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.get_balance", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.compute_node_value", new_callable=AsyncMock)
    async def test_already_owned_raises_value_error(self, mock_value, mock_balance, mock_emit, mock_conn):
        """Purchasing an already-owned node should raise ValueError."""
        from nexus_core.market.node_ownership import purchase_node

        node_id = uuid4()
        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            node_id=node_id,
            label="Owned Node",
            owner_persona_id=uuid4(),  # already owned
            status="validated",
        )
        mock_conn.execute.return_value = mock_result

        with pytest.raises(ValueError, match="already owned"):
            await purchase_node(mock_conn, uuid4(), node_id)

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.get_balance", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.compute_node_value", new_callable=AsyncMock)
    async def test_insufficient_balance_raises_value_error(self, mock_value, mock_balance, mock_emit, mock_conn):
        """When balance is below the purchase price, should raise ValueError."""
        from nexus_core.market.node_ownership import purchase_node

        persona_id = uuid4()
        node_id = uuid4()
        mock_value.return_value = Decimal("100.00")
        mock_balance.return_value = Decimal("10.00")  # Not enough

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    node_id=node_id,
                    label="Expensive Node",
                    owner_persona_id=None,
                    status="validated",
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    role_class="researcher",
                    reputation_score=Decimal("0.80"),
                )
            elif call_count == 3:
                mock_result.scalar_one.return_value = 0
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        with pytest.raises(ValueError, match="Insufficient balance"):
            await purchase_node(mock_conn, persona_id, node_id)

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.get_balance", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.compute_node_value", new_callable=AsyncMock)
    async def test_portfolio_cap_reached_raises_value_error(self, mock_value, mock_balance, mock_emit, mock_conn):
        """When agent already owns max_owned nodes, should raise ValueError."""
        from nexus_core.market.node_ownership import purchase_node

        persona_id = uuid4()
        node_id = uuid4()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    node_id=node_id,
                    label="Another Node",
                    owner_persona_id=None,
                    status="validated",
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    role_class="researcher",
                    reputation_score=Decimal("0.80"),
                )
            elif call_count == 3:
                mock_result.scalar_one.return_value = 5  # Already at cap (default max_owned=5)
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        with pytest.raises(ValueError, match="Portfolio cap reached"):
            await purchase_node(mock_conn, persona_id, node_id)

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.get_balance", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.compute_node_value", new_callable=AsyncMock)
    async def test_system_persona_raises_value_error(self, mock_value, mock_balance, mock_emit, mock_conn):
        """System personas should not be allowed to own KG nodes."""
        from nexus_core.market.node_ownership import purchase_node

        persona_id = uuid4()
        node_id = uuid4()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    node_id=node_id,
                    label="Node for System",
                    owner_persona_id=None,
                    status="validated",
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    role_class="system",
                    reputation_score=Decimal("1.0"),
                )
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        with pytest.raises(ValueError, match="System personas cannot own"):
            await purchase_node(mock_conn, persona_id, node_id)

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.get_balance", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.compute_node_value", new_callable=AsyncMock)
    async def test_below_capability_gate_raises_value_error(self, mock_value, mock_balance, mock_emit, mock_conn):
        """When reputation is below the capability gate, should raise ValueError."""
        from nexus_core.market.node_ownership import purchase_node

        persona_id = uuid4()
        node_id = uuid4()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.first.return_value = SimpleNamespace(
                    node_id=node_id,
                    label="Gated Node",
                    owner_persona_id=None,
                    status="validated",
                )
            elif call_count == 2:
                mock_result.first.return_value = SimpleNamespace(
                    role_class="researcher",
                    reputation_score=Decimal("0.30"),  # Below default gate of 0.50
                )
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        with pytest.raises(ValueError, match="below capability gate"):
            await purchase_node(mock_conn, persona_id, node_id)

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.get_balance", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.compute_node_value", new_callable=AsyncMock)
    async def test_superlinear_pricing_third_node_costs_more(self, mock_value, mock_balance, mock_emit, mock_conn):
        """Superlinear pricing: 3rd node should cost more than 1st due to owned_count markup."""
        from nexus_core.market.node_ownership import purchase_node

        persona_id = uuid4()
        node_id = uuid4()
        base_value = Decimal("50.00")
        mock_value.return_value = base_value
        mock_balance.return_value = Decimal("500.00")

        # Purchase with 0 nodes owned (first purchase)
        call_count_a = 0

        async def side_effect_a(*args, **kwargs):
            nonlocal call_count_a
            call_count_a += 1
            mock_result = MagicMock()
            if call_count_a == 1:
                mock_result.first.return_value = SimpleNamespace(
                    node_id=node_id,
                    label="Node A",
                    owner_persona_id=None,
                    status="validated",
                )
            elif call_count_a == 2:
                mock_result.first.return_value = SimpleNamespace(
                    role_class="researcher",
                    reputation_score=Decimal("0.80"),
                )
            elif call_count_a == 3:
                mock_result.scalar_one.return_value = 0  # First node
            else:
                mock_result.rowcount = 1
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect_a)
        result_first = await purchase_node(mock_conn, persona_id, node_id)
        price_first = Decimal(result_first["purchase_price"])

        # Purchase with 2 nodes already owned (third purchase)
        node_id_3 = uuid4()
        call_count_b = 0

        async def side_effect_b(*args, **kwargs):
            nonlocal call_count_b
            call_count_b += 1
            mock_result = MagicMock()
            if call_count_b == 1:
                mock_result.first.return_value = SimpleNamespace(
                    node_id=node_id_3,
                    label="Node C",
                    owner_persona_id=None,
                    status="validated",
                )
            elif call_count_b == 2:
                mock_result.first.return_value = SimpleNamespace(
                    role_class="researcher",
                    reputation_score=Decimal("0.80"),
                )
            elif call_count_b == 3:
                mock_result.scalar_one.return_value = 2  # Already owns 2
            else:
                mock_result.rowcount = 1
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect_b)
        result_third = await purchase_node(mock_conn, persona_id, node_id_3)
        price_third = Decimal(result_third["purchase_price"])

        # First purchase: markup = 1 + (0 * 0.20) = 1.0 -> price = 50.00
        # Third purchase: markup = 1 + (2 * 0.20) = 1.4 -> price = 70.00
        assert price_third > price_first
        assert price_first == Decimal("50.00")
        assert price_third == Decimal("70.00")

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.get_balance", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.compute_node_value", new_callable=AsyncMock)
    async def test_node_does_not_exist_raises_value_error(self, mock_value, mock_balance, mock_emit, mock_conn):
        """Attempting to purchase a non-existent node should raise ValueError."""
        from nexus_core.market.node_ownership import purchase_node

        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_conn.execute.return_value = mock_result

        with pytest.raises(ValueError, match="does not exist"):
            await purchase_node(mock_conn, uuid4(), uuid4())

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.get_balance", new_callable=AsyncMock)
    @patch("nexus_core.market.node_ownership.compute_node_value", new_callable=AsyncMock)
    async def test_invalid_node_status_raises_value_error(self, mock_value, mock_balance, mock_emit, mock_conn):
        """Only validated/proposed nodes can be purchased; other statuses should fail."""
        from nexus_core.market.node_ownership import purchase_node

        node_id = uuid4()
        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            node_id=node_id,
            label="Bad Status Node",
            owner_persona_id=None,
            status="rejected",
        )
        mock_conn.execute.return_value = mock_result

        with pytest.raises(ValueError, match="status"):
            await purchase_node(mock_conn, uuid4(), node_id)


# ---------------------------------------------------------------------------
# distribute_node_yields
# ---------------------------------------------------------------------------

class TestDistributeNodeYields:
    """Distribute yield to node owners based on traversal frequency."""

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    async def test_no_owned_nodes_returns_zero(self, mock_emit, mock_conn):
        """When no nodes are owned, should return 0."""
        from nexus_core.market.node_ownership import distribute_node_yields

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        count = await distribute_node_yields(mock_conn, Decimal("100.00"))

        assert count == 0

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    async def test_proportional_distribution_two_nodes(self, mock_emit, mock_conn):
        """Two nodes with traversals 10 and 5 should get ~67% and ~33%."""
        from nexus_core.market.node_ownership import distribute_node_yields

        owner_a = uuid4()
        owner_b = uuid4()
        node_a = uuid4()
        node_b = uuid4()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # Query for owned nodes with traversals
                mock_result.fetchall.return_value = [
                    SimpleNamespace(
                        node_id=node_a,
                        owner_persona_id=owner_a,
                        last_traversal_count=10,
                    ),
                    SimpleNamespace(
                        node_id=node_b,
                        owner_persona_id=owner_b,
                        last_traversal_count=5,
                    ),
                ]
            else:
                # Insert calls for yield distribution
                mock_result.rowcount = 1
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        yield_pool = Decimal("100.00")
        count = await distribute_node_yields(mock_conn, yield_pool)

        assert count == 2
        # Verify the insert calls contain the right amounts
        # Call 2 (index 1) should be node_a yield: 100 * (10/15) = 66.67
        # Call 3 (index 2) should be node_b yield: 100 * (5/15) = 33.33
        insert_calls = mock_conn.execute.call_args_list
        first_insert = insert_calls[1][0][0].compile().params
        second_insert = insert_calls[2][0][0].compile().params

        assert first_insert["amount"] == Decimal("66.67")
        assert first_insert["transaction_type"] == "node_yield"

        assert second_insert["amount"] == Decimal("33.33")
        assert second_insert["transaction_type"] == "node_yield"

    async def test_zero_pool_returns_zero(self, mock_conn):
        """An empty (zero) yield pool should return 0 without querying."""
        from nexus_core.market.node_ownership import distribute_node_yields

        count = await distribute_node_yields(mock_conn, Decimal("0"))

        assert count == 0
        mock_conn.execute.assert_not_called()

    async def test_negative_pool_returns_zero(self, mock_conn):
        """A negative yield pool should return 0 without querying."""
        from nexus_core.market.node_ownership import distribute_node_yields

        count = await distribute_node_yields(mock_conn, Decimal("-10.00"))

        assert count == 0
        mock_conn.execute.assert_not_called()

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    async def test_emits_event_when_yields_distributed(self, mock_emit, mock_conn):
        """Should emit a node_yields_distributed event when recipients > 0."""
        from nexus_core.market.node_ownership import distribute_node_yields

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.fetchall.return_value = [
                    SimpleNamespace(
                        node_id=uuid4(),
                        owner_persona_id=uuid4(),
                        last_traversal_count=10,
                    ),
                ]
            else:
                mock_result.rowcount = 1
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        await distribute_node_yields(mock_conn, Decimal("50.00"))

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][1] == "node_yields_distributed"

    @patch("nexus_core.market.node_ownership.emit_event", new_callable=AsyncMock)
    async def test_tiny_yield_below_minimum_skipped(self, mock_emit, mock_conn):
        """When a node's share is below 0.01, it should be skipped."""
        from nexus_core.market.node_ownership import distribute_node_yields

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.fetchall.return_value = [
                    SimpleNamespace(
                        node_id=uuid4(),
                        owner_persona_id=uuid4(),
                        last_traversal_count=1,
                    ),
                    SimpleNamespace(
                        node_id=uuid4(),
                        owner_persona_id=uuid4(),
                        last_traversal_count=9999,
                    ),
                ]
            else:
                mock_result.rowcount = 1
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        # Pool of 0.02: node with 1/10000 traversals gets 0.000002 -> below 0.01
        # Only the dominant node should get its share
        count = await distribute_node_yields(mock_conn, Decimal("0.02"))

        # The node with 1 traversal gets 0.02 * (1/10000) = ~0.000002 -> skipped
        # The node with 9999 traversals gets 0.02 * (9999/10000) = ~0.02 -> included
        assert count == 1


# ---------------------------------------------------------------------------
# apply_node_depreciation
# ---------------------------------------------------------------------------

class TestApplyNodeDepreciation:
    """Apply knowledge decay to owned nodes without recent traversals."""

    async def test_untraversed_node_confidence_decreases(self, mock_conn):
        """An untraversed owned node should have its confidence reduced."""
        from nexus_core.market.node_ownership import apply_node_depreciation

        node_id = uuid4()
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # Query for neglected nodes (owner set, traversal == 0)
                mock_result.fetchall.return_value = [
                    SimpleNamespace(
                        node_id=node_id,
                        confidence_score=Decimal("0.80"),
                        owner_persona_id=uuid4(),
                    ),
                ]
            else:
                mock_result.rowcount = 1
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        count = await apply_node_depreciation(mock_conn)

        assert count == 1
        # Verify the update was called with reduced confidence
        update_call = mock_conn.execute.call_args_list[1]
        update_clause = update_call[0][0]
        compiled = update_clause.compile()
        # new_confidence = max(0.001, 0.80 - 0.01) = 0.79
        assert compiled.params["confidence_score"] == Decimal("0.79")

    async def test_traversed_node_not_affected(self, mock_conn):
        """Nodes with traversal_count > 0 should not appear in the query results."""
        from nexus_core.market.node_ownership import apply_node_depreciation

        # The function only queries nodes where last_traversal_count == 0,
        # so traversed nodes are filtered at the SQL level.
        # We simulate this by returning no nodes.
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        count = await apply_node_depreciation(mock_conn)

        assert count == 0

    async def test_confidence_floors_at_minimum(self, mock_conn):
        """Confidence should not go below 0.001."""
        from nexus_core.market.node_ownership import apply_node_depreciation

        node_id = uuid4()
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.fetchall.return_value = [
                    SimpleNamespace(
                        node_id=node_id,
                        confidence_score=Decimal("0.005"),
                        owner_persona_id=uuid4(),
                    ),
                ]
            else:
                mock_result.rowcount = 1
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        count = await apply_node_depreciation(mock_conn)

        assert count == 1
        update_call = mock_conn.execute.call_args_list[1]
        update_clause = update_call[0][0]
        compiled = update_clause.compile()
        # max(0.001, 0.005 - 0.01) = max(0.001, -0.005) = 0.001
        assert compiled.params["confidence_score"] == Decimal("0.001")

    async def test_custom_depreciation_rate(self, mock_conn):
        """Should respect a custom depreciation_rate parameter."""
        from nexus_core.market.node_ownership import apply_node_depreciation

        node_id = uuid4()
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.fetchall.return_value = [
                    SimpleNamespace(
                        node_id=node_id,
                        confidence_score=Decimal("0.50"),
                        owner_persona_id=uuid4(),
                    ),
                ]
            else:
                mock_result.rowcount = 1
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        count = await apply_node_depreciation(mock_conn, depreciation_rate=Decimal("0.10"))

        assert count == 1
        update_call = mock_conn.execute.call_args_list[1]
        update_clause = update_call[0][0]
        compiled = update_clause.compile()
        # max(0.001, 0.50 - 0.10) = 0.40
        assert compiled.params["confidence_score"] == Decimal("0.40")

    async def test_multiple_neglected_nodes(self, mock_conn):
        """Multiple neglected nodes should each be depreciated."""
        from nexus_core.market.node_ownership import apply_node_depreciation

        nodes = [
            SimpleNamespace(
                node_id=uuid4(),
                confidence_score=Decimal("0.90"),
                owner_persona_id=uuid4(),
            ),
            SimpleNamespace(
                node_id=uuid4(),
                confidence_score=Decimal("0.30"),
                owner_persona_id=uuid4(),
            ),
        ]

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.fetchall.return_value = nodes
            else:
                mock_result.rowcount = 1
            return mock_result

        mock_conn.execute = AsyncMock(side_effect=side_effect)

        count = await apply_node_depreciation(mock_conn)

        assert count == 2
