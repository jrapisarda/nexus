"""Unit tests for nexus_core.utils.cost — CostGuard and BudgetExhaustedError."""

from decimal import Decimal

import pytest

from nexus_core.utils.cost import (
    BudgetExhaustedError,
    CostGuard,
    calculate_cost_breakdown,
)


class TestCostGuardInitialState:
    """Verify a fresh CostGuard has the expected initial state."""

    def test_initial_cumulative_spend_is_zero(self, cost_guard):
        assert cost_guard.cumulative_spend == Decimal("0.00")

    def test_initial_remaining_equals_ceiling(self, cost_guard):
        assert cost_guard.remaining_budget == Decimal("38.25")

    def test_initial_budget_utilization_is_zero(self, cost_guard):
        assert cost_guard.budget_utilization_pct == pytest.approx(0.0)


class TestEstimateCallCost:
    """Verify cost estimation arithmetic."""

    def test_estimate_call_cost_known_values(self, cost_guard):
        """1M input tokens at $0.60/M + 1M output tokens at $2.50/M = $3.10."""
        result = cost_guard.estimate_call_cost(1_000_000, 1_000_000)
        assert result == Decimal("0.60") + Decimal("2.50")
        assert result == Decimal("3.10")

    def test_estimate_call_cost_zero_tokens(self, cost_guard):
        result = cost_guard.estimate_call_cost(0, 0)
        assert result == Decimal("0")

    def test_estimate_call_cost_default_output_tokens(self, cost_guard):
        """Default output_tokens=4096."""
        result_default = cost_guard.estimate_call_cost(1000)
        result_explicit = cost_guard.estimate_call_cost(1000, 4096)
        assert result_default == result_explicit

    def test_estimate_call_cost_small_values(self, cost_guard):
        """1000 input + 500 output: tiny cost."""
        result = cost_guard.estimate_call_cost(1000, 500)
        expected_input = Decimal("1000") / Decimal("1000000") * Decimal("0.60")
        expected_output = Decimal("500") / Decimal("1000000") * Decimal("2.50")
        assert result == expected_input + expected_output

    def test_estimate_call_cost_returns_decimal(self, cost_guard):
        result = cost_guard.estimate_call_cost(5000, 2000)
        assert isinstance(result, Decimal)


class TestCalculateCostBreakdown:
    def test_breakdown_tracks_thinking_tokens_separately(self):
        breakdown = calculate_cost_breakdown(
            input_tokens=1_000_000,
            thinking_tokens=500_000,
            output_tokens=500_000,
            cost_input_per_million=Decimal("0.60"),
            cost_output_per_million=Decimal("2.50"),
        )
        assert breakdown.input_cost_usd == Decimal("0.600000")
        assert breakdown.thinking_cost_usd == Decimal("1.250000")
        assert breakdown.output_cost_usd == Decimal("1.250000")
        assert breakdown.total_cost_usd == Decimal("3.100000")


class TestRecordSpend:
    """Verify spend recording updates cumulative state."""

    def test_record_spend_increases_cumulative(self, cost_guard):
        cost = cost_guard.record_spend(input_tokens=1000, output_tokens=500)
        assert cost > 0
        assert cost_guard.cumulative_spend == cost

    def test_record_spend_accumulates(self, cost_guard):
        cost1 = cost_guard.record_spend(input_tokens=1000, output_tokens=500)
        cost2 = cost_guard.record_spend(input_tokens=2000, output_tokens=1000)
        assert cost_guard.cumulative_spend == cost1 + cost2

    def test_record_spend_returns_cost(self, cost_guard):
        cost = cost_guard.record_spend(input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == Decimal("3.10")

    def test_record_spend_reduces_remaining(self, cost_guard):
        cost_guard.record_spend(input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost_guard.remaining_budget == Decimal("38.25") - Decimal("3.10")

    def test_record_spend_with_thinking_tokens(self, cost_guard):
        """Thinking tokens are billed as output tokens.

        500 output + 500 thinking = 1000 total output tokens.
        """
        cost_with_thinking = cost_guard.record_spend(
            input_tokens=1000, output_tokens=500, thinking_tokens=500
        )
        # Create a fresh guard to compare
        guard2 = CostGuard(
            budget_ceiling_usd=Decimal("38.25"),
            cost_input_per_million=Decimal("0.60"),
            cost_output_per_million=Decimal("2.50"),
        )
        cost_combined = guard2.record_spend(input_tokens=1000, output_tokens=1000)
        assert cost_with_thinking == cost_combined

    def test_record_spend_thinking_tokens_default_zero(self, cost_guard):
        """Default thinking_tokens=0 means output_tokens alone determines output cost."""
        cost_no_thinking = cost_guard.record_spend(input_tokens=1000, output_tokens=500)
        guard2 = CostGuard(
            budget_ceiling_usd=Decimal("38.25"),
            cost_input_per_million=Decimal("0.60"),
            cost_output_per_million=Decimal("2.50"),
        )
        cost_explicit_zero = guard2.record_spend(
            input_tokens=1000, output_tokens=500, thinking_tokens=0
        )
        assert cost_no_thinking == cost_explicit_zero


class TestRecordExactCost:
    """Verify record_exact_cost adds the exact amount."""

    def test_record_exact_cost(self, cost_guard):
        cost_guard.record_exact_cost(Decimal("5.00"))
        assert cost_guard.cumulative_spend == Decimal("5.00")

    def test_record_exact_cost_accumulates(self, cost_guard):
        cost_guard.record_exact_cost(Decimal("1.50"))
        cost_guard.record_exact_cost(Decimal("2.75"))
        assert cost_guard.cumulative_spend == Decimal("4.25")


class TestCheckBudget:
    """Verify budget checking logic with the 95% threshold."""

    def test_check_budget_passes_when_under(self, cost_guard):
        """Should not raise when well under budget."""
        # Small call, well within $38.25 * 0.95 = $36.3375
        cost_guard.check_budget(1000, 1000)  # Should not raise

    def test_check_budget_raises_when_over_threshold(self):
        """Should raise BudgetExhaustedError when estimated cost + spend > 95% ceiling."""
        guard = CostGuard(
            budget_ceiling_usd=Decimal("10.00"),
            cost_input_per_million=Decimal("0.60"),
            cost_output_per_million=Decimal("2.50"),
        )
        # Spend $9.00 first, which is already past 90%
        guard.record_exact_cost(Decimal("9.00"))
        # Now try to check budget for a call that will cost ~$0.60 more
        # 9.00 + 0.60 = 9.60 > 9.50 (95% of 10.00)
        with pytest.raises(BudgetExhaustedError):
            guard.check_budget(1_000_000, 0)  # $0.60 input cost

    def test_check_budget_raises_message_contains_details(self):
        guard = CostGuard(
            budget_ceiling_usd=Decimal("10.00"),
            cost_input_per_million=Decimal("0.60"),
            cost_output_per_million=Decimal("2.50"),
        )
        guard.record_exact_cost(Decimal("9.50"))
        with pytest.raises(BudgetExhaustedError, match="Budget would be exceeded"):
            guard.check_budget(1_000_000, 1_000_000)

    def test_check_budget_exactly_at_threshold(self):
        """Exactly at the 95% threshold should still pass (not strictly greater)."""
        guard = CostGuard(
            budget_ceiling_usd=Decimal("100.00"),
            cost_input_per_million=Decimal("1.00"),
            cost_output_per_million=Decimal("0.00"),
        )
        # 95% of 100 = 95.00; spend 94.00 then try to add 1.00 (1M input tokens)
        guard.record_exact_cost(Decimal("94.00"))
        # 94.00 + 1.00 = 95.00 which is NOT > 95.00, so should pass
        guard.check_budget(1_000_000, 0)  # Should not raise

    def test_check_budget_just_over_threshold(self):
        """Just over 95% threshold should raise."""
        guard = CostGuard(
            budget_ceiling_usd=Decimal("100.00"),
            cost_input_per_million=Decimal("1.00"),
            cost_output_per_million=Decimal("0.00"),
        )
        # 95% of 100 = 95.00; spend 94.01 then try to add 1.00
        guard.record_exact_cost(Decimal("94.01"))
        # 94.01 + 1.00 = 95.01 > 95.00, should raise
        with pytest.raises(BudgetExhaustedError):
            guard.check_budget(1_000_000, 0)


class TestBudgetUtilizationPct:
    """Verify percentage calculation."""

    def test_zero_spend_gives_zero_pct(self, cost_guard):
        assert cost_guard.budget_utilization_pct == pytest.approx(0.0)

    def test_half_spend_gives_50_pct(self):
        guard = CostGuard(
            budget_ceiling_usd=Decimal("100.00"),
            cost_input_per_million=Decimal("0.60"),
            cost_output_per_million=Decimal("2.50"),
        )
        guard.record_exact_cost(Decimal("50.00"))
        assert guard.budget_utilization_pct == pytest.approx(50.0)

    def test_full_spend_gives_100_pct(self):
        guard = CostGuard(
            budget_ceiling_usd=Decimal("100.00"),
            cost_input_per_million=Decimal("0.60"),
            cost_output_per_million=Decimal("2.50"),
        )
        guard.record_exact_cost(Decimal("100.00"))
        assert guard.budget_utilization_pct == pytest.approx(100.0)

    def test_zero_ceiling_gives_100_pct(self):
        """Edge case: zero budget ceiling returns 100% to prevent any spending."""
        guard = CostGuard(
            budget_ceiling_usd=Decimal("0.00"),
            cost_input_per_million=Decimal("0.60"),
            cost_output_per_million=Decimal("2.50"),
        )
        assert guard.budget_utilization_pct == pytest.approx(100.0)

    def test_returns_float(self, cost_guard):
        assert isinstance(cost_guard.budget_utilization_pct, float)


class TestWarningLevels:
    """Verify warning level thresholds."""

    def _make_guard_at_pct(self, pct: float) -> CostGuard:
        """Helper: create a guard where utilization is at the given percentage."""
        guard = CostGuard(
            budget_ceiling_usd=Decimal("100.00"),
            cost_input_per_million=Decimal("0.60"),
            cost_output_per_million=Decimal("2.50"),
        )
        guard.record_exact_cost(Decimal(str(pct)))
        return guard

    def test_warning_none_at_zero(self):
        guard = self._make_guard_at_pct(0)
        assert guard.get_warning_level() is None

    def test_warning_none_at_49(self):
        guard = self._make_guard_at_pct(49)
        assert guard.get_warning_level() is None

    def test_warning_moderate_at_50(self):
        guard = self._make_guard_at_pct(50)
        assert guard.get_warning_level() == "moderate"

    def test_warning_moderate_at_74(self):
        guard = self._make_guard_at_pct(74)
        assert guard.get_warning_level() == "moderate"

    def test_warning_high_at_75(self):
        guard = self._make_guard_at_pct(75)
        assert guard.get_warning_level() == "high"

    def test_warning_high_at_89(self):
        guard = self._make_guard_at_pct(89)
        assert guard.get_warning_level() == "high"

    def test_warning_critical_at_90(self):
        guard = self._make_guard_at_pct(90)
        assert guard.get_warning_level() == "critical"

    def test_warning_critical_at_100(self):
        guard = self._make_guard_at_pct(100)
        assert guard.get_warning_level() == "critical"


class TestFromSettings:
    """Verify the factory method CostGuard.from_settings()."""

    def test_from_settings_creates_instance(self, settings):
        guard = CostGuard.from_settings(settings)
        assert isinstance(guard, CostGuard)

    def test_from_settings_uses_budget_ceiling(self, settings):
        guard = CostGuard.from_settings(settings)
        assert guard.budget_ceiling_usd == settings.BUDGET_CEILING_USD

    def test_from_settings_uses_input_cost(self, settings):
        guard = CostGuard.from_settings(settings)
        assert guard.cost_input_per_million == settings.COST_INPUT_PER_MILLION

    def test_from_settings_uses_output_cost(self, settings):
        guard = CostGuard.from_settings(settings)
        assert guard.cost_output_per_million == settings.COST_OUTPUT_PER_MILLION

    def test_from_settings_initial_spend_is_zero(self, settings):
        guard = CostGuard.from_settings(settings)
        assert guard.cumulative_spend == Decimal("0.00")
