"""Unit tests for progressive rent tier computation in nexus_core.economy.ledger."""

from decimal import Decimal

import pytest

from nexus_core.economy.ledger import _get_rent_tier_rate


class TestGetRentTierRate:
    """Tests for _get_rent_tier_rate() — a pure function that maps balance to rent rate."""

    # Default keyword arguments used by the production code
    DEFAULTS = dict(
        exempt_below=Decimal("20.00"),
        rate_low=Decimal("0.03"),
        rate_mid=Decimal("0.05"),
        rate_high=Decimal("0.08"),
        high_above=Decimal("300.00"),
    )

    # ------------------------------------------------------------------
    # Parameterized tier-rate tests
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "balance, expected_rate, description",
        [
            # Exempt tier: below exempt_below
            (Decimal("0"), Decimal("0"), "zero balance is exempt"),
            (Decimal("15"), Decimal("0"), "below exempt_below threshold (20)"),
            # Low tier: exempt_below <= balance < 100
            (Decimal("50"), Decimal("0.03"), "mid-range low tier"),
            (Decimal("20"), Decimal("0.03"), "exact boundary at exempt_below -> low tier"),
            (Decimal("99.99"), Decimal("0.03"), "just below mid tier boundary"),
            # Mid tier: 100 <= balance <= high_above
            (Decimal("150"), Decimal("0.05"), "mid tier"),
            (Decimal("100"), Decimal("0.05"), "exact boundary at 100 -> mid tier"),
            (Decimal("300"), Decimal("0.05"), "exact boundary at high_above -> mid tier"),
            # High tier: balance > high_above
            (Decimal("500"), Decimal("0.08"), "high tier"),
            (Decimal("300.01"), Decimal("0.08"), "just above high_above -> high tier"),
        ],
        ids=[
            "balance_0_exempt",
            "balance_15_exempt",
            "balance_50_low",
            "balance_20_boundary_low",
            "balance_99.99_low",
            "balance_150_mid",
            "balance_100_boundary_mid",
            "balance_300_boundary_mid",
            "balance_500_high",
            "balance_300.01_high",
        ],
    )
    def test_tier_rate_computation(self, balance, expected_rate, description):
        """Verify correct tier rate for each balance bracket."""
        result = _get_rent_tier_rate(balance, **self.DEFAULTS)
        assert result == expected_rate, f"Failed: {description}"

    # ------------------------------------------------------------------
    # Boundary and edge cases
    # ------------------------------------------------------------------

    def test_exempt_below_boundary_exclusive(self):
        """Balance just below exempt_below should return 0%."""
        result = _get_rent_tier_rate(Decimal("19.99"), **self.DEFAULTS)
        assert result == Decimal("0")

    def test_negative_balance_is_exempt(self):
        """Negative balances should be treated as below exempt_below."""
        result = _get_rent_tier_rate(Decimal("-10"), **self.DEFAULTS)
        assert result == Decimal("0")

    def test_very_large_balance_returns_high_rate(self):
        """Extremely large balances should return the high tier rate."""
        result = _get_rent_tier_rate(Decimal("100000"), **self.DEFAULTS)
        assert result == Decimal("0.08")

    # ------------------------------------------------------------------
    # Custom keyword parameters
    # ------------------------------------------------------------------

    def test_custom_exempt_below(self):
        """Custom exempt_below changes the exemption boundary."""
        result = _get_rent_tier_rate(
            Decimal("50"),
            exempt_below=Decimal("60"),
            rate_low=Decimal("0.03"),
            rate_mid=Decimal("0.05"),
            rate_high=Decimal("0.08"),
            high_above=Decimal("300"),
        )
        assert result == Decimal("0"), "50 should be exempt when exempt_below=60"

    def test_custom_rate_values(self):
        """Custom rate values should be returned for corresponding tiers."""
        result = _get_rent_tier_rate(
            Decimal("150"),
            exempt_below=Decimal("20"),
            rate_low=Decimal("0.01"),
            rate_mid=Decimal("0.10"),
            rate_high=Decimal("0.20"),
            high_above=Decimal("300"),
        )
        assert result == Decimal("0.10")

    def test_custom_high_above_boundary(self):
        """Custom high_above shifts the high tier threshold."""
        result = _get_rent_tier_rate(
            Decimal("250"),
            exempt_below=Decimal("20"),
            rate_low=Decimal("0.03"),
            rate_mid=Decimal("0.05"),
            rate_high=Decimal("0.08"),
            high_above=Decimal("200"),
        )
        assert result == Decimal("0.08"), "250 > 200 should use high rate"

    # ------------------------------------------------------------------
    # Return type guarantees
    # ------------------------------------------------------------------

    def test_return_type_is_decimal(self):
        """All returns should be Decimal instances."""
        for balance in [Decimal("0"), Decimal("50"), Decimal("150"), Decimal("500")]:
            result = _get_rent_tier_rate(balance, **self.DEFAULTS)
            assert isinstance(result, Decimal)
