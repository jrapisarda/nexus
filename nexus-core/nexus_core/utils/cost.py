from decimal import Decimal
from dataclasses import dataclass, field


class BudgetExhaustedError(Exception):
    """Raised when the budget ceiling would be exceeded."""
    pass


@dataclass(frozen=True)
class CostBreakdown:
    input_cost_usd: Decimal
    thinking_cost_usd: Decimal
    output_cost_usd: Decimal
    total_cost_usd: Decimal


def coerce_decimal_rate(value, default: Decimal) -> Decimal:
    """Coerce a numeric config value to Decimal, falling back when unavailable."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except Exception:
            return default
    return default


def calculate_cost_breakdown(
    *,
    input_tokens: int,
    thinking_tokens: int,
    output_tokens: int,
    cost_input_per_million: Decimal,
    cost_output_per_million: Decimal,
) -> CostBreakdown:
    """Calculate exact token-cost breakdown using configured per-token rates."""
    input_cost = (
        Decimal(input_tokens) / Decimal("1000000")
    ) * cost_input_per_million
    thinking_cost = (
        Decimal(thinking_tokens) / Decimal("1000000")
    ) * cost_output_per_million
    output_cost = (
        Decimal(output_tokens) / Decimal("1000000")
    ) * cost_output_per_million
    total_cost = input_cost + thinking_cost + output_cost
    quantum = Decimal("0.000001")
    return CostBreakdown(
        input_cost_usd=input_cost.quantize(quantum),
        thinking_cost_usd=thinking_cost.quantize(quantum),
        output_cost_usd=output_cost.quantize(quantum),
        total_cost_usd=total_cost.quantize(quantum),
    )


@dataclass
class CostGuard:
    """Tracks cumulative API spend and prevents budget overrun."""

    budget_ceiling_usd: Decimal
    cost_input_per_million: Decimal
    cost_output_per_million: Decimal
    _cumulative_spend: Decimal = field(default=Decimal("0.00"), init=False)

    @property
    def cumulative_spend(self) -> Decimal:
        return self._cumulative_spend

    @property
    def remaining_budget(self) -> Decimal:
        return self.budget_ceiling_usd - self._cumulative_spend

    def estimate_call_cost(
        self, estimated_input_tokens: int, estimated_output_tokens: int = 4096
    ) -> Decimal:
        """Estimate cost of an API call before making it."""
        return calculate_cost_breakdown(
            input_tokens=estimated_input_tokens,
            thinking_tokens=0,
            output_tokens=estimated_output_tokens,
            cost_input_per_million=self.cost_input_per_million,
            cost_output_per_million=self.cost_output_per_million,
        ).total_cost_usd

    def check_budget(
        self, estimated_input_tokens: int, estimated_output_tokens: int = 4096
    ) -> None:
        """Raise BudgetExhaustedError if estimated call would exceed 95% of budget."""
        estimated_cost = self.estimate_call_cost(
            estimated_input_tokens, estimated_output_tokens
        )
        threshold = self.budget_ceiling_usd * Decimal("0.95")
        if self._cumulative_spend + estimated_cost > threshold:
            raise BudgetExhaustedError(
                f"Budget would be exceeded: current spend ${self._cumulative_spend:.4f} + "
                f"estimated ${estimated_cost:.4f} > 95% ceiling ${threshold:.4f}"
            )

    def record_spend(
        self, input_tokens: int, output_tokens: int, thinking_tokens: int = 0
    ) -> Decimal:
        """Record actual spend after a call completes. Returns the cost."""
        breakdown = calculate_cost_breakdown(
            input_tokens=input_tokens,
            thinking_tokens=thinking_tokens,
            output_tokens=output_tokens,
            cost_input_per_million=self.cost_input_per_million,
            cost_output_per_million=self.cost_output_per_million,
        )
        self._cumulative_spend += breakdown.total_cost_usd
        return breakdown.total_cost_usd

    def record_exact_cost(self, cost_usd: Decimal) -> None:
        """Record an exact cost amount (e.g., from API response)."""
        self._cumulative_spend += cost_usd

    @property
    def budget_utilization_pct(self) -> float:
        """Current budget utilization as a percentage."""
        if self.budget_ceiling_usd == 0:
            return 100.0
        return float(self._cumulative_spend / self.budget_ceiling_usd * 100)

    def get_warning_level(self) -> str | None:
        """Return warning level based on budget utilization."""
        pct = self.budget_utilization_pct
        if pct >= 90:
            return "critical"
        elif pct >= 75:
            return "high"
        elif pct >= 50:
            return "moderate"
        return None

    @classmethod
    def from_settings(cls, settings) -> "CostGuard":
        """Create from NexusSettings."""
        return cls(
            budget_ceiling_usd=settings.BUDGET_CEILING_USD,
            cost_input_per_million=settings.COST_INPUT_PER_MILLION,
            cost_output_per_million=settings.COST_OUTPUT_PER_MILLION,
        )
