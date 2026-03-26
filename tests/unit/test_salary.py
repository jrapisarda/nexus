"""Unit tests for issue_participation_salary() in nexus_core.economy.ledger."""

from decimal import Decimal
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


def _build_execute_side_effects(*, already_paid: bool = False, tx_id=None):
    """Build a list of mock results for the execute calls in issue_participation_salary.

    When emit_event is patched out, conn.execute is called for:
      1. SELECT COUNT (idempotency check)  -> scalar_one() = 0
      2. INSERT (mint_credits)             -> scalar_one() = tx_id
      3. UPDATE (set transaction_type)     -> (no meaningful return)

    When already paid:
      1. SELECT COUNT (idempotency check)  -> scalar_one() = 1
    """
    if tx_id is None:
        tx_id = uuid4()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1 if already_paid else 0

    if already_paid:
        return [count_result], tx_id

    insert_result = MagicMock()
    insert_result.scalar_one.return_value = tx_id

    # The UPDATE for transaction_type does not need a meaningful return value.
    noop = MagicMock()

    return [count_result, insert_result, noop], tx_id


# ---------------------------------------------------------------------------
# Helpers for expected salary computation
# ---------------------------------------------------------------------------

def _expected_salary(
    objective_budget: Decimal,
    reputation_score: Decimal,
    salary_budget_rate: Decimal = Decimal("0.12"),
    salary_min: Decimal = Decimal("1.00"),
    salary_max: Decimal = Decimal("5.00"),
) -> Decimal:
    """Mirror the salary formula in issue_participation_salary."""
    base = max(salary_min, objective_budget * salary_budget_rate)
    rep = Decimal(str(reputation_score))
    reputation_multiplier = Decimal("0.8") + (rep * Decimal("0.4"))
    amount = min(base * reputation_multiplier, salary_max).quantize(Decimal("0.01"))
    return amount


# ---------------------------------------------------------------------------
# TestParticipationSalaryComputation — parameterised across rep & budget
# ---------------------------------------------------------------------------

class TestParticipationSalaryComputation:
    """Verify the salary formula produces correct amounts."""

    @pytest.mark.parametrize(
        "reputation_score, objective_budget",
        [
            (Decimal("0.0"), Decimal("5")),
            (Decimal("0.0"), Decimal("10")),
            (Decimal("0.0"), Decimal("50")),
            (Decimal("0.0"), Decimal("100")),
            (Decimal("0.5"), Decimal("5")),
            (Decimal("0.5"), Decimal("10")),
            (Decimal("0.5"), Decimal("50")),
            (Decimal("0.5"), Decimal("100")),
            (Decimal("1.0"), Decimal("5")),
            (Decimal("1.0"), Decimal("10")),
            (Decimal("1.0"), Decimal("50")),
            (Decimal("1.0"), Decimal("100")),
        ],
        ids=[
            "rep0.0-budget5",
            "rep0.0-budget10",
            "rep0.0-budget50",
            "rep0.0-budget100",
            "rep0.5-budget5",
            "rep0.5-budget10",
            "rep0.5-budget50",
            "rep0.5-budget100",
            "rep1.0-budget5",
            "rep1.0-budget10",
            "rep1.0-budget50",
            "rep1.0-budget100",
        ],
    )
    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_salary_amount_matches_formula(
        self, mock_emit, mock_conn, reputation_score, objective_budget
    ):
        """The minted amount should equal the formula:
        min(max(salary_min, budget * rate) * (0.8 + rep * 0.4), salary_max)
        """
        from nexus_core.economy.ledger import issue_participation_salary

        finding_id = uuid4()
        persona_id = uuid4()
        tx_id = uuid4()

        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        result = await issue_participation_salary(
            conn=mock_conn,
            finding_id=finding_id,
            persona_id=persona_id,
            objective_budget=objective_budget,
            reputation_score=reputation_score,
        )

        assert result == tx_id

        expected = _expected_salary(objective_budget, reputation_score)

        # The second execute call is mint_credits INSERT — extract its amount param
        mint_insert_call = mock_conn.execute.call_args_list[1]
        mint_clause = mint_insert_call[0][0]
        compiled = mint_clause.compile()
        params = compiled.params
        assert Decimal(str(params["amount"])) == expected, (
            f"Expected salary={expected} for budget={objective_budget}, rep={reputation_score}"
        )


# ---------------------------------------------------------------------------
# TestParticipationSalaryIdempotency
# ---------------------------------------------------------------------------

class TestParticipationSalaryIdempotency:
    """Salary should be issued at most once per finding_id."""

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_returns_none_when_already_paid(self, mock_emit, mock_conn):
        """If the idempotency check finds an existing salary, return None."""
        from nexus_core.economy.ledger import issue_participation_salary

        effects, _ = _build_execute_side_effects(already_paid=True)
        mock_conn.execute = AsyncMock(side_effect=effects)

        result = await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        assert result is None

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_no_insert_when_already_paid(self, mock_emit, mock_conn):
        """When already paid, only the idempotency SELECT should be executed."""
        from nexus_core.economy.ledger import issue_participation_salary

        effects, _ = _build_execute_side_effects(already_paid=True)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        # Only 1 execute call: the idempotency check
        assert mock_conn.execute.call_count == 1

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_emit_event_not_called_when_already_paid(self, mock_emit, mock_conn):
        """No salary_issued event should fire for a duplicate."""
        from nexus_core.economy.ledger import issue_participation_salary

        effects, _ = _build_execute_side_effects(already_paid=True)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        mock_emit.assert_not_called()

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_first_call_succeeds(self, mock_emit, mock_conn):
        """The first call for a finding should return a valid tx_id."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        result = await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        assert result == tx_id


# ---------------------------------------------------------------------------
# TestParticipationSalaryCapping
# ---------------------------------------------------------------------------

class TestParticipationSalaryCapping:
    """Salary must stay within [salary_min, salary_max]."""

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_salary_never_below_min(self, mock_emit, mock_conn):
        """With a tiny budget and 0 reputation, salary should be at least salary_min * 0.8."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        # Budget of 0.01 * 0.12 = 0.0012, which is below salary_min=1.00
        # so base = max(1.00, 0.0012) = 1.00
        # with rep=0.0 -> multiplier=0.8, amount = 1.00 * 0.8 = 0.80
        result = await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("0.01"),
            reputation_score=Decimal("0.0"),
        )

        assert result == tx_id
        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        amount = Decimal(str(mint_insert["amount"]))
        # The base is salary_min (1.00) because budget*rate < salary_min
        # After rep multiplier (0.8): 1.00 * 0.8 = 0.80
        assert amount == Decimal("0.80")

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_salary_min_used_when_budget_rate_is_lower(self, mock_emit, mock_conn):
        """When objective_budget * salary_budget_rate < salary_min, base = salary_min."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        # budget=5, rate=0.12 -> 0.60 < salary_min=1.00 so base=1.00
        # rep=1.0 -> multiplier=1.2, amount = 1.00 * 1.2 = 1.20
        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("5"),
            reputation_score=Decimal("1.0"),
        )

        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        amount = Decimal(str(mint_insert["amount"]))
        assert amount == Decimal("1.20")

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_salary_never_above_max(self, mock_emit, mock_conn):
        """With a huge budget and max reputation, salary should cap at salary_max."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        # budget=1000, rate=0.12 -> base=120.00, multiplier=1.2 -> 144.00
        # Capped at salary_max=5.00
        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("1000"),
            reputation_score=Decimal("1.0"),
        )

        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        amount = Decimal(str(mint_insert["amount"]))
        assert amount == Decimal("5.00")

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_custom_salary_max_is_respected(self, mock_emit, mock_conn):
        """Passing a custom salary_max should cap at that value."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        # budget=100, rate=0.12 -> base=12.00, rep=1.0 -> multiplier=1.2
        # amount would be 14.40, but salary_max=3.00
        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("100"),
            reputation_score=Decimal("1.0"),
            salary_max=Decimal("3.00"),
        )

        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        amount = Decimal(str(mint_insert["amount"]))
        assert amount == Decimal("3.00")

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_custom_salary_min_is_respected(self, mock_emit, mock_conn):
        """Passing a custom salary_min should raise the floor."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        # budget=5, rate=0.12 -> 0.60, custom salary_min=2.00 so base=2.00
        # rep=0.5 -> multiplier=1.0 -> amount=2.00
        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("5"),
            reputation_score=Decimal("0.5"),
            salary_min=Decimal("2.00"),
            salary_max=Decimal("10.00"),
        )

        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        amount = Decimal(str(mint_insert["amount"]))
        assert amount == Decimal("2.00")


# ---------------------------------------------------------------------------
# TestParticipationSalaryTransactionType
# ---------------------------------------------------------------------------

class TestParticipationSalaryTransactionType:
    """Verify the ledger entry is updated to participation_salary."""

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_mint_credits_uses_mint_type_initially(self, mock_emit, mock_conn):
        """The INSERT via mint_credits should have transaction_type='mint'."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        # Call index 1 is mint_credits INSERT
        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        assert mint_insert["transaction_type"] == "mint"

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_transaction_type_updated_to_participation_salary(
        self, mock_emit, mock_conn
    ):
        """After mint, an UPDATE should set transaction_type='participation_salary'."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        # Call index 2 is the UPDATE to set transaction_type
        # (index 0 = idempotency check, 1 = mint INSERT, 2 = UPDATE type)
        # Note: emit_event is patched, so calls 2 onward in execute are the UPDATE
        # from issue_participation_salary directly (not emit_event's INSERT).
        update_call = mock_conn.execute.call_args_list[2]
        update_clause = update_call[0][0]
        compiled = update_clause.compile()
        params = compiled.params
        assert params["transaction_type"] == "participation_salary"


# ---------------------------------------------------------------------------
# TestParticipationSalaryEventEmission
# ---------------------------------------------------------------------------

class TestParticipationSalaryEventEmission:
    """Verify salary_issued event is emitted correctly."""

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_salary_issued_event_emitted(self, mock_emit, mock_conn):
        """A successful salary should emit salary_issued via emit_event."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        persona_id = uuid4()
        finding_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=finding_id,
            persona_id=persona_id,
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        # emit_event is called twice: once by mint_credits (economy_mint)
        # and once by issue_participation_salary (salary_issued)
        assert mock_emit.call_count == 2

        # The second call should be salary_issued
        salary_call = mock_emit.call_args_list[1]
        assert salary_call[0][1] == "salary_issued"

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_salary_event_payload_contains_amount(self, mock_emit, mock_conn):
        """The salary_issued event payload should include the amount."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        salary_call = mock_emit.call_args_list[1]
        payload = salary_call[1].get("payload") or salary_call[0][4] if len(salary_call[0]) > 4 else salary_call[1]["payload"]
        assert "amount" in payload

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_salary_event_payload_contains_finding_id(self, mock_emit, mock_conn):
        """The salary_issued event payload should include the finding_id."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        finding_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=finding_id,
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        salary_call = mock_emit.call_args_list[1]
        payload = salary_call[1].get("payload") or salary_call[0][4] if len(salary_call[0]) > 4 else salary_call[1]["payload"]
        assert payload["finding_id"] == str(finding_id)

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_salary_event_payload_contains_transaction_id(
        self, mock_emit, mock_conn
    ):
        """The salary_issued event payload should include the transaction_id."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        salary_call = mock_emit.call_args_list[1]
        payload = salary_call[1].get("payload") or salary_call[0][4] if len(salary_call[0]) > 4 else salary_call[1]["payload"]
        assert payload["transaction_id"] == str(tx_id)

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_salary_event_entity_type_is_persona(self, mock_emit, mock_conn):
        """The salary_issued event should have entity_type='persona'."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        persona_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=persona_id,
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        salary_call = mock_emit.call_args_list[1]
        # entity_id and entity_type are passed as kwargs
        assert salary_call[1]["entity_type"] == "persona"
        assert salary_call[1]["entity_id"] == persona_id


# ---------------------------------------------------------------------------
# TestParticipationSalaryReturnValue
# ---------------------------------------------------------------------------

class TestParticipationSalaryReturnValue:
    """Verify the function returns the correct transaction_id or None."""

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_returns_transaction_id_on_success(self, mock_emit, mock_conn):
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        result = await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        assert result == tx_id

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_returns_none_on_duplicate(self, mock_emit, mock_conn):
        from nexus_core.economy.ledger import issue_participation_salary

        effects, _ = _build_execute_side_effects(already_paid=True)
        mock_conn.execute = AsyncMock(side_effect=effects)

        result = await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        assert result is None


# ---------------------------------------------------------------------------
# TestParticipationSalaryReferencePropagation
# ---------------------------------------------------------------------------

class TestParticipationSalaryReferencePropagation:
    """Verify finding_id and objective_id are propagated to mint_credits."""

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_finding_id_passed_to_mint(self, mock_emit, mock_conn):
        """The reference_finding_id on the minted row should match finding_id."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        finding_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=finding_id,
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        assert mint_insert["reference_finding_id"] == finding_id

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_objective_id_passed_to_mint(self, mock_emit, mock_conn):
        """The reference_objective_id on the minted row should match the one passed in."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        objective_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
            reference_objective_id=objective_id,
        )

        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        assert mint_insert["reference_objective_id"] == objective_id

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_objective_id_defaults_to_none(self, mock_emit, mock_conn):
        """When reference_objective_id is not passed, it should be None."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        assert mint_insert["reference_objective_id"] is None


# ---------------------------------------------------------------------------
# TestParticipationSalaryEdgeCases
# ---------------------------------------------------------------------------

class TestParticipationSalaryEdgeCases:
    """Edge-case scenarios for salary computation."""

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_reputation_score_as_float_is_handled(self, mock_emit, mock_conn):
        """The function should accept float reputation_score (not just Decimal)."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        # Pass a float instead of Decimal — the function converts via Decimal(str(...))
        result = await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=0.75,  # float, not Decimal
        )

        assert result == tx_id

        expected = _expected_salary(Decimal("50"), Decimal("0.75"))
        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        assert Decimal(str(mint_insert["amount"])) == expected

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_zero_budget_uses_salary_min(self, mock_emit, mock_conn):
        """With objective_budget=0, base = salary_min."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("0"),
            reputation_score=Decimal("0.5"),
        )

        # base = max(1.00, 0*0.12=0) = 1.00, multiplier=1.0, amount=1.00
        expected = _expected_salary(Decimal("0"), Decimal("0.5"))
        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        assert Decimal(str(mint_insert["amount"])) == expected
        assert expected == Decimal("1.00")

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_exact_boundary_at_salary_max(self, mock_emit, mock_conn):
        """When the computed amount exactly equals salary_max, it should pass through."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        # We want base * multiplier == salary_max exactly.
        # salary_max = 5.00. Let's pick rep=0.5 (multiplier=1.0) and
        # budget such that budget * 0.12 = 5.00 -> budget = 41.6667
        # max(1.00, 41.6667 * 0.12) = max(1.00, 5.000004) = 5.000004
        # That's slightly over. Use salary_budget_rate to make it exact:
        # budget=50, rate=0.10 -> 5.00, rep=0.5 -> multiplier=1.0, amount=5.00
        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
            salary_budget_rate=Decimal("0.10"),
        )

        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        amount = Decimal(str(mint_insert["amount"]))
        assert amount == Decimal("5.00")

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_amount_is_quantized_to_two_decimal_places(self, mock_emit, mock_conn):
        """The salary amount should always be rounded to 2 decimal places."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        # budget=10, rate=0.12 -> base=1.20, rep=0.7 -> multiplier=1.08
        # amount = 1.20 * 1.08 = 1.296 -> quantized to 1.30
        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("10"),
            reputation_score=Decimal("0.7"),
        )

        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        amount = Decimal(str(mint_insert["amount"]))
        # Verify it has at most 2 decimal places
        assert amount == amount.quantize(Decimal("0.01"))
        expected = _expected_salary(Decimal("10"), Decimal("0.7"))
        assert amount == expected

    @patch("nexus_core.economy.ledger.emit_event", new_callable=AsyncMock)
    async def test_memo_contains_amount(self, mock_emit, mock_conn):
        """The memo field should include the computed salary amount."""
        from nexus_core.economy.ledger import issue_participation_salary

        tx_id = uuid4()
        effects, _ = _build_execute_side_effects(already_paid=False, tx_id=tx_id)
        mock_conn.execute = AsyncMock(side_effect=effects)

        await issue_participation_salary(
            conn=mock_conn,
            finding_id=uuid4(),
            persona_id=uuid4(),
            objective_budget=Decimal("50"),
            reputation_score=Decimal("0.5"),
        )

        mint_insert = mock_conn.execute.call_args_list[1][0][0].compile().params
        amount = str(mint_insert["amount"])
        memo = mint_insert["memo"]
        assert amount in memo
        assert "Participation salary" in memo
