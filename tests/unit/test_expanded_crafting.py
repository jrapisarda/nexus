"""Unit tests for expanded crafting helpers in nexus_core.market.service."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nexus_core.market.service import (
    MARKET_MAKER_ROLES,
    _check_supply_cap,
    _increment_craft_count,
    _select_template_for_persona,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_persona(role_class: str, available_balance: Decimal = Decimal("200.00")) -> SimpleNamespace:
    """Create a minimal persona-like object."""
    return SimpleNamespace(
        persona_id=uuid4(),
        role_class=role_class,
        available_balance=available_balance,
    )


def _make_template(
    template_code: str,
    allowed_crafter_roles: list[str] | None = None,
    craft_cost: Decimal = Decimal("5.00"),
    default_price: Decimal = Decimal("15.00"),
) -> SimpleNamespace:
    """Create a minimal template-like object."""
    return SimpleNamespace(
        template_id=uuid4(),
        template_code=template_code,
        allowed_crafter_roles=allowed_crafter_roles,
        craft_cost=craft_cost,
        default_price=default_price,
    )


def _make_settings(idle_threshold: Decimal = Decimal("120.00")) -> SimpleNamespace:
    """Create a minimal settings-like object with the threshold used by _is_distressed_balance."""
    return SimpleNamespace(MARKET_IDLE_BALANCE_THRESHOLD=idle_threshold)


# ---------------------------------------------------------------------------
# _select_template_for_persona
# ---------------------------------------------------------------------------

class TestSelectTemplateForPersona:
    """Tests for template selection logic based on persona role and permissions."""

    def test_role_in_allowed_crafter_roles(self):
        """A researcher with a template allowing researcher/analyst should be selected."""
        template = _make_template(
            "research_bundle",
            allowed_crafter_roles=["researcher", "analyst"],
        )
        persona = _make_persona("researcher")
        settings = _make_settings()

        result = _select_template_for_persona(
            persona_row=persona,
            templates={"research_bundle": template},
            settings=settings,
        )

        assert result is not None
        assert result.template_code == "research_bundle"

    def test_role_not_in_allowed_crafter_roles(self):
        """A governor whose role is not in allowed_crafter_roles should get None.

        Governor's preferred templates are synthesis_package and memory_digest.
        If those templates only allow researchers, the governor gets nothing.
        """
        synth = _make_template(
            "synthesis_package",
            allowed_crafter_roles=["researcher"],
        )
        mem = _make_template(
            "memory_digest",
            allowed_crafter_roles=["researcher"],
        )
        persona = _make_persona("governor")
        settings = _make_settings()

        result = _select_template_for_persona(
            persona_row=persona,
            templates={"synthesis_package": synth, "memory_digest": mem},
            settings=settings,
        )

        assert result is None

    def test_fallback_to_market_maker_roles_when_allowed_is_none(self):
        """When allowed_crafter_roles is None, only MARKET_MAKER_ROLES should be allowed."""
        template = _make_template(
            "synthesis_package",
            allowed_crafter_roles=None,  # falls back to MARKET_MAKER_ROLES
        )
        # consolidator is in MARKET_MAKER_ROLES
        persona = _make_persona("consolidator")
        settings = _make_settings()

        result = _select_template_for_persona(
            persona_row=persona,
            templates={"synthesis_package": template},
            settings=settings,
        )

        assert result is not None
        assert result.template_code == "synthesis_package"

    def test_fallback_rejects_non_market_maker_role(self):
        """When allowed_crafter_roles is None, a non-MARKET_MAKER role should be rejected.

        Governor preferred codes: synthesis_package, memory_digest.
        Both have allowed_crafter_roles=None, so fallback to MARKET_MAKER_ROLES.
        Governor is NOT in MARKET_MAKER_ROLES.
        """
        synth = _make_template("synthesis_package", allowed_crafter_roles=None)
        mem = _make_template("memory_digest", allowed_crafter_roles=None)
        persona = _make_persona("governor")
        settings = _make_settings()

        result = _select_template_for_persona(
            persona_row=persona,
            templates={"synthesis_package": synth, "memory_digest": mem},
            settings=settings,
        )

        assert result is None

    def test_researcher_can_access_knowledge_digest(self):
        """Researcher role should be able to access the knowledge_digest template."""
        template = _make_template(
            "knowledge_digest",
            allowed_crafter_roles=["researcher", "analyst", "synthesizer", "consolidator"],
        )
        persona = _make_persona("researcher")
        settings = _make_settings()

        result = _select_template_for_persona(
            persona_row=persona,
            templates={"knowledge_digest": template},
            settings=settings,
        )

        assert result is not None
        assert result.template_code == "knowledge_digest"

    def test_selects_affordable_template(self):
        """When persona is not distressed, the first affordable template is returned."""
        expensive = _make_template(
            "research_bundle",
            allowed_crafter_roles=["researcher"],
            craft_cost=Decimal("300.00"),
            default_price=Decimal("50.00"),
        )
        cheap = _make_template(
            "knowledge_digest",
            allowed_crafter_roles=["researcher"],
            craft_cost=Decimal("5.00"),
            default_price=Decimal("15.00"),
        )
        persona = _make_persona("researcher", available_balance=Decimal("200.00"))
        settings = _make_settings(idle_threshold=Decimal("120.00"))

        result = _select_template_for_persona(
            persona_row=persona,
            templates={"research_bundle": expensive, "knowledge_digest": cheap},
            settings=settings,
        )

        # research_bundle costs 300, persona has 200, so it should be skipped.
        # knowledge_digest costs 5, which is affordable.
        assert result is not None
        assert result.template_code == "knowledge_digest"

    def test_distressed_persona_gets_cheapest_template(self):
        """A distressed persona should get the template with the lowest craft_cost."""
        expensive = _make_template(
            "research_bundle",
            allowed_crafter_roles=["researcher"],
            craft_cost=Decimal("10.00"),
            default_price=Decimal("30.00"),
        )
        cheap = _make_template(
            "knowledge_digest",
            allowed_crafter_roles=["researcher"],
            craft_cost=Decimal("3.00"),
            default_price=Decimal("12.00"),
        )
        # Balance below idle threshold = distressed
        persona = _make_persona("researcher", available_balance=Decimal("50.00"))
        settings = _make_settings(idle_threshold=Decimal("120.00"))

        result = _select_template_for_persona(
            persona_row=persona,
            templates={"research_bundle": expensive, "knowledge_digest": cheap},
            settings=settings,
        )

        assert result is not None
        assert result.template_code == "knowledge_digest"

    def test_no_templates_available_returns_none(self):
        """When templates dict is empty, should return None."""
        persona = _make_persona("researcher")
        settings = _make_settings()

        result = _select_template_for_persona(
            persona_row=persona,
            templates={},
            settings=settings,
        )

        assert result is None

    def test_market_maker_roles_set(self):
        """Verify MARKET_MAKER_ROLES contains the expected roles."""
        expected = {"consolidator", "synthesizer", "tool_forger", "architect"}
        assert MARKET_MAKER_ROLES == expected


# ---------------------------------------------------------------------------
# _check_supply_cap
# ---------------------------------------------------------------------------

class TestCheckSupplyCap:
    """Tests for supply cap checking on template crafting per cycle."""

    @pytest.fixture
    def mock_conn(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        return conn

    async def test_no_cap_returns_true(self, mock_conn):
        """When max_crafts is None, crafting should always be allowed."""
        result = await _check_supply_cap(mock_conn, uuid4(), cycle_tick=1, max_crafts=None)
        assert result is True

    async def test_zero_cycle_tick_returns_true(self, mock_conn):
        """When cycle_tick <= 0, no tracking means always allowed."""
        result = await _check_supply_cap(mock_conn, uuid4(), cycle_tick=0, max_crafts=3)
        assert result is True

    async def test_under_cap_returns_true(self, mock_conn):
        """When craft_count < max_crafts, crafting should be allowed."""
        row = MagicMock()
        row.craft_count = 1
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = row
        mock_conn.execute.return_value = mock_result

        result = await _check_supply_cap(mock_conn, uuid4(), cycle_tick=5, max_crafts=3)
        assert result is True

    async def test_at_cap_returns_false(self, mock_conn):
        """When craft_count == max_crafts, crafting should be blocked."""
        row = MagicMock()
        row.craft_count = 3
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = row
        mock_conn.execute.return_value = mock_result

        result = await _check_supply_cap(mock_conn, uuid4(), cycle_tick=5, max_crafts=3)
        assert result is False

    async def test_above_cap_returns_false(self, mock_conn):
        """When craft_count > max_crafts, crafting should be blocked."""
        row = MagicMock()
        row.craft_count = 5
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = row
        mock_conn.execute.return_value = mock_result

        result = await _check_supply_cap(mock_conn, uuid4(), cycle_tick=5, max_crafts=3)
        assert result is False

    async def test_no_existing_row_returns_true(self, mock_conn):
        """First craft in a cycle (no row exists) should be allowed."""
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await _check_supply_cap(mock_conn, uuid4(), cycle_tick=5, max_crafts=3)
        assert result is True


# ---------------------------------------------------------------------------
# _increment_craft_count
# ---------------------------------------------------------------------------

class TestIncrementCraftCount:
    """Tests for _increment_craft_count() — upserts the cycle craft counter."""

    @pytest.fixture
    def mock_conn(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        return conn

    async def test_zero_cycle_tick_returns_early(self, mock_conn):
        """When cycle_tick <= 0, no DB call should be made."""
        await _increment_craft_count(mock_conn, uuid4(), cycle_tick=0)
        mock_conn.execute.assert_not_called()

    async def test_existing_row_updates(self, mock_conn):
        """When an existing row is updated (rowcount=1), no INSERT should follow."""
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result

        await _increment_craft_count(mock_conn, uuid4(), cycle_tick=5)

        # Only one call: the UPDATE
        assert mock_conn.execute.call_count == 1

    async def test_no_existing_row_inserts(self, mock_conn):
        """When UPDATE affects 0 rows, an INSERT should follow."""
        mock_update_result = MagicMock()
        mock_update_result.rowcount = 0
        mock_insert_result = MagicMock()

        mock_conn.execute.side_effect = [mock_update_result, mock_insert_result]

        await _increment_craft_count(mock_conn, uuid4(), cycle_tick=5)

        # Two calls: UPDATE (rowcount=0) then INSERT
        assert mock_conn.execute.call_count == 2
