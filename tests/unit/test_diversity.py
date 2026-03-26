"""Unit tests for nexus_core.economy.diversity — calculate_gini and related functions."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus_core.economy.diversity import calculate_gini


# ---------------------------------------------------------------------------
# calculate_gini
# ---------------------------------------------------------------------------

class TestCalculateGini:

    def test_calculate_gini_equal(self):
        """All agents have equal wealth -- Gini should be 0."""
        balances = [Decimal("100"), Decimal("100"), Decimal("100")]
        assert calculate_gini(balances) == 0.0

    def test_calculate_gini_unequal(self):
        """Highly unequal distribution should have a high Gini coefficient."""
        balances = [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("1000")]
        gini = calculate_gini(balances)
        assert gini > 0.5

    def test_calculate_gini_moderate(self):
        """Mixed wealth distribution should produce moderate Gini."""
        balances = [Decimal("10"), Decimal("50"), Decimal("100"), Decimal("200")]
        gini = calculate_gini(balances)
        assert 0.0 < gini < 1.0

    def test_calculate_gini_empty(self):
        """Empty balance list should return 0."""
        assert calculate_gini([]) == 0.0

    def test_calculate_gini_single_value(self):
        """Single agent should return Gini = 0."""
        assert calculate_gini([Decimal("100")]) == 0.0

    def test_calculate_gini_with_zeros(self):
        """All zero balances should return 0."""
        balances = [Decimal("0"), Decimal("0"), Decimal("0")]
        assert calculate_gini(balances) == 0.0

    def test_calculate_gini_negative_balances_excluded(self):
        """Negative balances are excluded from calculation."""
        balances = [Decimal("-50"), Decimal("100"), Decimal("100")]
        gini = calculate_gini(balances)
        assert gini == 0.0  # Only the two 100s remain -- equal

    def test_calculate_gini_returns_float(self):
        """Result should be a float."""
        result = calculate_gini([Decimal("10"), Decimal("20")])
        assert isinstance(result, float)

    def test_calculate_gini_range_zero_to_one(self):
        """Gini coefficient should always be in [0, 1]."""
        import random
        random.seed(42)
        for _ in range(10):
            balances = [Decimal(str(random.randint(0, 1000))) for _ in range(20)]
            gini = calculate_gini(balances)
            assert 0.0 <= gini <= 1.0

    def test_calculate_gini_two_equal_values(self):
        """Two equal values should give 0."""
        assert calculate_gini([Decimal("50"), Decimal("50")]) == 0.0

    def test_calculate_gini_two_unequal_values(self):
        """Two values (0, 100) should give a Gini close to 0.5."""
        # With values [0, 100], the sorted array after removing negatives is [0, 100]
        # But 0 is >= 0, so it's kept. sum = 100. index = [1,2]
        # Gini = (2*(1*0 + 2*100) - (2+1)*100) / (2*100)
        #       = (2*200 - 300) / 200 = (400-300)/200 = 0.5
        gini = calculate_gini([Decimal("0"), Decimal("100")])
        assert gini == pytest.approx(0.5, abs=0.01)

    def test_calculate_gini_large_equal_distribution(self):
        """100 agents all with the same balance should give 0."""
        balances = [Decimal("50")] * 100
        assert calculate_gini(balances) == 0.0

    def test_calculate_gini_all_negative_returns_zero(self):
        """If all balances are negative, all are excluded and result is 0."""
        balances = [Decimal("-10"), Decimal("-20"), Decimal("-30")]
        assert calculate_gini(balances) == 0.0
