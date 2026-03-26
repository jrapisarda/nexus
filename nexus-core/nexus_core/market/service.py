"""Deterministic autonomous marketplace and securities exchange services."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus_core.civilization.service import create_bond, ensure_civilization_state, record_capability_signal
from nexus_core.config import NexusSettings
from nexus_core.economy.ledger import balance_expression
from nexus_core.llm.prompt_builder import PromptBuilder
from nexus_core.llm.response_parser import ResponseParser
from nexus_core.models.economy import economy_ledger
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.market import (
    market_assets,
    market_instruments,
    market_orders,
    market_positions,
    market_price_history,
    market_reservations,
    market_templates,
    market_trades,
    marketplace_listings,
    persona_market_profiles,
    service_contracts,
)
from nexus_core.models.objectives import objectives
from nexus_core.models.personas import agent_personas
from nexus_core.models.telemetry import agent_telemetry
from nexus_core.utils.events import emit_event


MONEY_QUANT = Decimal("0.01")
QTY_QUANT = Decimal("0.0001")
REPUTATION_QUANT = Decimal("0.001")
STATUS_OPEN = "open"
SUCCESSFUL_MARKET_STATUSES = {"completed", "fulfilled"}
FAILED_MARKET_STATUSES = {"refunded"}
MARKET_OBJECTIVES = {
    "marketplace": {
        "title": "Marketplace Operations",
        "description": (
            "Operate the autonomous agent marketplace for crafted goods, bounded services, "
            "escrow contracts, and seller-side fulfillment."
        ),
    },
    "securities": {
        "title": "Securities Exchange",
        "description": (
            "Operate the autonomous securities exchange for entity-backed notes, order "
            "matching, settlement, and market risk controls."
        ),
    },
}
MARKET_MAKER_ROLES = {"consolidator", "synthesizer", "tool_forger", "architect"}
GOVERNOR_ROLES = {"governor"}
SERVICE_LISTING_KINDS = {"hard_service"}
DEFAULT_MARKET_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_code": "memory_digest",
        "template_kind": "good",
        "listing_kind": "soft_good",
        "title": "Memory Digest",
        "description": "Condensed institutional memory package with relevant lessons and patterns.",
        "settlement_hook": "immediate_transfer",
        "fulfillment_mode": "immediate",
        "privilege_boundary": "read_only",
        "allowed_custom_fields": ["description", "price", "audience", "bundle_metadata"],
        "craft_cost": Decimal("4.00"),
        "default_price": Decimal("12.00"),
        "default_quantity": 1,
        "metadata_json": {"category": "memory"},
    },
    {
        "template_code": "research_bundle",
        "template_kind": "good",
        "listing_kind": "soft_good",
        "title": "Research Bundle",
        "description": "A reusable evidence bundle, references, and supporting notes.",
        "settlement_hook": "immediate_transfer",
        "fulfillment_mode": "immediate",
        "privilege_boundary": "read_only",
        "allowed_custom_fields": ["description", "price", "audience", "bundle_metadata"],
        "craft_cost": Decimal("6.00"),
        "default_price": Decimal("18.00"),
        "default_quantity": 1,
        "metadata_json": {"category": "research"},
    },
    {
        "template_code": "prompt_artifact",
        "template_kind": "good",
        "listing_kind": "soft_good",
        "title": "Prompt Artifact",
        "description": "A curated prompt/tool artifact designed for transfer and reuse.",
        "settlement_hook": "immediate_transfer",
        "fulfillment_mode": "immediate",
        "privilege_boundary": "tool_safe",
        "allowed_custom_fields": ["description", "price", "audience", "bundle_metadata"],
        "craft_cost": Decimal("8.00"),
        "default_price": Decimal("22.00"),
        "default_quantity": 1,
        "metadata_json": {"category": "tooling"},
    },
    {
        "template_code": "scout_package",
        "template_kind": "service",
        "listing_kind": "hard_service",
        "title": "Scout Package",
        "description": "Bounded external intelligence sweep tied to a target objective or finding.",
        "settlement_hook": "escrow_on_purchase",
        "fulfillment_mode": "objective_linked",
        "privilege_boundary": "bounded_service_request",
        "allowed_custom_fields": ["description", "price", "audience", "target_entity", "bundle_metadata"],
        "craft_cost": Decimal("5.00"),
        "default_price": Decimal("20.00"),
        "default_quantity": 1,
        "metadata_json": {"category": "service", "service_type": "scout"},
    },
    {
        "template_code": "review_reservation",
        "template_kind": "service",
        "listing_kind": "hard_service",
        "title": "Review Reservation",
        "description": "Reserve a bounded critical review pass with explicit target linkage.",
        "settlement_hook": "escrow_on_purchase",
        "fulfillment_mode": "objective_linked",
        "privilege_boundary": "bounded_service_request",
        "allowed_custom_fields": ["description", "price", "audience", "target_entity", "bundle_metadata"],
        "craft_cost": Decimal("5.00"),
        "default_price": Decimal("16.00"),
        "default_quantity": 1,
        "metadata_json": {"category": "service", "service_type": "review"},
    },
    {
        "template_code": "synthesis_package",
        "template_kind": "service",
        "listing_kind": "hard_service",
        "title": "Synthesis Package",
        "description": "A bounded synthesis pass for a target objective with explicit contract scope.",
        "settlement_hook": "escrow_on_purchase",
        "fulfillment_mode": "objective_linked",
        "privilege_boundary": "bounded_service_request",
        "allowed_custom_fields": ["description", "price", "audience", "target_entity", "bundle_metadata"],
        "craft_cost": Decimal("6.00"),
        "default_price": Decimal("24.00"),
        "default_quantity": 1,
        "metadata_json": {"category": "service", "service_type": "synthesis"},
    },
)


def _now() -> datetime:
    return datetime.now(UTC)


def _money(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    raw = value if isinstance(value, Decimal) else Decimal(str(value))
    return raw.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _qty(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0.0000")
    raw = value if isinstance(value, Decimal) else Decimal(str(value))
    return raw.quantize(QTY_QUANT, rounding=ROUND_HALF_UP)


def _risk_tier_for_role(role_class: str) -> str:
    if role_class in GOVERNOR_ROLES:
        return "governor"
    if role_class in MARKET_MAKER_ROLES:
        return "market_maker"
    return "standard"


def available_balance_expression(persona_id_column) -> sa.ColumnElement:
    reserved = (
        sa.select(
            sa.func.coalesce(sa.func.sum(market_reservations.c.remaining_amount), Decimal("0"))
        )
        .where(
            market_reservations.c.persona_id == persona_id_column,
            market_reservations.c.status == STATUS_OPEN,
        )
        .scalar_subquery()
    )
    return sa.type_coerce(balance_expression(persona_id_column) - reserved, sa.Numeric(12, 2))


async def ensure_market_objectives(conn: AsyncConnection) -> dict[str, UUID]:
    """Ensure standing market objectives exist so market instances always have an objective."""
    result = await conn.execute(
        sa.select(
            objectives.c.objective_id,
            objectives.c.title,
            objectives.c.status,
        ).where(
            objectives.c.objective_type == "market",
            objectives.c.title.in_([item["title"] for item in MARKET_OBJECTIVES.values()]),
        )
    )
    existing = {row.title: row for row in result.fetchall()}
    objective_ids: dict[str, UUID] = {}

    for key, item in MARKET_OBJECTIVES.items():
        row = existing.get(item["title"])
        if row is None:
            inserted = await conn.execute(
                objectives.insert()
                .values(
                    title=item["title"],
                    description=item["description"],
                    objective_type="market",
                    impact_level="routine",
                    priority=4,
                    status="active",
                    proposed_by_type="system",
                    approved_by_type="system",
                    acceptance_criteria=(
                        "Operate the standing market subsystem without mutating research queues "
                        "outside explicit service requests."
                    ),
                    output_type="market_runtime",
                )
                .returning(objectives.c.objective_id)
            )
            objective_ids[key] = inserted.scalar_one()
        else:
            objective_ids[key] = row.objective_id
            if row.status in {"failed", "escalated", "completed"}:
                await conn.execute(
                    objectives.update()
                    .where(objectives.c.objective_id == row.objective_id)
                    .values(status="active", escalation_reason=None, escalated_at=None, completed_at=None)
                )

    return objective_ids


async def sync_persona_market_profiles(
    conn: AsyncConnection,
    settings: NexusSettings,
) -> None:
    """Ensure each active persona has a market profile with a deterministic risk tier."""
    personas = (
        await conn.execute(
            sa.select(agent_personas.c.persona_id, agent_personas.c.role_class).where(
                agent_personas.c.status == "active"
            )
        )
    ).fetchall()
    existing = {
        row.persona_id: row
        for row in (
            await conn.execute(sa.select(persona_market_profiles))
        ).fetchall()
    }

    for persona in personas:
        risk_tier = _risk_tier_for_role(persona.role_class)
        max_position = Decimal("250.00") if risk_tier != "standard" else Decimal("150.00")
        if persona.persona_id not in existing:
            await conn.execute(
                persona_market_profiles.insert().values(
                    persona_id=persona.persona_id,
                    risk_tier=risk_tier,
                    max_open_orders=settings.MARKET_MAX_OPEN_ORDERS_PER_PERSONA,
                    max_position_notional=max_position,
                    collateral_ratio=settings.MARKET_DEFAULT_COLLATERAL_RATIO,
                )
            )
        else:
            await conn.execute(
                persona_market_profiles.update()
                .where(persona_market_profiles.c.persona_id == persona.persona_id)
                .values(
                    risk_tier=risk_tier,
                    max_open_orders=settings.MARKET_MAX_OPEN_ORDERS_PER_PERSONA,
                    max_position_notional=max_position,
                    collateral_ratio=settings.MARKET_DEFAULT_COLLATERAL_RATIO,
                )
            )


async def seed_market_templates(conn: AsyncConnection) -> None:
    """Insert governed listing templates if they do not already exist."""
    existing_codes = {
        row.template_code
        for row in (
            await conn.execute(sa.select(market_templates.c.template_code))
        ).fetchall()
    }
    for template in DEFAULT_MARKET_TEMPLATES:
        if template["template_code"] in existing_codes:
            continue
        await conn.execute(market_templates.insert().values(**template))


async def get_available_balance(conn: AsyncConnection, persona_id: UUID) -> Decimal:
    result = await conn.execute(
        sa.select(available_balance_expression(sa.literal(persona_id, type_=sa.Uuid)))
    )
    return _money(result.scalar_one())


async def create_reservation(
    conn: AsyncConnection,
    *,
    persona_id: UUID,
    amount: Decimal,
    reservation_type: str,
    listing_id: UUID | None = None,
    instrument_id: UUID | None = None,
    order_id: UUID | None = None,
    related_contract_id: UUID | None = None,
    memo: str | None = None,
) -> UUID | None:
    amount = _money(amount)
    if amount <= 0:
        return None
    available = await get_available_balance(conn, persona_id)
    if available < amount:
        return None
    result = await conn.execute(
        market_reservations.insert()
        .values(
            persona_id=persona_id,
            reservation_type=reservation_type,
            listing_id=listing_id,
            instrument_id=instrument_id,
            order_id=order_id,
            related_contract_id=related_contract_id,
            reserved_amount=amount,
            remaining_amount=amount,
            memo=memo,
        )
        .returning(market_reservations.c.reservation_id)
    )
    reservation_id = result.scalar_one()
    if reservation_type in {"escrow", "collateral"}:
        await create_bond(
            conn,
            persona_id=persona_id,
            bond_type="service_fulfillment" if reservation_type == "escrow" else "market_making",
            amount=amount,
            reference_contract_id=related_contract_id,
            reference_order_id=order_id,
            release_after=_now() + timedelta(minutes=60),
            memo=memo or f"Market reservation mirror for {reservation_type}",
            metadata_json={"reservation_id": str(reservation_id)},
        )
    return reservation_id


async def _apply_reservation_delta(
    conn: AsyncConnection,
    reservation_id: UUID,
    amount: Decimal | None,
    *,
    terminal_status: str,
) -> Decimal:
    row = (
        await conn.execute(
            sa.select(market_reservations).where(
                market_reservations.c.reservation_id == reservation_id
            )
        )
    ).first()
    if row is None:
        return Decimal("0.00")

    remaining = _money(row.remaining_amount)
    delta = remaining if amount is None else min(remaining, _money(amount))
    new_remaining = _money(remaining - delta)
    values: dict[str, Any] = {"remaining_amount": new_remaining}
    if new_remaining <= Decimal("0.00"):
        values["status"] = terminal_status
        values["released_at"] = _now()
    await conn.execute(
        market_reservations.update()
        .where(market_reservations.c.reservation_id == reservation_id)
        .values(**values)
    )
    return delta


async def consume_reservation(
    conn: AsyncConnection,
    reservation_id: UUID,
    amount: Decimal | None = None,
) -> Decimal:
    return await _apply_reservation_delta(
        conn,
        reservation_id,
        amount,
        terminal_status="consumed",
    )


async def release_reservation(
    conn: AsyncConnection,
    reservation_id: UUID,
    amount: Decimal | None = None,
) -> Decimal:
    return await _apply_reservation_delta(
        conn,
        reservation_id,
        amount,
        terminal_status="released",
    )


async def _transfer_credits(
    conn: AsyncConnection,
    *,
    from_persona_id: UUID | None,
    to_persona_id: UUID | None,
    amount: Decimal,
    transaction_type: str,
    memo: str,
    reference_objective_id: UUID | None = None,
    reference_finding_id: UUID | None = None,
) -> None:
    amount = _money(amount)
    if amount <= 0:
        return
    await conn.execute(
        economy_ledger.insert().values(
            from_persona_id=from_persona_id,
            to_persona_id=to_persona_id,
            amount=amount,
            transaction_type=transaction_type,
            reference_objective_id=reference_objective_id,
            reference_finding_id=reference_finding_id,
            memo=memo,
        )
    )


def _preferred_template_codes_for_role(role_class: str) -> tuple[str, ...]:
    mapping = {
        "scout": ("scout_package", "data_package", "memory_digest", "research_bundle"),
        "critic": ("review_reservation", "review_package", "memory_digest"),
        "red_team": ("review_reservation", "review_package", "research_bundle"),
        "synthesizer": ("synthesis_package", "research_bundle", "knowledge_digest"),
        "consolidator": ("synthesis_package", "memory_digest", "knowledge_digest"),
        "tool_forger": ("prompt_artifact", "memory_digest"),
        "architect": ("prompt_artifact", "synthesis_package"),
        "debugger": ("prompt_artifact", "review_reservation"),
        "researcher": ("research_bundle", "knowledge_digest", "data_package", "memory_digest"),
        "analyst": ("research_bundle", "knowledge_digest", "data_package", "memory_digest"),
        "policy_researcher": ("research_bundle", "knowledge_digest", "synthesis_package"),
        "education_strategist": ("research_bundle", "knowledge_digest", "memory_digest"),
        "economist": ("research_bundle", "knowledge_digest", "memory_digest"),
        "governor": ("synthesis_package", "memory_digest"),
        "originator": ("memory_digest", "research_bundle"),
        "infiltrator": ("review_reservation", "memory_digest"),
        "reviewer": ("review_package", "memory_digest", "knowledge_digest"),
    }
    return mapping.get(role_class, ("memory_digest", "research_bundle"))


async def _load_template_map(conn: AsyncConnection) -> dict[str, Any]:
    rows = (await conn.execute(sa.select(market_templates).where(market_templates.c.status == "active"))).fetchall()
    return {row.template_code: row for row in rows}


def _is_distressed_balance(balance: Decimal, settings: NexusSettings) -> bool:
    return _money(balance) < _money(settings.MARKET_IDLE_BALANCE_THRESHOLD)


def _is_secondary_asset(metadata: dict[str, Any] | None) -> bool:
    payload = metadata or {}
    return bool(
        payload.get("acquired_from_market")
        or payload.get("sale_channel") == "secondary_market"
        or payload.get("asset_class") in {"contract_right", "service_artifact"}
    )


def _select_template_for_persona(
    *,
    persona_row: Any,
    templates: dict[str, Any],
    settings: NexusSettings,
) -> Any | None:
    preferred_codes = _preferred_template_codes_for_role(persona_row.role_class)
    preferred_rows = []
    for code in preferred_codes:
        template = templates.get(code)
        if template is None:
            continue
        # Check DB-driven role permissions (allowed_crafter_roles column)
        allowed = getattr(template, "allowed_crafter_roles", None) or list(MARKET_MAKER_ROLES)
        if persona_row.role_class in allowed:
            preferred_rows.append(template)
    if not preferred_rows:
        return None

    available = _money(persona_row.available_balance)
    distressed = _is_distressed_balance(available, settings)
    if distressed:
        return min(
            preferred_rows,
            key=lambda row: (_money(row.craft_cost), -_money(row.default_price)),
        )

    for row in preferred_rows:
        if _money(row.craft_cost) < available:
            return row
    return None


def _listing_reference_price(*, template_row: Any, asset_metadata: dict[str, Any] | None = None) -> Decimal:
    payload = asset_metadata or {}
    raw_reference = payload.get("agreed_price") or payload.get("reference_price") or template_row.default_price
    return _money(raw_reference)


def _compute_listing_price(
    *,
    template_row: Any,
    reputation_score: Decimal | int | float | str | None,
    distressed: bool,
    secondary: bool,
    contract_asset: bool,
    asset_metadata: dict[str, Any] | None = None,
) -> Decimal:
    base = _listing_reference_price(template_row=template_row, asset_metadata=asset_metadata)
    if secondary:
        base = _money(base * Decimal("0.88"))
    if distressed:
        base = _money(base * Decimal("0.82"))
    if contract_asset:
        contract_status = str((asset_metadata or {}).get("contract_status", "pending_fulfillment"))
        if contract_status == "pending_fulfillment":
            base = _money(base * Decimal("0.92"))
        elif contract_status == "fulfilled":
            base = _money(base * Decimal("1.08"))
    reputation_markup = Decimal(str(reputation_score or 0)) * (Decimal("2.00") if distressed else Decimal("6.00"))
    return max(_money(base + reputation_markup), Decimal("2.00"))


async def _active_listing_count_for_persona(conn: AsyncConnection, persona_id: UUID) -> int:
    return int(
        await conn.scalar(
            sa.select(sa.func.count())
            .select_from(marketplace_listings)
            .where(
                marketplace_listings.c.seller_persona_id == persona_id,
                marketplace_listings.c.status == "active",
            )
        )
        or 0
    )


def _max_market_listings_per_cycle(persona_count: int, settings: NexusSettings) -> int:
    return max(4, min(persona_count, settings.MARKET_MAX_LISTINGS_PER_PERSONA * 4))


def _distressed_listing_sort_key(
    persona_row: Any,
    settings: NexusSettings,
) -> tuple[int, Decimal, Decimal]:
    available = _money(persona_row.available_balance)
    reputation = Decimal(str(persona_row.reputation_score or 0))
    return (
        0 if _is_distressed_balance(available, settings) else 1,
        available,
        -reputation,
    )


async def _insert_market_asset(
    conn: AsyncConnection,
    *,
    template_id: UUID,
    owner_persona_id: UUID,
    crafted_by_persona_id: UUID,
    asset_kind: str,
    title: str,
    description: str,
    quantity_available: int,
    metadata_json: dict[str, Any] | None = None,
    status: str = "active",
    transferable: bool = True,
) -> UUID:
    result = await conn.execute(
        market_assets.insert()
        .values(
            template_id=template_id,
            owner_persona_id=owner_persona_id,
            crafted_by_persona_id=crafted_by_persona_id,
            asset_kind=asset_kind,
            title=title,
            description=description,
            quantity_available=quantity_available,
            transferable=transferable,
            metadata_json=metadata_json or {},
            status=status,
        )
        .returning(market_assets.c.asset_id)
    )
    return result.scalar_one()


async def _close_listing(
    conn: AsyncConnection,
    *,
    listing_id: UUID,
    status: str = "sold_out",
) -> None:
    await conn.execute(
        marketplace_listings.update()
        .where(marketplace_listings.c.listing_id == listing_id)
        .values(quantity_available=0, status=status)
    )


async def _transfer_asset_to_buyer(
    conn: AsyncConnection,
    *,
    asset_id: UUID,
    buyer_id: UUID,
    metadata_updates: dict[str, Any] | None = None,
    title: str | None = None,
    description: str | None = None,
) -> None:
    row = (
        await conn.execute(
            sa.select(
                market_assets.c.metadata_json,
                market_assets.c.title,
                market_assets.c.description,
            ).where(market_assets.c.asset_id == asset_id)
        )
    ).first()
    if row is None:
        return

    metadata = dict(row.metadata_json or {})
    metadata.update(metadata_updates or {})
    await conn.execute(
        market_assets.update()
        .where(market_assets.c.asset_id == asset_id)
        .values(
            owner_persona_id=buyer_id,
            title=title or row.title,
            description=description or row.description,
            quantity_available=1,
            status="active",
            metadata_json=metadata,
        )
    )


async def _load_contract_obligation_remaining(
    conn: AsyncConnection,
    contract_id: UUID | str | None,
) -> tuple[UUID | None, Decimal]:
    if contract_id is None:
        return None, Decimal("0.00")
    contract_uuid = contract_id if isinstance(contract_id, UUID) else UUID(str(contract_id))
    contract_row = (
        await conn.execute(
            sa.select(service_contracts.c.reservation_id).where(
                service_contracts.c.contract_id == contract_uuid
            )
        )
    ).first()
    if contract_row is None or contract_row.reservation_id is None:
        return None, Decimal("0.00")
    reservation_row = (
        await conn.execute(
            sa.select(
                market_reservations.c.reservation_id,
                market_reservations.c.status,
                market_reservations.c.remaining_amount,
            ).where(market_reservations.c.reservation_id == contract_row.reservation_id)
        )
    ).first()
    if reservation_row is None or reservation_row.status != STATUS_OPEN:
        return contract_row.reservation_id, Decimal("0.00")
    return reservation_row.reservation_id, _money(reservation_row.remaining_amount)


async def _insert_market_listing(
    conn: AsyncConnection,
    *,
    asset_id: UUID,
    seller_persona_id: UUID,
    template_id: UUID,
    listing_kind: str,
    price: Decimal,
    quantity_available: int,
    description: str,
    metadata_json: dict[str, Any] | None = None,
    audience: list[str] | None = None,
) -> UUID:
    result = await conn.execute(
        marketplace_listings.insert()
        .values(
            asset_id=asset_id,
            seller_persona_id=seller_persona_id,
            template_id=template_id,
            listing_kind=listing_kind,
            price=_money(price),
            quantity_available=quantity_available,
            audience=audience or ["all_agents"],
            description=description,
            metadata_json=metadata_json or {},
        )
        .returning(marketplace_listings.c.listing_id)
    )
    return result.scalar_one()


def _purchase_candidate_sort_key(
    *,
    listing: Any,
    seller_row: Any | None,
    settings: NexusSettings,
) -> tuple[int, int, int, Decimal, Decimal, datetime]:
    asset_metadata = dict(getattr(listing, "asset_metadata_json", {}) or {})
    seller_balance = _money(getattr(seller_row, "available_balance", Decimal("0.00")))
    seller_reputation = Decimal(str(getattr(seller_row, "reputation_score", 0) or 0))
    return (
        0 if _is_distressed_balance(seller_balance, settings) else 1,
        0 if asset_metadata.get("asset_class") == "contract_right" else 1,
        0 if _is_secondary_asset(asset_metadata) else 1,
        seller_balance,
        -seller_reputation,
        listing.created_at,
    )


def _is_immediate_secondary_sale(listing_row: Any) -> bool:
    metadata = dict(getattr(listing_row, "asset_metadata_json", {}) or {})
    return _is_secondary_asset(metadata)


async def _load_market_reliability(conn: AsyncConnection, persona_id: UUID) -> tuple[int, int]:
    statuses = (
        await conn.execute(
            sa.select(service_contracts.c.status).where(service_contracts.c.seller_persona_id == persona_id)
        )
    ).fetchall()
    successful = sum(1 for row in statuses if row.status in SUCCESSFUL_MARKET_STATUSES)
    failed = sum(1 for row in statuses if row.status in FAILED_MARKET_STATUSES)
    return successful, failed


async def _apply_market_reputation_adjustment(
    conn: AsyncConnection,
    *,
    persona_id: UUID,
    outcome: str,
    context: str,
    secondary: bool = False,
    service: bool = False,
) -> Decimal:
    successful, failed = await _load_market_reliability(conn, persona_id)
    reliability = Decimal(successful + 1) / Decimal(successful + failed + 2)
    success_metric = Decimal("0.35") + (reliability * Decimal("0.40"))
    if outcome == "fulfilled_service":
        success_metric += Decimal("0.18")
    elif outcome == "completed_sale":
        success_metric += Decimal("0.10")
    elif outcome == "secondary_sale":
        success_metric += Decimal("0.12")
    elif outcome == "refunded_service":
        success_metric -= Decimal("0.22")
    if secondary:
        success_metric += Decimal("0.05")
    if service:
        success_metric += Decimal("0.05")

    success_metric = max(Decimal("0.00"), min(success_metric, Decimal("1.00")))
    current = Decimal(
        str(
            await conn.scalar(
                sa.select(agent_personas.c.reputation_score).where(agent_personas.c.persona_id == persona_id)
            )
            or Decimal("0.500")
        )
    )
    delta = ((success_metric - Decimal("0.50")) * Decimal("0.04")).quantize(
        REPUTATION_QUANT, rounding=ROUND_HALF_UP
    )
    new_reputation = min(max(current + delta, Decimal("0.000")), Decimal("1.000")).quantize(
        REPUTATION_QUANT,
        rounding=ROUND_HALF_UP,
    )
    await conn.execute(
        agent_personas.update()
        .where(agent_personas.c.persona_id == persona_id)
        .values(reputation_score=new_reputation)
    )
    await emit_event(
        conn,
        "market_reputation_adjusted",
        entity_id=persona_id,
        entity_type="persona",
        payload={
            "persona_id": str(persona_id),
            "context": context,
            "outcome": outcome,
            "success_metric": str(success_metric),
            "delta": str(delta),
            "new_reputation": str(new_reputation),
        },
    )
    await record_capability_signal(
        conn,
        persona_id=persona_id,
        capability="market",
        outcome="success" if outcome != "refunded_service" else "failure",
        magnitude=Decimal("1.20") if service else Decimal("0.85"),
    )
    return new_reputation


async def _create_contract_right_asset(
    conn: AsyncConnection,
    *,
    template_row: Any,
    contract_id: UUID,
    buyer_id: UUID,
    seller_id: UUID,
    agreed_price: Decimal,
    reservation_id: UUID | None,
) -> UUID:
    _, reservation_remaining = await _load_contract_obligation_remaining(conn, contract_id)
    return await _insert_market_asset(
        conn,
        template_id=template_row.template_id,
        owner_persona_id=buyer_id,
        crafted_by_persona_id=seller_id,
        asset_kind=template_row.listing_kind,
        title=f"Contract Right: {template_row.template_title}",
        description=(
            f"Transferable right to receive {template_row.template_title}. "
            "Ownership includes the pending service contract and reserved escrow obligation."
        ),
        quantity_available=1,
        metadata_json={
            "template_code": template_row.template_code,
            "asset_class": "contract_right",
            "contract_id": str(contract_id),
            "contract_status": "pending_fulfillment",
            "reference_price": str(_money(agreed_price)),
            "agreed_price": str(_money(agreed_price)),
            "reservation_id": str(reservation_id) if reservation_id else None,
            "reservation_remaining": str(reservation_remaining),
            "service_seller_persona_id": str(seller_id),
            "acquired_from_market": True,
            "sale_channel": "secondary_market",
        },
    )


async def _update_contract_asset_state(
    conn: AsyncConnection,
    *,
    contract_id: UUID,
    status: str,
    service_objective_id: UUID | None = None,
    fulfillment_summary: str | None = None,
) -> None:
    asset_rows = (
        await conn.execute(
            sa.select(market_assets.c.asset_id, market_assets.c.metadata_json)
        )
    ).fetchall()
    for asset_row in asset_rows:
        metadata = dict(asset_row.metadata_json or {})
        if metadata.get("contract_id") != str(contract_id):
            continue
        metadata["contract_status"] = status
        if service_objective_id is not None:
            metadata["service_objective_id"] = str(service_objective_id)
        if fulfillment_summary:
            metadata["fulfillment_summary"] = fulfillment_summary

        values: dict[str, Any] = {"metadata_json": metadata}
        if status == "fulfilled":
            metadata["asset_class"] = "service_artifact"
            values["title"] = f"Service Artifact: {metadata.get('template_code', 'contract')}"
            values["status"] = "active"
            values["quantity_available"] = 1
        elif status == "refunded":
            values["status"] = "expired"
            values["quantity_available"] = 0
            values["transferable"] = False

        await conn.execute(
            market_assets.update()
            .where(market_assets.c.asset_id == asset_row.asset_id)
            .values(**values)
        )


async def _transfer_pending_contract_obligation(
    conn: AsyncConnection,
    *,
    contract_id: UUID | str,
    new_buyer_id: UUID,
) -> Decimal:
    reservation_id, remaining = await _load_contract_obligation_remaining(conn, contract_id)
    if reservation_id is not None and remaining > 0:
        await conn.execute(
            market_reservations.update()
            .where(market_reservations.c.reservation_id == reservation_id)
            .values(
                persona_id=new_buyer_id,
                memo=f"Transferred reservation for contract {contract_id}",
            )
        )
    await conn.execute(
        service_contracts.update()
        .where(service_contracts.c.contract_id == UUID(str(contract_id)))
        .values(buyer_persona_id=new_buyer_id)
    )
    return remaining


async def _persona_rows_with_market_balance(conn: AsyncConnection) -> list[Any]:
    reservation_sum = (
        sa.select(
            market_reservations.c.persona_id.label("persona_id"),
            sa.func.coalesce(sa.func.sum(market_reservations.c.remaining_amount), Decimal("0")).label("reserved"),
        )
        .where(market_reservations.c.status == STATUS_OPEN)
        .group_by(market_reservations.c.persona_id)
        .subquery()
    )
    rows = (
        await conn.execute(
            sa.select(
                agent_personas.c.persona_id,
                agent_personas.c.persona_name,
                agent_personas.c.role_class,
                agent_personas.c.reputation_score,
                available_balance_expression(agent_personas.c.persona_id).label("available_balance"),
                sa.func.coalesce(reservation_sum.c.reserved, Decimal("0")).label("reserved_balance"),
            )
            .outerjoin(
                reservation_sum,
                reservation_sum.c.persona_id == agent_personas.c.persona_id,
            )
            .where(
                agent_personas.c.status == "active",
                agent_personas.c.role_class != "system",  # Exclude welfare/fee pool personas
            )
            .order_by(available_balance_expression(agent_personas.c.persona_id).desc())
        )
    ).fetchall()
    return rows


async def _record_market_action(
    conn: AsyncConnection,
    *,
    settings: NexusSettings,
    persona_id: UUID,
    persona_name: str,
    objective_id: UUID,
    objective_title: str,
    action_type: str,
    action_payload: dict[str, Any],
    spawn_reason: str,
    detail_summary: str,
) -> UUID:
    system_prompt, user_prompt = PromptBuilder.build_market_action_prompt(
        persona_name=persona_name,
        objective_title=objective_title,
        action_type=action_type,
        action_context=detail_summary,
    )
    response_json = json.dumps(action_payload, sort_keys=True)
    ResponseParser.parse_market_action(response_json, strict=True)
    now = _now()
    prompt_hash = hashlib.sha256(f"{system_prompt}\n{user_prompt}".encode("utf-8")).hexdigest()
    tokens_input = max(len(user_prompt) // 4, 1)
    tokens_output = max(len(response_json) // 4, 1)
    cost_total = _money(settings.MARKET_ACTION_COST_USD)

    result = await conn.execute(
        agent_instances.insert()
        .values(
            persona_id=persona_id,
            objective_id=objective_id,
            spawn_reason=spawn_reason,
            input_prompt=user_prompt,
            output_content=response_json,
            thinking_content="deterministic_market_heuristic",
            started_at=now,
            completed_at=now,
            last_heartbeat=now,
            status="completed",
            retry_count=0,
            tokens_input=tokens_input,
            tokens_thinking=0,
            tokens_output=tokens_output,
            cost_usd=cost_total,
            latency_ms=0,
        )
        .returning(agent_instances.c.instance_id)
    )
    instance_id = result.scalar_one()
    await conn.execute(
        agent_telemetry.insert().values(
            instance_id=instance_id,
            persona_id=persona_id,
            objective_id=objective_id,
            api_call_timestamp=now,
            prompt_hash=prompt_hash,
            tokens_input=tokens_input,
            tokens_thinking=0,
            tokens_output=tokens_output,
            cost_input_usd=Decimal("0.000000"),
            cost_thinking_usd=Decimal("0.000000"),
            cost_output_usd=cost_total,
            cost_total_usd=cost_total,
            latency_ms=0,
            http_status=200,
            success=True,
            model_id="market-heuristic-v1",
        )
    )
    await emit_event(
        conn,
        "agent_spawned",
        entity_id=instance_id,
        entity_type="instance",
        payload={"persona": persona_name, "objective": objective_title},
    )
    await emit_event(
        conn,
        "agent_completed",
        entity_id=instance_id,
        entity_type="instance",
        payload={"persona": persona_name, "objective": objective_title, "cost": str(cost_total)},
    )
    return instance_id


async def _check_supply_cap(
    conn: AsyncConnection,
    template_id: UUID,
    cycle_tick: int,
    max_crafts: int | None,
) -> bool:
    """Check if the template's supply cap for this cycle has been reached.

    Returns True if crafting is allowed, False if cap exceeded.
    """
    if max_crafts is None or cycle_tick <= 0:
        return True  # No cap or no cycle tracking

    from nexus_core.models.citation import template_craft_cycle_counts

    result = await conn.execute(
        sa.select(template_craft_cycle_counts.c.craft_count)
        .where(
            template_craft_cycle_counts.c.template_id == template_id,
            template_craft_cycle_counts.c.cycle_tick == cycle_tick,
        )
    )
    row = result.one_or_none()
    if row is None:
        return True  # No crafts yet this cycle
    return row.craft_count < max_crafts


async def _increment_craft_count(
    conn: AsyncConnection,
    template_id: UUID,
    cycle_tick: int,
) -> None:
    """Increment the craft count for a template in the current cycle."""
    if cycle_tick <= 0:
        return

    from nexus_core.models.citation import template_craft_cycle_counts

    # Try UPDATE first, then INSERT if no row exists
    result = await conn.execute(
        template_craft_cycle_counts.update()
        .where(
            template_craft_cycle_counts.c.template_id == template_id,
            template_craft_cycle_counts.c.cycle_tick == cycle_tick,
        )
        .values(craft_count=template_craft_cycle_counts.c.craft_count + 1)
    )
    if result.rowcount == 0:
        await conn.execute(
            template_craft_cycle_counts.insert().values(
                template_id=template_id,
                cycle_tick=cycle_tick,
                craft_count=1,
            )
        )


async def maybe_create_listings(
    conn: AsyncConnection,
    *,
    settings: NexusSettings,
    objective_id: UUID,
    cycle_tick: int = 0,
) -> int:
    templates = await _load_template_map(conn)
    personas = sorted(
        await _persona_rows_with_market_balance(conn),
        key=lambda row: _distressed_listing_sort_key(row, settings),
    )
    created = 0
    max_created = _max_market_listings_per_cycle(len(personas), settings)

    for persona in personas:
        active_listing_count = await _active_listing_count_for_persona(conn, persona.persona_id)
        if active_listing_count >= settings.MARKET_MAX_LISTINGS_PER_PERSONA:
            continue

        template = _select_template_for_persona(
            persona_row=persona,
            templates=templates,
            settings=settings,
        )
        if template is None:
            continue

        # Supply cap check
        max_crafts = getattr(template, "max_crafts_per_cycle", None)
        if not await _check_supply_cap(conn, template.template_id, cycle_tick, max_crafts):
            continue

        distressed = _is_distressed_balance(_money(persona.available_balance), settings)
        craft_cost = _money(template.craft_cost)
        effective_craft_cost = Decimal("0.00") if distressed else craft_cost
        if effective_craft_cost > 0 and _money(persona.available_balance) <= effective_craft_cost:
            continue

        price = _compute_listing_price(
            template_row=template,
            reputation_score=persona.reputation_score,
            distressed=distressed,
            secondary=False,
            contract_asset=False,
        )
        quantity = int(template.default_quantity or 1)
        asset_id = await _insert_market_asset(
            conn,
            template_id=template.template_id,
            owner_persona_id=persona.persona_id,
            crafted_by_persona_id=persona.persona_id,
            asset_kind=template.listing_kind,
            title=f"{template.title} by {persona.persona_name}",
            description=template.description,
            quantity_available=quantity,
            metadata_json={
                "template_code": template.template_code,
                "seller_role_class": persona.role_class,
                "crafted_with_excess_credits": not distressed,
                "distress_inventory": distressed,
                "sale_channel": "primary_market",
                "reference_price": str(price),
                "deferred_craft_cost": str(craft_cost) if distressed and craft_cost > 0 else None,
            },
        )
        listing_id = await _insert_market_listing(
            conn,
            asset_id=asset_id,
            seller_persona_id=persona.persona_id,
            template_id=template.template_id,
            listing_kind=template.listing_kind,
            price=price,
            quantity_available=quantity,
            audience=["all_agents"],
            description=template.description,
            metadata_json={
                "template_code": template.template_code,
                "category": (template.metadata_json or {}).get("category"),
                "sale_channel": "primary_market",
                "distress_inventory": distressed,
            },
        )
        if effective_craft_cost > 0:
            await _transfer_credits(
                conn,
                from_persona_id=persona.persona_id,
                to_persona_id=None,
                amount=effective_craft_cost,
                transaction_type="market_crafting",
                memo=f"Crafted listing from template {template.template_code}",
                reference_objective_id=objective_id,
            )
        await _record_market_action(
            conn,
            settings=settings,
            persona_id=persona.persona_id,
            persona_name=persona.persona_name,
            objective_id=objective_id,
            objective_title=MARKET_OBJECTIVES["marketplace"]["title"],
            action_type="craft_listing",
            action_payload={
                "action_type": "craft_listing",
                "persona_id": str(persona.persona_id),
                "template_code": template.template_code,
                "listing_kind": template.listing_kind,
                "price": float(price),
                "quantity": quantity,
                "details": {
                    "listing_id": str(listing_id),
                    "asset_id": str(asset_id),
                    "distress_inventory": distressed,
                },
            },
            spawn_reason="market_listing_decision",
            detail_summary=f"Craft listing {template.template_code} for {price} credits.",
        )
        await _increment_craft_count(conn, template.template_id, cycle_tick)
        await emit_event(
            conn,
            "market_asset_crafted",
            entity_id=asset_id,
            entity_type="market_asset",
            payload={"seller_persona_id": str(persona.persona_id), "template_code": template.template_code},
        )
        await emit_event(
            conn,
            "market_listing_created",
            entity_id=listing_id,
            entity_type="listing",
            payload={
                "seller_persona_id": str(persona.persona_id),
                "seller_name": persona.persona_name,
                "template_code": template.template_code,
                "listing_kind": template.listing_kind,
                "price": str(price),
                "sale_channel": "primary_market",
                "distress_inventory": distressed,
            },
        )
        created += 1
        if created >= max_created:
            break

    return created


async def maybe_relist_owned_assets(
    conn: AsyncConnection,
    *,
    settings: NexusSettings,
    objective_id: UUID,
) -> int:
    active_listing_assets = (
        sa.select(marketplace_listings.c.asset_id)
        .where(marketplace_listings.c.status == "active")
        .subquery()
    )
    assets = (
        await conn.execute(
            sa.select(
                market_assets,
                market_templates.c.template_code,
                market_templates.c.title.label("template_title"),
                market_templates.c.default_price,
                agent_personas.c.persona_name,
                agent_personas.c.role_class,
                agent_personas.c.reputation_score,
                available_balance_expression(agent_personas.c.persona_id).label("available_balance"),
            )
            .join(market_templates, market_assets.c.template_id == market_templates.c.template_id)
            .join(agent_personas, market_assets.c.owner_persona_id == agent_personas.c.persona_id)
            .outerjoin(active_listing_assets, active_listing_assets.c.asset_id == market_assets.c.asset_id)
            .where(
                market_assets.c.status == "active",
                market_assets.c.transferable.is_(True),
                market_assets.c.quantity_available > 0,
                agent_personas.c.status == "active",
                active_listing_assets.c.asset_id.is_(None),
            )
        )
    ).fetchall()

    candidates: list[tuple[tuple[int, int, Decimal, datetime], Any, dict[str, Any]]] = []
    for row in assets:
        metadata = dict(row.metadata_json or {})
        if not _is_secondary_asset(metadata):
            continue
        if metadata.get("asset_class") == "contract_right" and metadata.get("contract_status") not in {
            "pending_fulfillment",
            "fulfilled",
        }:
            continue
        candidates.append(
            (
                (
                    0 if metadata.get("asset_class") == "contract_right" else 1,
                    0 if _is_distressed_balance(_money(row.available_balance), settings) else 1,
                    _money(row.available_balance),
                    row.created_at,
                ),
                row,
                metadata,
            )
        )

    created = 0
    max_created = _max_market_listings_per_cycle(len(candidates), settings)
    listing_counts: dict[UUID, int] = {}

    for _, row, metadata in sorted(candidates, key=lambda item: item[0]):
        owner_id = row.owner_persona_id
        active_listing_count = listing_counts.get(owner_id)
        if active_listing_count is None:
            active_listing_count = await _active_listing_count_for_persona(conn, owner_id)
        if active_listing_count >= settings.MARKET_MAX_LISTINGS_PER_PERSONA:
            continue

        distressed = _is_distressed_balance(_money(row.available_balance), settings)
        contract_asset = metadata.get("asset_class") == "contract_right"
        price = _compute_listing_price(
            template_row=row,
            reputation_score=row.reputation_score,
            distressed=distressed,
            secondary=True,
            contract_asset=contract_asset,
            asset_metadata=metadata,
        )
        description = row.description
        if contract_asset and metadata.get("contract_status") == "pending_fulfillment":
            description = (
                f"Transferable contract right for {row.template_title}. "
                "Buyer assumes the reserved escrow obligation and receives the service outcome."
            )

        listing_id = await _insert_market_listing(
            conn,
            asset_id=row.asset_id,
            seller_persona_id=owner_id,
            template_id=row.template_id,
            listing_kind=row.asset_kind,
            price=price,
            quantity_available=int(row.quantity_available or 1),
            description=description,
            metadata_json={
                "template_code": row.template_code,
                "category": metadata.get("category"),
                "sale_channel": "secondary_market",
                "asset_class": metadata.get("asset_class"),
                "contract_id": metadata.get("contract_id"),
                "contract_status": metadata.get("contract_status"),
            },
        )
        listing_counts[owner_id] = active_listing_count + 1

        await _record_market_action(
            conn,
            settings=settings,
            persona_id=owner_id,
            persona_name=row.persona_name,
            objective_id=objective_id,
            objective_title=MARKET_OBJECTIVES["marketplace"]["title"],
            action_type="relist_asset",
            action_payload={
                "action_type": "relist_asset",
                "persona_id": str(owner_id),
                "listing_id": str(listing_id),
                "listing_kind": row.asset_kind,
                "price": float(price),
                "quantity": int(row.quantity_available or 1),
                "details": {
                    "asset_id": str(row.asset_id),
                    "asset_class": metadata.get("asset_class"),
                    "sale_channel": "secondary_market",
                },
            },
            spawn_reason="market_relisting_decision",
            detail_summary=f"Relist owned asset {row.template_code} for {price} credits.",
        )
        await emit_event(
            conn,
            "market_listing_created",
            entity_id=listing_id,
            entity_type="listing",
            payload={
                "seller_persona_id": str(owner_id),
                "seller_name": row.persona_name,
                "template_code": row.template_code,
                "listing_kind": row.asset_kind,
                "price": str(price),
                "sale_channel": "secondary_market",
                "asset_class": metadata.get("asset_class"),
            },
        )
        created += 1
        if created >= max_created:
            break

    return created


async def _decrement_listing_inventory(
    conn: AsyncConnection,
    listing_row: Any,
    *,
    consume_asset: bool = True,
) -> None:
    new_quantity = max(int(listing_row.quantity_available or 1) - 1, 0)
    listing_status = "sold_out" if new_quantity <= 0 else "active"
    await conn.execute(
        marketplace_listings.update()
        .where(marketplace_listings.c.listing_id == listing_row.listing_id)
        .values(quantity_available=new_quantity, status=listing_status)
    )
    if consume_asset:
        await conn.execute(
            market_assets.update()
            .where(market_assets.c.asset_id == listing_row.asset_id)
            .values(quantity_available=new_quantity, status=("consumed" if new_quantity <= 0 else "active"))
        )


async def _select_contract_target(conn: AsyncConnection) -> tuple[UUID | None, UUID | None]:
    objective = (
        await conn.execute(
            sa.select(objectives.c.objective_id)
            .where(
                objectives.c.objective_type != "market",
                objectives.c.status.in_(["proposed", "approved", "active", "revision_requested", "synthesizing"]),
            )
            .order_by(objectives.c.priority.desc(), objectives.c.created_at.asc())
            .limit(1)
        )
    ).first()
    if objective is not None:
        return objective.objective_id, None

    finding = (
        await conn.execute(
            sa.select(findings.c.finding_id)
            .order_by(findings.c.created_at.desc())
            .limit(1)
        )
    ).first()
    return None, (finding.finding_id if finding is not None else None)


async def _clone_asset_to_buyer(
    conn: AsyncConnection,
    *,
    template_row: Any,
    buyer_id: UUID,
    seller_id: UUID,
    title_suffix: str,
    reference_price: Decimal | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> UUID:
    template_title = getattr(template_row, "template_title", getattr(template_row, "title", "Market Asset"))
    result = await conn.execute(
        market_assets.insert().values(
            template_id=template_row.template_id,
            owner_persona_id=buyer_id,
            crafted_by_persona_id=seller_id,
            asset_kind=template_row.listing_kind,
            title=f"{template_title} {title_suffix}",
            description=template_row.description,
            quantity_available=1,
            transferable=True,
            metadata_json={
                "template_code": template_row.template_code,
                "acquired_from_market": True,
                "sale_channel": "secondary_market",
                "reference_price": str(_money(reference_price or getattr(template_row, "price", Decimal("0.00")))),
                **(extra_metadata or {}),
            },
        ).returning(market_assets.c.asset_id)
    )
    return result.scalar_one()


async def _complete_secondary_sale(
    conn: AsyncConnection,
    *,
    buyer: Any,
    listing_row: Any,
    sale_price: Decimal,
    reservation_id: UUID,
    objective_id: UUID,
) -> UUID:
    asset_metadata = dict(listing_row.asset_metadata_json or {})
    transfer_contract_id = asset_metadata.get("contract_id")
    obligation_remaining = Decimal("0.00")
    if asset_metadata.get("asset_class") == "contract_right" and transfer_contract_id:
        obligation_remaining = await _transfer_pending_contract_obligation(
            conn,
            contract_id=transfer_contract_id,
            new_buyer_id=buyer.persona_id,
        )

    contract_result = await conn.execute(
        service_contracts.insert()
        .values(
            listing_id=listing_row.listing_id,
            buyer_persona_id=buyer.persona_id,
            seller_persona_id=listing_row.seller_persona_id,
            reservation_id=reservation_id,
            status="completed",
            agreed_price=sale_price,
            quantity=1,
            service_payload={
                "template_code": listing_row.template_code,
                "asset_trade": True,
                "sale_channel": "secondary_market",
                "transfer_contract_id": transfer_contract_id,
                "obligation_remaining": str(obligation_remaining),
            },
            fulfilled_at=_now(),
            fulfillment_summary="Secondary market transfer completed.",
        )
        .returning(service_contracts.c.contract_id)
    )
    receipt_contract_id = contract_result.scalar_one()

    await _close_listing(conn, listing_id=listing_row.listing_id, status="transferred")
    asset_updates = {
        "acquired_from_market": True,
        "sale_channel": "secondary_market",
        "reference_price": str(sale_price),
        "last_sale_price": str(sale_price),
        "last_buyer_persona_id": str(buyer.persona_id),
    }
    if transfer_contract_id:
        asset_updates["contract_status"] = "pending_fulfillment"
        asset_updates["reservation_remaining"] = str(obligation_remaining)
    await _transfer_asset_to_buyer(
        conn,
        asset_id=listing_row.asset_id,
        buyer_id=buyer.persona_id,
        metadata_updates=asset_updates,
    )
    await _transfer_credits(
        conn,
        from_persona_id=buyer.persona_id,
        to_persona_id=listing_row.seller_persona_id,
        amount=sale_price,
        transaction_type="market_purchase",
        memo=f"Secondary purchase of {listing_row.template_code}",
        reference_objective_id=objective_id,
    )
    await consume_reservation(conn, reservation_id)
    await _apply_market_reputation_adjustment(
        conn,
        persona_id=listing_row.seller_persona_id,
        outcome="secondary_sale",
        context=f"secondary_sale:{listing_row.template_code}",
        secondary=True,
    )
    if transfer_contract_id:
        await emit_event(
            conn,
            "market_contract_transferred",
            entity_id=UUID(str(transfer_contract_id)),
            entity_type="contract",
            payload={
                "contract_id": str(transfer_contract_id),
                "new_buyer_persona_id": str(buyer.persona_id),
                "seller_persona_id": str(listing_row.seller_persona_id),
                "sale_price": str(sale_price),
            },
        )
    return receipt_contract_id


async def maybe_submit_purchases(
    conn: AsyncConnection,
    *,
    settings: NexusSettings,
    objective_id: UUID,
) -> int:
    personas = await _persona_rows_with_market_balance(conn)
    seller_map = {row.persona_id: row for row in personas}
    listings = (
        await conn.execute(
            sa.select(
                marketplace_listings,
                market_assets.c.metadata_json.label("asset_metadata_json"),
                market_assets.c.title.label("asset_title"),
                market_assets.c.description.label("asset_description"),
                market_templates.c.template_code,
                market_templates.c.title.label("template_title"),
                market_templates.c.fulfillment_mode,
                market_templates.c.settlement_hook,
                market_templates.c.default_price,
            )
            .join(market_assets, marketplace_listings.c.asset_id == market_assets.c.asset_id)
            .join(market_templates, marketplace_listings.c.template_id == market_templates.c.template_id)
            .where(
                marketplace_listings.c.status == "active",
                marketplace_listings.c.quantity_available > 0,
            )
            .order_by(marketplace_listings.c.created_at.asc())
        )
    ).fetchall()
    purchases = 0
    max_purchases = max(3, min(len(personas), 6))

    for buyer in sorted(personas, key=lambda row: _money(row.available_balance), reverse=True):
        available = _money(buyer.available_balance)
        if available < Decimal("15.00"):
            continue
        affordable_candidates = [
            listing
            for listing in listings
            if listing.seller_persona_id != buyer.persona_id
            and _money(listing.price) <= available
        ]
        if not affordable_candidates:
            continue

        candidate = None
        for listing in sorted(
            affordable_candidates,
            key=lambda row: _purchase_candidate_sort_key(
                listing=row,
                seller_row=seller_map.get(row.seller_persona_id),
                settings=settings,
            ),
        ):
            asset_metadata = dict(listing.asset_metadata_json or {})
            if asset_metadata.get("asset_class") == "contract_right" and asset_metadata.get("contract_id"):
                _, obligation_remaining = await _load_contract_obligation_remaining(
                    conn,
                    asset_metadata.get("contract_id"),
                )
                if available < _money(_money(listing.price) + obligation_remaining):
                    continue
            candidate = listing
            break
        if candidate is None:
            continue

        reservation_id = await create_reservation(
            conn,
            persona_id=buyer.persona_id,
            amount=_money(candidate.price),
            reservation_type="escrow" if candidate.listing_kind in SERVICE_LISTING_KINDS else "purchase_hold",
            listing_id=candidate.listing_id,
            memo=f"Purchase reservation for {candidate.template_code}",
        )
        if reservation_id is None:
            continue

        target_objective_id: UUID | None = None
        target_finding_id: UUID | None = None
        secondary_sale = _is_immediate_secondary_sale(candidate)
        if secondary_sale:
            contract_id = await _complete_secondary_sale(
                conn,
                buyer=buyer,
                listing_row=candidate,
                sale_price=_money(candidate.price),
                reservation_id=reservation_id,
                objective_id=objective_id,
            )
        else:
            if candidate.listing_kind in SERVICE_LISTING_KINDS:
                target_objective_id, target_finding_id = await _select_contract_target(conn)
            contract_status = "pending_fulfillment" if candidate.listing_kind in SERVICE_LISTING_KINDS else "completed"
            contract_result = await conn.execute(
                service_contracts.insert()
                .values(
                    listing_id=candidate.listing_id,
                    buyer_persona_id=buyer.persona_id,
                    seller_persona_id=candidate.seller_persona_id,
                    reservation_id=reservation_id,
                    target_objective_id=target_objective_id,
                    target_finding_id=target_finding_id,
                    status=contract_status,
                    agreed_price=_money(candidate.price),
                    quantity=1,
                    service_payload={
                        "template_code": candidate.template_code,
                        "target_objective_id": (str(target_objective_id) if target_objective_id else None),
                        "target_finding_id": (str(target_finding_id) if target_finding_id else None),
                    },
                    expires_at=_now() + timedelta(minutes=settings.MARKET_SERVICE_TIMEOUT_MINS),
                )
                .returning(service_contracts.c.contract_id)
            )
            contract_id = contract_result.scalar_one()
            await _decrement_listing_inventory(conn, candidate, consume_asset=True)

            if candidate.listing_kind not in SERVICE_LISTING_KINDS:
                await _transfer_credits(
                    conn,
                    from_persona_id=buyer.persona_id,
                    to_persona_id=candidate.seller_persona_id,
                    amount=_money(candidate.price),
                    transaction_type="market_purchase",
                    memo=f"Immediate purchase of {candidate.template_code}",
                    reference_objective_id=objective_id,
                )
                await consume_reservation(conn, reservation_id)
                await _clone_asset_to_buyer(
                    conn,
                    template_row=candidate,
                    buyer_id=buyer.persona_id,
                    seller_id=candidate.seller_persona_id,
                    title_suffix=f"(acquired by {buyer.persona_name})",
                    reference_price=_money(candidate.price),
                )
                await conn.execute(
                    service_contracts.update()
                    .where(service_contracts.c.contract_id == contract_id)
                    .values(
                        status="completed",
                        fulfillment_summary="Immediate market delivery completed.",
                        fulfilled_at=_now(),
                    )
                )
                await _apply_market_reputation_adjustment(
                    conn,
                    persona_id=candidate.seller_persona_id,
                    outcome="completed_sale",
                    context=f"sale:{candidate.template_code}",
                )
            else:
                contract_asset_id = await _create_contract_right_asset(
                    conn,
                    template_row=candidate,
                    contract_id=contract_id,
                    buyer_id=buyer.persona_id,
                    seller_id=candidate.seller_persona_id,
                    agreed_price=_money(candidate.price),
                    reservation_id=reservation_id,
                )
                await conn.execute(
                    service_contracts.update()
                    .where(service_contracts.c.contract_id == contract_id)
                    .values(
                        service_payload={
                            "template_code": candidate.template_code,
                            "target_objective_id": (
                                str(target_objective_id) if target_objective_id else None
                            ),
                            "target_finding_id": str(target_finding_id) if target_finding_id else None,
                            "contract_asset_id": str(contract_asset_id),
                        }
                    )
                )

        await _record_market_action(
            conn,
            settings=settings,
            persona_id=buyer.persona_id,
            persona_name=buyer.persona_name,
            objective_id=objective_id,
            objective_title=MARKET_OBJECTIVES["marketplace"]["title"],
            action_type="purchase_listing",
            action_payload={
                "action_type": "purchase_listing",
                "persona_id": str(buyer.persona_id),
                "listing_id": str(candidate.listing_id),
                "listing_kind": candidate.listing_kind,
                "price": float(_money(candidate.price)),
                "quantity": 1,
                "details": {
                    "contract_id": str(contract_id),
                    "reservation_id": str(reservation_id),
                    "target_objective_id": str(target_objective_id) if target_objective_id else None,
                    "target_finding_id": str(target_finding_id) if target_finding_id else None,
                    "sale_channel": "secondary_market" if secondary_sale else "primary_market",
                },
            },
            spawn_reason="market_purchase_decision",
            detail_summary=f"Purchase listing {candidate.template_code} for {_money(candidate.price)} credits.",
        )
        await emit_event(
            conn,
            "market_purchase_submitted",
            entity_id=contract_id,
            entity_type="contract",
            payload={
                "buyer_persona_id": str(buyer.persona_id),
                "seller_persona_id": str(candidate.seller_persona_id),
                "listing_id": str(candidate.listing_id),
                "listing_kind": candidate.listing_kind,
                "price": str(_money(candidate.price)),
                "sale_channel": "secondary_market" if secondary_sale else "primary_market",
            },
        )
        purchases += 1
        if purchases >= max_purchases:
            break

    return purchases


async def process_service_contracts(
    conn: AsyncConnection,
    *,
    settings: NexusSettings,
) -> tuple[int, int]:
    fulfilled = 0
    refunded = 0
    rows = (
        await conn.execute(
            sa.select(
                service_contracts,
                marketplace_listings.c.asset_id,
                market_templates.c.template_code,
                market_templates.c.title.label("template_title"),
                agent_personas.c.persona_name.label("seller_name"),
            )
            .join(marketplace_listings, service_contracts.c.listing_id == marketplace_listings.c.listing_id)
            .join(market_templates, marketplace_listings.c.template_id == market_templates.c.template_id)
            .join(agent_personas, service_contracts.c.seller_persona_id == agent_personas.c.persona_id)
            .where(service_contracts.c.status == "pending_fulfillment")
            .order_by(service_contracts.c.created_at.asc())
        )
    ).fetchall()
    now = _now()

    for row in rows:
        if row.expires_at is not None and row.expires_at <= now:
            if row.reservation_id:
                await release_reservation(conn, row.reservation_id)
            await conn.execute(
                service_contracts.update()
                .where(service_contracts.c.contract_id == row.contract_id)
                .values(status="refunded", refunded_at=now, fulfillment_summary="Escrow refunded after timeout.")
            )
            await emit_event(
                conn,
                "service_contract_refunded",
                entity_id=row.contract_id,
                entity_type="contract",
                payload={"seller_persona_id": str(row.seller_persona_id), "buyer_persona_id": str(row.buyer_persona_id)},
            )
            await _update_contract_asset_state(conn, contract_id=row.contract_id, status="refunded")
            await _apply_market_reputation_adjustment(
                conn,
                persona_id=row.seller_persona_id,
                outcome="refunded_service",
                context=f"refund:{row.template_code}",
                service=True,
            )
            refunded += 1
            continue

        service_title = f"Service Contract: {row.template_title}"
        if row.target_objective_id:
            service_title = f"{service_title} for objective {str(row.target_objective_id)[:8]}"
        elif row.target_finding_id:
            service_title = f"{service_title} for finding {str(row.target_finding_id)[:8]}"

        objective_result = await conn.execute(
            objectives.insert()
            .values(
                title=service_title,
                description=(
                    "Explicit bounded market service request generated from a contract. "
                    "This objective exists solely to make the service leg observable."
                ),
                objective_type="market",
                impact_level="routine",
                priority=4,
                status="completed",
                proposed_by_type="system",
                approved_by_type="system",
                acceptance_criteria=(
                    "Provide the contracted service artifact without mutating unrelated queues or priorities."
                ),
                compute_budget_allocated=Decimal("0.00"),
                output_type="market_service",
                completed_at=now,
            )
            .returning(objectives.c.objective_id)
        )
        service_objective_id = objective_result.scalar_one()
        summary = (
            f"Fulfilled {row.template_code} contract for buyer {str(row.buyer_persona_id)[:8]} "
            "against explicit target linkage."
        )
        await _record_market_action(
            conn,
            settings=settings,
            persona_id=row.seller_persona_id,
            persona_name=row.seller_name,
            objective_id=service_objective_id,
            objective_title=service_title,
            action_type="fulfill_service",
            action_payload={
                "action_type": "fulfill_service",
                "persona_id": str(row.seller_persona_id),
                "contract_id": str(row.contract_id),
                "listing_kind": "hard_service",
                "price": float(_money(row.agreed_price)),
                "quantity": int(row.quantity or 1),
                "details": {
                    "service_objective_id": str(service_objective_id),
                    "target_objective_id": str(row.target_objective_id) if row.target_objective_id else None,
                    "target_finding_id": str(row.target_finding_id) if row.target_finding_id else None,
                },
            },
            spawn_reason="market_service_fulfillment",
            detail_summary=summary,
        )
        await _transfer_credits(
            conn,
            from_persona_id=row.buyer_persona_id,
            to_persona_id=row.seller_persona_id,
            amount=_money(row.agreed_price),
            transaction_type="service_settlement",
            memo=f"Fulfilled service contract {row.template_code}",
            reference_objective_id=service_objective_id,
            reference_finding_id=row.target_finding_id,
        )
        if row.reservation_id:
            await consume_reservation(conn, row.reservation_id)
        await conn.execute(
            service_contracts.update()
            .where(service_contracts.c.contract_id == row.contract_id)
            .values(
                status="fulfilled",
                service_objective_id=service_objective_id,
                fulfillment_summary=summary,
                fulfilled_at=now,
            )
        )
        await _update_contract_asset_state(
            conn,
            contract_id=row.contract_id,
            status="fulfilled",
            service_objective_id=service_objective_id,
            fulfillment_summary=summary,
        )
        await _apply_market_reputation_adjustment(
            conn,
            persona_id=row.seller_persona_id,
            outcome="fulfilled_service",
            context=f"fulfillment:{row.template_code}",
            service=True,
        )
        await emit_event(
            conn,
            "service_contract_fulfilled",
            entity_id=row.contract_id,
            entity_type="contract",
            payload={
                "seller_persona_id": str(row.seller_persona_id),
                "buyer_persona_id": str(row.buyer_persona_id),
                "service_objective_id": str(service_objective_id),
                "target_objective_id": str(row.target_objective_id) if row.target_objective_id else None,
                "target_finding_id": str(row.target_finding_id) if row.target_finding_id else None,
            },
        )
        fulfilled += 1

    return fulfilled, refunded


def _status_mark(status: str) -> Decimal:
    mapping = {
        "completed": Decimal("90.00"),
        "validated": Decimal("90.00"),
        "active": Decimal("60.00"),
        "approved": Decimal("55.00"),
        "pending_review": Decimal("55.00"),
        "proposed": Decimal("50.00"),
        "revision_requested": Decimal("40.00"),
        "failed": Decimal("10.00"),
        "rejected": Decimal("10.00"),
        "escalated": Decimal("10.00"),
    }
    return mapping.get(status, Decimal("50.00"))


async def ensure_market_instruments(conn: AsyncConnection) -> int:
    """Create objective, finding, and persona performance notes when missing."""
    existing = (
        await conn.execute(
            sa.select(
                market_instruments.c.family,
                market_instruments.c.underlying_objective_id,
                market_instruments.c.underlying_finding_id,
                market_instruments.c.underlying_persona_id,
            )
        )
    ).fetchall()
    existing_objectives = {row.underlying_objective_id for row in existing if row.family == "objective_note"}
    existing_findings = {row.underlying_finding_id for row in existing if row.family == "finding_note"}
    existing_personas = {row.underlying_persona_id for row in existing if row.family == "persona_performance_note"}
    created = 0
    now = _now()

    objective_rows = (
        await conn.execute(
            sa.select(
                objectives.c.objective_id,
                objectives.c.title,
                objectives.c.status,
            )
            .where(objectives.c.objective_type != "market")
            .order_by(objectives.c.priority.desc(), objectives.c.created_at.desc())
            .limit(3)
        )
    ).fetchall()
    for row in objective_rows:
        if row.objective_id in existing_objectives:
            continue
        symbol = f"OBJ-{str(row.objective_id)[:6].upper()}"
        await conn.execute(
            market_instruments.insert().values(
                symbol=symbol,
                name=f"Objective Note: {row.title[:120]}",
                family="objective_note",
                underlying_objective_id=row.objective_id,
                risk_tier="standard",
                settlement_status="open",
                last_trade_price=_status_mark(row.status),
                mark_price=_status_mark(row.status),
                expiry_at=now + timedelta(hours=12),
                settlement_at=now + timedelta(hours=12),
                metadata_json={"status_at_issue": row.status},
            )
        )
        await emit_event(
            conn,
            "security_instrument_created",
            entity_id=row.objective_id,
            entity_type="objective",
            payload={"symbol": symbol, "family": "objective_note"},
        )
        created += 1

    finding_rows = (
        await conn.execute(
            sa.select(
                findings.c.finding_id,
                findings.c.title,
                findings.c.status,
            )
            .order_by(findings.c.created_at.desc())
            .limit(3)
        )
    ).fetchall()
    for row in finding_rows:
        if row.finding_id in existing_findings:
            continue
        symbol = f"FND-{str(row.finding_id)[:6].upper()}"
        await conn.execute(
            market_instruments.insert().values(
                symbol=symbol,
                name=f"Finding Note: {row.title[:120]}",
                family="finding_note",
                underlying_finding_id=row.finding_id,
                risk_tier="standard",
                settlement_status="open",
                last_trade_price=_status_mark(row.status),
                mark_price=_status_mark(row.status),
                expiry_at=now + timedelta(hours=12),
                settlement_at=now + timedelta(hours=12),
                metadata_json={"status_at_issue": row.status},
            )
        )
        await emit_event(
            conn,
            "security_instrument_created",
            entity_id=row.finding_id,
            entity_type="finding",
            payload={"symbol": symbol, "family": "finding_note"},
        )
        created += 1

    persona_rows = await _persona_rows_with_market_balance(conn)
    persona_candidates: list[Any] = []
    seen_persona_ids: set[UUID] = set()
    if persona_rows:
        persona_candidates.append(max(persona_rows, key=lambda row: _money(row.available_balance)))
        persona_candidates.append(min(persona_rows, key=lambda row: _money(row.available_balance)))
        persona_candidates.append(max(persona_rows, key=lambda row: Decimal(str(row.reputation_score or 0))))
        market_maker = next(
            (row for row in persona_rows if _risk_tier_for_role(row.role_class) in {"market_maker", "governor"}),
            None,
        )
        if market_maker is not None:
            persona_candidates.append(market_maker)

    for row in persona_candidates:
        if row.persona_id in seen_persona_ids:
            continue
        seen_persona_ids.add(row.persona_id)
        if row.persona_id in existing_personas:
            continue
        symbol = f"PER-{str(row.persona_id)[:6].upper()}"
        await conn.execute(
            market_instruments.insert().values(
                symbol=symbol,
                name=f"Persona Performance Note: {row.persona_name}",
                family="persona_performance_note",
                underlying_persona_id=row.persona_id,
                risk_tier=_risk_tier_for_role(row.role_class),
                settlement_status="open",
                last_trade_price=Decimal("50.00"),
                mark_price=Decimal("50.00"),
                expiry_at=now + timedelta(hours=12),
                settlement_at=now + timedelta(hours=12),
                metadata_json={
                    "baseline_balance": str(_money(row.available_balance)),
                    "baseline_reputation": str(row.reputation_score or 0),
                },
            )
        )
        await emit_event(
            conn,
            "security_instrument_created",
            entity_id=row.persona_id,
            entity_type="persona",
            payload={"symbol": symbol, "family": "persona_performance_note"},
        )
        created += 1

    return created


async def _current_position_quantity(
    conn: AsyncConnection,
    *,
    instrument_id: UUID,
    persona_id: UUID,
) -> Decimal:
    row = (
        await conn.execute(
            sa.select(market_positions.c.net_quantity).where(
                market_positions.c.instrument_id == instrument_id,
                market_positions.c.persona_id == persona_id,
            )
        )
    ).first()
    return _qty(row.net_quantity if row is not None else Decimal("0.0000"))


async def _open_sell_commitment(
    conn: AsyncConnection,
    *,
    instrument_id: UUID,
    persona_id: UUID,
) -> Decimal:
    quantity = await conn.scalar(
        sa.select(
            sa.func.coalesce(
                sa.func.sum(market_orders.c.quantity - market_orders.c.filled_quantity),
                Decimal("0"),
            )
        ).where(
            market_orders.c.instrument_id == instrument_id,
            market_orders.c.persona_id == persona_id,
            market_orders.c.side == "sell",
            market_orders.c.status == STATUS_OPEN,
        )
    )
    return _qty(quantity)


async def place_limit_order(
    conn: AsyncConnection,
    *,
    settings: NexusSettings,
    persona_row: Any,
    instrument_row: Any,
    objective_id: UUID,
    side: str,
    price: Decimal,
    quantity: Decimal,
) -> UUID | None:
    quantity = _qty(quantity)
    price = _money(price)
    if quantity <= 0 or price <= 0 or instrument_row.halted or instrument_row.settlement_status != "open":
        return None

    profile = (
        await conn.execute(
            sa.select(persona_market_profiles).where(
                persona_market_profiles.c.persona_id == persona_row.persona_id
            )
        )
    ).first()
    if profile is None:
        return None
    open_order_count = int(
        await conn.scalar(
            sa.select(sa.func.count())
            .select_from(market_orders)
            .where(
                market_orders.c.persona_id == persona_row.persona_id,
                market_orders.c.status == STATUS_OPEN,
            )
        )
        or 0
    )
    if open_order_count >= int(profile.max_open_orders):
        return None

    reservation_id: UUID | None = None
    if side == "buy":
        notional = _money(price * quantity)
        position_notional = _money(
            abs(
                await _current_position_quantity(
                    conn,
                    instrument_id=instrument_row.instrument_id,
                    persona_id=persona_row.persona_id,
                )
            )
            * instrument_row.mark_price
        )
        if position_notional + notional > _money(profile.max_position_notional):
            return None
        reservation_id = await create_reservation(
            conn,
            persona_id=persona_row.persona_id,
            amount=notional,
            reservation_type="order_cash",
            instrument_id=instrument_row.instrument_id,
            memo=f"Buy order for {instrument_row.symbol}",
        )
        if reservation_id is None:
            return None
    else:
        current_qty = await _current_position_quantity(
            conn,
            instrument_id=instrument_row.instrument_id,
            persona_id=persona_row.persona_id,
        )
        sell_commitment = await _open_sell_commitment(
            conn,
            instrument_id=instrument_row.instrument_id,
            persona_id=persona_row.persona_id,
        )
        available_long = current_qty - sell_commitment
        shortage = quantity - max(available_long, Decimal("0.0000"))
        if shortage > 0 and profile.risk_tier == "standard":
            return None
        if shortage > 0:
            collateral = _money(shortage * price * Decimal(str(profile.collateral_ratio)))
            reservation_id = await create_reservation(
                conn,
                persona_id=persona_row.persona_id,
                amount=collateral,
                reservation_type="collateral",
                instrument_id=instrument_row.instrument_id,
                memo=f"Short collateral for {instrument_row.symbol}",
            )
            if reservation_id is None:
                return None

    result = await conn.execute(
        market_orders.insert()
        .values(
            instrument_id=instrument_row.instrument_id,
            persona_id=persona_row.persona_id,
            side=side,
            order_type="limit",
            price=price,
            quantity=quantity,
            filled_quantity=Decimal("0.0000"),
            reservation_id=reservation_id,
            risk_tier=profile.risk_tier,
            status=STATUS_OPEN,
        )
        .returning(market_orders.c.order_id)
    )
    order_id = result.scalar_one()
    if reservation_id is not None:
        await conn.execute(
            market_reservations.update()
            .where(market_reservations.c.reservation_id == reservation_id)
            .values(order_id=order_id)
        )

    await _record_market_action(
        conn,
        settings=settings,
        persona_id=persona_row.persona_id,
        persona_name=persona_row.persona_name,
        objective_id=objective_id,
        objective_title=MARKET_OBJECTIVES["securities"]["title"],
        action_type="place_order",
        action_payload={
            "action_type": "place_order",
            "persona_id": str(persona_row.persona_id),
            "instrument_symbol": instrument_row.symbol,
            "side": side,
            "price": float(price),
            "quantity": float(quantity),
            "details": {"order_id": str(order_id), "reservation_id": str(reservation_id) if reservation_id else None},
        },
        spawn_reason="security_trade_decision",
        detail_summary=f"Place {side} order on {instrument_row.symbol} for {quantity} @ {price}.",
    )
    await emit_event(
        conn,
        "security_order_placed",
        entity_id=order_id,
        entity_type="order",
        payload={
            "instrument_id": str(instrument_row.instrument_id),
            "instrument_symbol": instrument_row.symbol,
            "persona_id": str(persona_row.persona_id),
            "side": side,
            "price": str(price),
            "quantity": str(quantity),
        },
    )
    return order_id


async def maybe_place_orders(
    conn: AsyncConnection,
    *,
    settings: NexusSettings,
    objective_id: UUID,
) -> int:
    personas = await _persona_rows_with_market_balance(conn)
    instruments = (
        await conn.execute(
            sa.select(market_instruments)
            .where(
                market_instruments.c.settlement_status == "open",
                market_instruments.c.halted.is_(False),
            )
            .order_by(market_instruments.c.updated_at.desc())
            .limit(4)
        )
    ).fetchall()
    if not personas or not instruments:
        return 0

    placed = 0
    preferred_buyers = [
        row
        for row in personas
        if _money(row.available_balance) >= Decimal("18.00")
        and not _is_distressed_balance(_money(row.available_balance), settings)
        and _risk_tier_for_role(row.role_class) == "standard"
    ]
    supplemental_buyers = [
        row
        for row in personas
        if row.persona_id not in {buyer.persona_id for buyer in preferred_buyers}
        and _money(row.available_balance) >= Decimal("18.00")
        and not _is_distressed_balance(_money(row.available_balance), settings)
    ]
    buyer_candidates = (preferred_buyers + supplemental_buyers)[:4]
    if not buyer_candidates:
        buyer_candidates = [row for row in personas if _money(row.available_balance) >= Decimal("18.00")][:3]

    for instrument in instruments:
        mark = max(_money(instrument.mark_price), Decimal("10.00"))
        buy_price = _money(mark + Decimal("1.00"))
        sell_price = _money(max(mark - Decimal("1.00"), Decimal("1.00")))
        instrument_buyers = buyer_candidates[:2]
        for buyer in instrument_buyers:
            if await place_limit_order(
                conn,
                settings=settings,
                persona_row=buyer,
                instrument_row=instrument,
                objective_id=objective_id,
                side="buy",
                price=buy_price,
                quantity=Decimal("1.0000"),
            ):
                placed += 1

        seller_candidates: list[Any] = []
        for persona in personas:
            if persona.persona_id in {buyer.persona_id for buyer in instrument_buyers}:
                continue
            current_qty = await _current_position_quantity(
                conn,
                instrument_id=instrument.instrument_id,
                persona_id=persona.persona_id,
            )
            if current_qty > 0 or (
                _risk_tier_for_role(persona.role_class) in {"market_maker", "governor"}
                and _money(persona.available_balance) >= Decimal("20.00")
            ):
                seller_candidates.append(persona)
            if len(seller_candidates) >= 2:
                break

        for seller in seller_candidates:
            if await place_limit_order(
                conn,
                settings=settings,
                persona_row=seller,
                instrument_row=instrument,
                objective_id=objective_id,
                side="sell",
                price=sell_price,
                quantity=Decimal("1.0000"),
            ):
                placed += 1
    return placed


async def _upsert_position(
    conn: AsyncConnection,
    *,
    instrument_id: UUID,
    persona_id: UUID,
    delta_qty: Decimal,
    trade_price: Decimal,
    mark_price: Decimal,
) -> Decimal:
    row = (
        await conn.execute(
            sa.select(market_positions).where(
                market_positions.c.instrument_id == instrument_id,
                market_positions.c.persona_id == persona_id,
            )
        )
    ).first()
    current_qty = _qty(row.net_quantity if row is not None else Decimal("0.0000"))
    current_avg = _money(row.average_entry_price if row is not None else Decimal("0.00"))
    new_qty = _qty(current_qty + delta_qty)

    if delta_qty > 0:
        if current_qty >= 0 and new_qty > 0:
            new_avg = _money(((current_qty * current_avg) + (delta_qty * trade_price)) / new_qty)
        elif new_qty > 0:
            new_avg = trade_price
        else:
            new_avg = current_avg
    else:
        if current_qty <= 0 and new_qty < 0:
            new_avg = _money(((abs(current_qty) * current_avg) + (abs(delta_qty) * trade_price)) / abs(new_qty))
        elif new_qty < 0:
            new_avg = trade_price
        else:
            new_avg = current_avg

    market_value = _money(new_qty * mark_price)
    if row is None:
        await conn.execute(
            market_positions.insert().values(
                instrument_id=instrument_id,
                persona_id=persona_id,
                net_quantity=new_qty,
                average_entry_price=new_avg,
                realized_pnl=Decimal("0.00"),
                market_value=market_value,
            )
        )
    else:
        await conn.execute(
            market_positions.update()
            .where(market_positions.c.position_id == row.position_id)
            .values(
                net_quantity=new_qty,
                average_entry_price=new_avg,
                market_value=market_value,
            )
        )
    return new_qty


async def _release_flat_collateral(
    conn: AsyncConnection,
    *,
    instrument_id: UUID,
    persona_id: UUID,
) -> None:
    current_qty = await _current_position_quantity(conn, instrument_id=instrument_id, persona_id=persona_id)
    if current_qty < 0:
        return
    rows = (
        await conn.execute(
            sa.select(market_reservations.c.reservation_id).where(
                market_reservations.c.instrument_id == instrument_id,
                market_reservations.c.persona_id == persona_id,
                market_reservations.c.reservation_type == "collateral",
                market_reservations.c.status == STATUS_OPEN,
            )
        )
    ).fetchall()
    for row in rows:
        await release_reservation(conn, row.reservation_id)


async def _update_order_fill(
    conn: AsyncConnection,
    *,
    order_row: Any,
    fill_qty: Decimal,
) -> None:
    new_filled = _qty(order_row.filled_quantity + fill_qty)
    status = "filled" if new_filled >= _qty(order_row.quantity) else STATUS_OPEN
    await conn.execute(
        market_orders.update()
        .where(market_orders.c.order_id == order_row.order_id)
        .values(filled_quantity=new_filled, status=status, updated_at=_now())
    )


async def _maybe_release_order_reservation(
    conn: AsyncConnection,
    *,
    order_row: Any,
    trade_notional: Decimal,
    seller_new_qty: Decimal | None = None,
) -> None:
    if not order_row.reservation_id:
        return
    if order_row.side == "buy":
        await consume_reservation(conn, order_row.reservation_id, trade_notional)
        refreshed = (
            await conn.execute(
                sa.select(market_orders.c.quantity, market_orders.c.filled_quantity).where(
                    market_orders.c.order_id == order_row.order_id
                )
            )
        ).first()
        if refreshed and _qty(refreshed.filled_quantity) >= _qty(refreshed.quantity):
            await release_reservation(conn, order_row.reservation_id)
    elif seller_new_qty is not None and seller_new_qty >= 0:
        await release_reservation(conn, order_row.reservation_id)


async def match_orders(conn: AsyncConnection) -> int:
    trades_executed = 0
    instruments = (
        await conn.execute(
            sa.select(market_instruments).where(
                market_instruments.c.settlement_status == "open",
                market_instruments.c.halted.is_(False),
            )
        )
    ).fetchall()

    for instrument in instruments:
        while True:
            buy = (
                await conn.execute(
                    sa.select(market_orders)
                    .where(
                        market_orders.c.instrument_id == instrument.instrument_id,
                        market_orders.c.side == "buy",
                        market_orders.c.status == STATUS_OPEN,
                    )
                    .order_by(market_orders.c.price.desc(), market_orders.c.created_at.asc())
                    .limit(1)
                )
            ).first()
            sell = (
                await conn.execute(
                    sa.select(market_orders)
                    .where(
                        market_orders.c.instrument_id == instrument.instrument_id,
                        market_orders.c.side == "sell",
                        market_orders.c.status == STATUS_OPEN,
                    )
                    .order_by(market_orders.c.price.asc(), market_orders.c.created_at.asc())
                    .limit(1)
                )
            ).first()
            if buy is None or sell is None or _money(buy.price) < _money(sell.price):
                break

            buy_remaining = _qty(buy.quantity - buy.filled_quantity)
            sell_remaining = _qty(sell.quantity - sell.filled_quantity)
            trade_qty = min(buy_remaining, sell_remaining)
            if trade_qty <= 0:
                break

            trade_price = _money(buy.price if buy.created_at <= sell.created_at else sell.price)
            trade_notional = _money(trade_price * trade_qty)
            trade_result = await conn.execute(
                market_trades.insert()
                .values(
                    instrument_id=instrument.instrument_id,
                    buy_order_id=buy.order_id,
                    sell_order_id=sell.order_id,
                    buyer_persona_id=buy.persona_id,
                    seller_persona_id=sell.persona_id,
                    price=trade_price,
                    quantity=trade_qty,
                    notional=trade_notional,
                )
                .returning(market_trades.c.trade_id)
            )
            trade_id = trade_result.scalar_one()
            await _transfer_credits(
                conn,
                from_persona_id=buy.persona_id,
                to_persona_id=sell.persona_id,
                amount=trade_notional,
                transaction_type="security_trade_cash",
                memo=f"Trade {instrument.symbol}",
            )

            await _upsert_position(
                conn,
                instrument_id=instrument.instrument_id,
                persona_id=buy.persona_id,
                delta_qty=trade_qty,
                trade_price=trade_price,
                mark_price=trade_price,
            )
            seller_new_qty = await _upsert_position(
                conn,
                instrument_id=instrument.instrument_id,
                persona_id=sell.persona_id,
                delta_qty=-trade_qty,
                trade_price=trade_price,
                mark_price=trade_price,
            )

            await _update_order_fill(conn, order_row=buy, fill_qty=trade_qty)
            await _update_order_fill(conn, order_row=sell, fill_qty=trade_qty)
            await _maybe_release_order_reservation(conn, order_row=buy, trade_notional=trade_notional)
            await _maybe_release_order_reservation(
                conn,
                order_row=sell,
                trade_notional=trade_notional,
                seller_new_qty=seller_new_qty,
            )
            await _release_flat_collateral(
                conn,
                instrument_id=instrument.instrument_id,
                persona_id=sell.persona_id,
            )
            await conn.execute(
                market_instruments.update()
                .where(market_instruments.c.instrument_id == instrument.instrument_id)
                .values(last_trade_price=trade_price, mark_price=trade_price)
            )
            await conn.execute(
                market_price_history.insert().values(
                    instrument_id=instrument.instrument_id,
                    last_trade_price=trade_price,
                    mark_price=trade_price,
                    traded_volume=trade_qty,
                    source="trade",
                )
            )
            await emit_event(
                conn,
                "security_trade_executed",
                entity_id=trade_id,
                entity_type="trade",
                payload={
                    "instrument_symbol": instrument.symbol,
                    "instrument_id": str(instrument.instrument_id),
                    "buyer_persona_id": str(buy.persona_id),
                    "seller_persona_id": str(sell.persona_id),
                    "price": str(trade_price),
                    "quantity": str(trade_qty),
                    "notional": str(trade_notional),
                },
            )

            # Protocol fee: 0.05% from each side → fee pool
            FEE_POOL_ID = UUID("00000000-0000-0000-0000-000000000002")
            fee_per_side = _money(trade_notional * Decimal("0.0005"))
            if fee_per_side > Decimal("0"):
                for side_persona_id in (buy.persona_id, sell.persona_id):
                    side_balance = await get_available_balance(conn, side_persona_id)
                    if side_balance >= fee_per_side:
                        await _transfer_credits(
                            conn,
                            from_persona_id=side_persona_id,
                            to_persona_id=FEE_POOL_ID,
                            amount=fee_per_side,
                            transaction_type="protocol_fee",
                            memo=f"Protocol fee on trade {instrument.symbol}",
                        )

            # Market maker rebate: if passive side has resting order on opposite side
            maker_id = sell.persona_id if buy.created_at <= sell.created_at else buy.persona_id
            maker_opposite_side = "buy" if maker_id == sell.persona_id else "sell"
            has_opposite = await conn.scalar(
                sa.select(sa.func.count()).select_from(market_orders).where(
                    market_orders.c.instrument_id == instrument.instrument_id,
                    market_orders.c.persona_id == maker_id,
                    market_orders.c.side == maker_opposite_side,
                    market_orders.c.status == STATUS_OPEN,
                )
            )
            if has_opposite and has_opposite > 0:
                rebate = _money(trade_notional * Decimal("0.002"))
                fee_pool_balance = await get_available_balance(conn, FEE_POOL_ID)
                if rebate > Decimal("0") and fee_pool_balance >= rebate:
                    await _transfer_credits(
                        conn,
                        from_persona_id=FEE_POOL_ID,
                        to_persona_id=maker_id,
                        amount=rebate,
                        transaction_type="market_maker_rebate",
                        memo=f"MM rebate on trade {instrument.symbol}",
                    )

            trades_executed += 1

    return trades_executed


async def cancel_stale_orders(conn: AsyncConnection) -> int:
    cutoff = _now() - timedelta(minutes=15)
    rows = (
        await conn.execute(
            sa.select(
                market_orders,
                market_instruments.c.settlement_status,
                market_instruments.c.halted,
            )
            .join(market_instruments, market_orders.c.instrument_id == market_instruments.c.instrument_id)
            .where(
                market_orders.c.status == STATUS_OPEN,
                sa.or_(
                    market_orders.c.created_at < cutoff,
                    market_instruments.c.halted.is_(True),
                    market_instruments.c.settlement_status != "open",
                ),
            )
        )
    ).fetchall()
    cancelled = 0
    for row in rows:
        await conn.execute(
            market_orders.update()
            .where(market_orders.c.order_id == row.order_id)
            .values(status="cancelled", cancelled_at=_now())
        )
        if row.reservation_id:
            if row.side == "sell":
                await _release_flat_collateral(
                    conn,
                    instrument_id=row.instrument_id,
                    persona_id=row.persona_id,
                )
            else:
                await release_reservation(conn, row.reservation_id)
        await emit_event(
            conn,
            "security_order_cancelled",
            entity_id=row.order_id,
            entity_type="order",
            payload={"instrument_id": str(row.instrument_id), "persona_id": str(row.persona_id)},
        )
        cancelled += 1
    return cancelled


async def _compute_obi(conn: AsyncConnection, instrument_id) -> Decimal:
    """Compute Order Book Imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol).

    Returns value in [-1.0, +1.0]. Positive = buy pressure, negative = sell pressure.
    Only counts resting orders (older than 30 seconds) to prevent wash-trade manipulation.
    """
    result = await conn.execute(
        sa.select(
            sa.func.coalesce(
                sa.func.sum(
                    sa.case(
                        (market_orders.c.side == "buy",
                         market_orders.c.quantity - market_orders.c.filled_quantity),
                        else_=Decimal("0"),
                    )
                ),
                Decimal("0"),
            ).label("bid_vol"),
            sa.func.coalesce(
                sa.func.sum(
                    sa.case(
                        (market_orders.c.side == "sell",
                         market_orders.c.quantity - market_orders.c.filled_quantity),
                        else_=Decimal("0"),
                    )
                ),
                Decimal("0"),
            ).label("ask_vol"),
        ).where(
            market_orders.c.instrument_id == instrument_id,
            market_orders.c.status == STATUS_OPEN,
            market_orders.c.created_at <= sa.func.now() - sa.text("INTERVAL '30 seconds'"),
        )
    )
    row = result.first()
    bid_vol = _money(row.bid_vol) if row else Decimal("0")
    ask_vol = _money(row.ask_vol) if row else Decimal("0")
    total = bid_vol + ask_vol
    if total == Decimal("0"):
        return Decimal("0")
    return (bid_vol - ask_vol) / total


async def _compute_vwap(conn: AsyncConnection, instrument_id) -> Decimal | None:
    """Volume-weighted average price of the last 20 trades for an instrument."""
    recent = (
        sa.select(
            market_trades.c.price,
            market_trades.c.quantity,
        )
        .where(market_trades.c.instrument_id == instrument_id)
        .order_by(market_trades.c.created_at.desc())
        .limit(20)
        .subquery()
    )
    result = await conn.execute(
        sa.select(
            sa.func.sum(recent.c.price * recent.c.quantity).label("pq_sum"),
            sa.func.sum(recent.c.quantity).label("q_sum"),
        )
    )
    row = result.first()
    if row is None or row.q_sum is None or row.q_sum == 0:
        return None
    return _money(Decimal(str(row.pq_sum)) / Decimal(str(row.q_sum)))


async def _compute_finding_quality_mark(
    conn: AsyncConnection,
    finding_id,
) -> Decimal:
    """Continuous quality-based mark for a finding note.

    Uses validation count, citation count, confidence, and challenge metrics
    to produce a smooth appreciation curve instead of binary status→price mapping.
    """
    from nexus_core.models.knowledge_graph import knowledge_graph_nodes, knowledge_graph_edges

    # Get finding status and KG node IDs
    finding_row = await conn.execute(
        sa.select(findings.c.status, findings.c.kg_nodes_created)
        .where(findings.c.finding_id == finding_id)
    )
    finding = finding_row.first()
    if finding is None:
        return Decimal("50.00")

    base_map = {
        "proposed": Decimal("50"),
        "pending_review": Decimal("50"),
        "citation_checking": Decimal("50"),
        "validated": Decimal("60"),
        "revision_requested": Decimal("40"),
        "challenged": Decimal("45"),
        "escalated": Decimal("10"),
        "failed": Decimal("10"),
        "superseded": Decimal("30"),
    }
    base = base_map.get(finding.status, Decimal("50"))

    # Extract node IDs from kg_nodes_created JSON
    kg_node_refs = finding.kg_nodes_created or []
    node_ids = []
    for ref in kg_node_refs:
        nid = ref if isinstance(ref, str) else (ref.get("node_id", ref) if isinstance(ref, dict) else str(ref))
        try:
            from uuid import UUID as _UUID
            node_ids.append(_UUID(str(nid)))
        except (ValueError, AttributeError):
            continue

    if not node_ids:
        return _money(max(Decimal("5"), min(base, Decimal("95"))))

    # Query KG node quality metrics
    node_result = await conn.execute(
        sa.select(
            sa.func.avg(knowledge_graph_nodes.c.confidence_score).label("avg_confidence"),
            sa.func.avg(sa.cast(knowledge_graph_nodes.c.validation_count, sa.Numeric)).label("avg_validations"),
            sa.func.avg(sa.cast(knowledge_graph_nodes.c.challenge_count, sa.Numeric)).label("avg_challenges"),
            sa.func.avg(sa.cast(knowledge_graph_nodes.c.challenge_failures, sa.Numeric)).label("avg_failures"),
        ).where(knowledge_graph_nodes.c.node_id.in_(node_ids))
    )
    nrow = node_result.first()

    # Count citations: edges where source is one of our nodes
    citation_result = await conn.execute(
        sa.select(sa.func.count()).select_from(knowledge_graph_edges)
        .where(knowledge_graph_edges.c.source_node_id.in_(node_ids))
    )
    citation_count = citation_result.scalar_one() or 0

    avg_conf = Decimal(str(nrow.avg_confidence or "0.5"))
    avg_val = Decimal(str(nrow.avg_validations or "0"))
    avg_chal = Decimal(str(nrow.avg_challenges or "0"))
    avg_fail = Decimal(str(nrow.avg_failures or "0"))

    score = (
        base
        + avg_val * Decimal("3.0")
        + Decimal(str(citation_count)) * Decimal("2.0")
        + (avg_conf - Decimal("0.5")) * Decimal("20.0")
        - avg_chal * Decimal("2.5")
        - avg_fail * Decimal("5.0")
    )
    return _money(max(Decimal("5"), min(score, Decimal("95"))))


async def update_market_marks(conn: AsyncConnection, obi_sensitivity: float = 1.0) -> int:
    """Update mark prices using VWAP + OBI with continuous finding quality marks.

    OBI (Order Book Imbalance) makes prices respond to demand pressure:
    - 7 bids at 56 with no asks → OBI = +1.0 → mark rises by c1
    - Finding notes blend 70% quality mark + 30% market signal
    """
    updates = 0
    c1 = Decimal(str(obi_sensitivity))

    instruments = (
        await conn.execute(
            sa.select(market_instruments).where(market_instruments.c.settlement_status == "open")
        )
    ).fetchall()

    for instrument in instruments:
        current_mark = _money(instrument.mark_price)
        par = _money(getattr(instrument, "par_value", None) or Decimal("50"))

        # Compute VWAP (volume-weighted average of recent trades)
        vwap = await _compute_vwap(conn, instrument.instrument_id)
        if vwap is None:
            # No trades yet — use last trade price or par value
            vwap = _money(instrument.last_trade_price) if _money(instrument.last_trade_price) > 0 else par

        # Compute OBI (order book imbalance)
        obi = await _compute_obi(conn, instrument.instrument_id)

        # Market signal: VWAP adjusted by OBI pressure
        market_signal = vwap + c1 * obi

        # For finding_note instruments: blend quality mark with market signal
        if instrument.family == "finding_note" and instrument.underlying_finding_id is not None:
            quality_mark = await _compute_finding_quality_mark(conn, instrument.underlying_finding_id)
            next_mark = _money(quality_mark * Decimal("0.7") + market_signal * Decimal("0.3"))
        else:
            next_mark = _money(market_signal)

        # Clamp to [5, 95] range
        next_mark = _money(max(Decimal("5"), min(next_mark, Decimal("95"))))

        if next_mark == current_mark:
            continue

        await conn.execute(
            market_instruments.update()
            .where(market_instruments.c.instrument_id == instrument.instrument_id)
            .values(mark_price=next_mark)
        )
        await conn.execute(
            market_price_history.insert().values(
                instrument_id=instrument.instrument_id,
                last_trade_price=_money(instrument.last_trade_price),
                mark_price=next_mark,
                traded_volume=Decimal("0.0000"),
                source="mark",
            )
        )
        await conn.execute(
            market_positions.update()
            .where(market_positions.c.instrument_id == instrument.instrument_id)
            .values(market_value=sa.type_coerce(market_positions.c.net_quantity * next_mark, sa.Numeric(12, 2)))
        )
        await emit_event(
            conn,
            "market_mark_updated",
            entity_id=instrument.instrument_id,
            entity_type="instrument",
            payload={"instrument_symbol": instrument.symbol, "mark_price": str(next_mark), "obi": str(obi)},
        )
        updates += 1
    return updates


async def _compute_settlement_value(conn: AsyncConnection, instrument_row: Any) -> Decimal:
    if instrument_row.family == "objective_note" and instrument_row.underlying_objective_id:
        status = await conn.scalar(
            sa.select(objectives.c.status).where(
                objectives.c.objective_id == instrument_row.underlying_objective_id
            )
        )
        return _status_mark(str(status or "proposed"))

    if instrument_row.family == "finding_note" and instrument_row.underlying_finding_id:
        return await _compute_finding_quality_mark(conn, instrument_row.underlying_finding_id)

    if instrument_row.family == "persona_performance_note" and instrument_row.underlying_persona_id:
        persona = (
            await conn.execute(
                sa.select(agent_personas.c.reputation_score).where(
                    agent_personas.c.persona_id == instrument_row.underlying_persona_id
                )
            )
        ).first()
        current_balance = await get_available_balance(conn, instrument_row.underlying_persona_id)
        metadata = dict(instrument_row.metadata_json or {})
        baseline_balance = Decimal(str(metadata.get("baseline_balance", "0")))
        baseline_rep = Decimal(str(metadata.get("baseline_reputation", "0.5")))
        current_rep = Decimal(str(getattr(persona, "reputation_score", Decimal("0.5")) or 0.5))
        score = Decimal("50.00")
        score += min(max(current_balance - baseline_balance, Decimal("-40.00")), Decimal("40.00")) * Decimal("0.5")
        score += (current_rep - baseline_rep) * Decimal("80.00")
        return _money(max(Decimal("10.00"), min(score, Decimal("90.00"))))

    return _money(instrument_row.mark_price or Decimal("50.00"))


async def settle_expired_instruments(conn: AsyncConnection) -> int:
    now = _now()
    rows = (
        await conn.execute(
            sa.select(market_instruments).where(
                market_instruments.c.settlement_status == "open",
                market_instruments.c.settlement_at.is_not(None),
                market_instruments.c.settlement_at <= now,
            )
        )
    ).fetchall()
    settled = 0
    for row in rows:
        settlement_value = await _compute_settlement_value(conn, row)
        positions = (
            await conn.execute(
                sa.select(market_positions).where(
                    market_positions.c.instrument_id == row.instrument_id,
                    market_positions.c.net_quantity != Decimal("0.0000"),
                )
            )
        ).fetchall()
        for position in positions:
            payout = _money(_qty(position.net_quantity) * settlement_value)
            if payout > 0:
                await _transfer_credits(
                    conn,
                    from_persona_id=None,
                    to_persona_id=position.persona_id,
                    amount=payout,
                    transaction_type="security_settlement_payout",
                    memo=f"Settlement payout for {row.symbol}",
                )
            elif payout < 0:
                charge = _money(abs(payout))
                await _transfer_credits(
                    conn,
                    from_persona_id=position.persona_id,
                    to_persona_id=None,
                    amount=charge,
                    transaction_type="security_settlement_charge",
                    memo=f"Settlement charge for {row.symbol}",
                )
                if await get_available_balance(conn, position.persona_id) < Decimal("0.00"):
                    await emit_event(
                        conn,
                        "position_liquidated",
                        entity_id=position.position_id,
                        entity_type="position",
                        payload={"instrument_symbol": row.symbol, "persona_id": str(position.persona_id)},
                    )
            await conn.execute(
                market_positions.update()
                .where(market_positions.c.position_id == position.position_id)
                .values(net_quantity=Decimal("0.0000"), market_value=Decimal("0.00"))
            )

        reservation_rows = (
            await conn.execute(
                sa.select(market_reservations.c.reservation_id).where(
                    market_reservations.c.instrument_id == row.instrument_id,
                    market_reservations.c.status == STATUS_OPEN,
                )
            )
        ).fetchall()
        for reservation in reservation_rows:
            await release_reservation(conn, reservation.reservation_id)
        await conn.execute(
            market_instruments.update()
            .where(market_instruments.c.instrument_id == row.instrument_id)
            .values(
                settlement_status="settled",
                settlement_value=settlement_value,
                mark_price=settlement_value,
                last_trade_price=settlement_value,
            )
        )
        settled += 1
    return settled


NODE_TYPE_AFFINITY: dict[str, tuple[str, ...]] = {
    "researcher": ("mechanism", "concept", "hypothesis"),
    "analyst": ("outcome", "metric", "method"),
    "scout": ("entity", "intervention", "population"),
    "synthesizer": ("concept", "mechanism", "process"),
    "critic": ("risk", "argument", "method"),
    "red_team": ("risk", "argument", "entity"),
    "consolidator": ("concept", "mechanism", "outcome"),
    "molecular_biologist": ("mechanism", "entity", "intervention"),
    "immunologist": ("mechanism", "entity", "intervention"),
    "computational_biologist": ("method", "mechanism", "metric"),
    "bioinformatician": ("method", "metric", "entity"),
    "pharmacologist": ("intervention", "mechanism", "outcome"),
    "systems_biologist": ("mechanism", "process", "concept"),
    "experimentalist": ("method", "outcome", "intervention"),
    "bioengineer": ("method", "intervention", "entity"),
    "economist": ("concept", "outcome", "risk"),
    "policy_researcher": ("policy", "argument", "concept"),
    "education_strategist": ("concept", "method", "outcome"),
}


async def maybe_purchase_nodes(
    conn: AsyncConnection,
    *,
    settings: NexusSettings,
    objective_id: UUID,
    cycle_tick: int = 0,
) -> int:
    """Autonomous agent decisions to purchase unowned KG nodes.

    Follows the same deterministic heuristic pattern as ``maybe_create_listings()``.
    Agents select nodes based on role affinity, value, and betweenness centrality.
    """
    from nexus_core.market.node_ownership import compute_node_value, purchase_node

    # 1. Candidate buyers
    personas = await _persona_rows_with_market_balance(conn)
    buyers = [
        p for p in personas
        if _money(p.available_balance) >= settings.NODE_PURCHASE_MIN_BALANCE
        and not _is_distressed_balance(_money(p.available_balance), settings)
        and Decimal(str(p.reputation_score or 0)) >= settings.NODE_CAPABILITY_GATE
    ]
    # Sort by reputation desc (better researchers buy first)
    buyers.sort(key=lambda p: float(p.reputation_score or 0), reverse=True)

    # 2. Candidate nodes (unowned, validated/proposed, decent confidence)
    from nexus_core.models.knowledge_graph import knowledge_graph_nodes
    node_result = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.node_id,
            knowledge_graph_nodes.c.label,
            knowledge_graph_nodes.c.node_type,
            knowledge_graph_nodes.c.confidence_score,
            knowledge_graph_nodes.c.betweenness_score,
        )
        .where(
            knowledge_graph_nodes.c.owner_persona_id.is_(None),
            knowledge_graph_nodes.c.status.in_(["validated", "proposed"]),
            knowledge_graph_nodes.c.confidence_score >= settings.NODE_PURCHASE_MIN_CONFIDENCE,
        )
        .order_by(
            knowledge_graph_nodes.c.betweenness_score.desc(),
            knowledge_graph_nodes.c.confidence_score.desc(),
        )
        .limit(20)
    )
    candidate_nodes = node_result.fetchall()

    if not buyers or not candidate_nodes:
        return 0

    purchased = 0
    max_per_cycle = 2  # Rate limit

    for buyer in buyers:
        if purchased >= max_per_cycle:
            break

        # How many does this persona already own?
        owned_count_r = await conn.execute(
            sa.select(sa.func.count()).select_from(knowledge_graph_nodes)
            .where(knowledge_graph_nodes.c.owner_persona_id == buyer.persona_id)
        )
        owned_count = owned_count_r.scalar_one()
        if owned_count >= settings.NODE_MAX_OWNED_PER_AGENT:
            continue

        # Role affinity: prefer matching node_types
        affinity = NODE_TYPE_AFFINITY.get(buyer.role_class, ())

        # Find best candidate: preferred affinity first, then any
        best_node = None
        for node in candidate_nodes:
            if node.node_type in affinity:
                best_node = node
                break
        if best_node is None and candidate_nodes:
            best_node = candidate_nodes[0]  # Fall back to highest-centrality node
        if best_node is None:
            continue

        # Compute value and check affordability
        node_value = await compute_node_value(conn, best_node.node_id)
        superlinear = Decimal("1") + (Decimal(str(owned_count)) * settings.NODE_SUPERLINEAR_FACTOR)
        effective_price = _money(node_value * superlinear)
        max_spend = _money(_money(buyer.available_balance) * settings.NODE_PURCHASE_MAX_SPEND_PCT)

        if effective_price > max_spend:
            continue

        # Execute purchase
        try:
            result = await purchase_node(
                conn, buyer.persona_id, best_node.node_id,
                base_price=settings.NODE_BASE_PRICE,
                edge_value_multiplier=settings.NODE_EDGE_VALUE_MULTIPLIER,
                centrality_multiplier=settings.NODE_CENTRALITY_MULTIPLIER,
                min_price=settings.NODE_MIN_PRICE,
                max_price=settings.NODE_MAX_PRICE,
                max_owned=settings.NODE_MAX_OWNED_PER_AGENT,
                max_portfolio_pct=settings.NODE_MAX_PORTFOLIO_PCT,
                capability_gate=settings.NODE_CAPABILITY_GATE,
                superlinear_factor=settings.NODE_SUPERLINEAR_FACTOR,
            )
        except ValueError:
            continue

        # Log as market action
        await _record_market_action(
            conn,
            settings=settings,
            persona_id=buyer.persona_id,
            persona_name=buyer.persona_name,
            objective_id=objective_id,
            objective_title="Marketplace Operations",
            action_type="purchase_kg_node",
            action_payload={
                "action_type": "purchase_kg_node",
                "persona_id": str(buyer.persona_id),
                "node_id": result["node_id"],
                "price": float(result["purchase_price"]),
                "listing_kind": "kg_node",
                "details": {
                    "node_label": result["label"],
                    "owned_count": result["owned_count"],
                },
            },
            spawn_reason="kg_node_acquisition_decision",
            detail_summary=f"Purchased KG node '{result['label'][:40]}' for {result['purchase_price']} credits.",
        )

        # Remove from candidates so next buyer doesn't pick same node
        candidate_nodes = [n for n in candidate_nodes if n.node_id != best_node.node_id]
        purchased += 1

    return purchased


async def maybe_sell_nodes(
    conn: AsyncConnection,
    *,
    settings: NexusSettings,
    objective_id: UUID,
) -> int:
    """Autonomous agent decisions to sell depreciating KG nodes.

    Agents sell nodes when:
    - Confidence has dropped below 0.15 (cut losses)
    - No traversals and agent has low balance (< 50 credits)
    """
    from nexus_core.market.node_ownership import sell_node

    from nexus_core.models.knowledge_graph import knowledge_graph_nodes

    # Find owned nodes with poor metrics
    result = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.node_id,
            knowledge_graph_nodes.c.label,
            knowledge_graph_nodes.c.owner_persona_id,
            knowledge_graph_nodes.c.confidence_score,
            knowledge_graph_nodes.c.last_traversal_count,
        )
        .where(
            knowledge_graph_nodes.c.owner_persona_id.isnot(None),
            sa.or_(
                knowledge_graph_nodes.c.confidence_score < Decimal("0.15"),
                sa.and_(
                    knowledge_graph_nodes.c.last_traversal_count == 0,
                    knowledge_graph_nodes.c.confidence_score < Decimal("0.30"),
                ),
            ),
        )
    )
    candidates = result.fetchall()

    sold = 0
    for node in candidates:
        # For low-traversal nodes, only sell if owner has low balance
        if node.confidence_score >= Decimal("0.15"):
            balance = await get_available_balance(conn, node.owner_persona_id)
            if balance >= Decimal("50"):
                continue

        # Get persona name for logging
        name_result = await conn.execute(
            sa.select(agent_personas.c.persona_name)
            .where(agent_personas.c.persona_id == node.owner_persona_id)
        )
        name_row = name_result.first()
        persona_name = name_row.persona_name if name_row else "Unknown"

        try:
            result = await sell_node(conn, node.owner_persona_id, node.node_id)
        except ValueError:
            continue

        await _record_market_action(
            conn,
            settings=settings,
            persona_id=node.owner_persona_id,
            persona_name=persona_name,
            objective_id=objective_id,
            objective_title="Marketplace Operations",
            action_type="sell_kg_node",
            action_payload={
                "action_type": "sell_kg_node",
                "persona_id": str(node.owner_persona_id),
                "node_id": str(node.node_id),
                "price": float(result["sale_price"]),
                "listing_kind": "kg_node",
                "details": {
                    "node_label": node.label[:40],
                    "realized_pnl": result["realized_pnl"],
                    "reason": "low_confidence" if float(node.confidence_score) < 0.15 else "low_traversal_low_balance",
                },
            },
            spawn_reason="kg_node_sale_decision",
            detail_summary=f"Sold KG node '{node.label[:40]}' for {result['sale_price']} credits (P&L: {result['realized_pnl']}).",
        )
        sold += 1

    return sold


async def run_market_cycle(
    conn: AsyncConnection,
    settings: NexusSettings,
    cycle_tick: int = 0,
) -> dict[str, int]:
    """Advance the autonomous market one deterministic tick."""
    await ensure_civilization_state(conn)
    objective_ids = await ensure_market_objectives(conn)
    await sync_persona_market_profiles(conn, settings)
    await seed_market_templates(conn)
    instruments_created = await ensure_market_instruments(conn)
    listings_created = await maybe_create_listings(
        conn,
        settings=settings,
        objective_id=objective_ids["marketplace"],
        cycle_tick=cycle_tick,
    )
    relisted_assets = await maybe_relist_owned_assets(
        conn,
        settings=settings,
        objective_id=objective_ids["marketplace"],
    )
    purchases = await maybe_submit_purchases(
        conn,
        settings=settings,
        objective_id=objective_ids["marketplace"],
    )
    fulfilled, refunded = await process_service_contracts(conn, settings=settings)
    nodes_purchased = await maybe_purchase_nodes(
        conn, settings=settings,
        objective_id=objective_ids["marketplace"],
        cycle_tick=cycle_tick,
    )
    nodes_sold = await maybe_sell_nodes(
        conn, settings=settings,
        objective_id=objective_ids["marketplace"],
    )
    orders_placed = await maybe_place_orders(
        conn,
        settings=settings,
        objective_id=objective_ids["securities"],
    )
    trades = await match_orders(conn)
    cancelled = await cancel_stale_orders(conn)
    mark_updates = await update_market_marks(conn, obi_sensitivity=settings.MARKET_OBI_SENSITIVITY)
    settlements = await settle_expired_instruments(conn)
    return {
        "instruments_created": instruments_created,
        "listings_created": listings_created,
        "secondary_listings_created": relisted_assets,
        "purchases": purchases,
        "contracts_fulfilled": fulfilled,
        "contracts_refunded": refunded,
        "orders_placed": orders_placed,
        "nodes_purchased": nodes_purchased,
        "nodes_sold": nodes_sold,
        "orders_cancelled": cancelled,
        "trades": trades,
        "mark_updates": mark_updates,
        "settlements": settlements,
    }


async def get_marketplace_overview(conn: AsyncConnection) -> dict[str, Any]:
    listing_rows = (
        await conn.execute(
            sa.select(
                marketplace_listings.c.listing_kind,
                marketplace_listings.c.price,
                marketplace_listings.c.quantity_available,
                marketplace_listings.c.seller_persona_id,
            ).where(marketplace_listings.c.status == "active")
        )
    ).fetchall()
    contract_rows = (
        await conn.execute(
            sa.select(
                service_contracts.c.status,
                service_contracts.c.buyer_persona_id,
                service_contracts.c.seller_persona_id,
                service_contracts.c.agreed_price,
                service_contracts.c.created_at,
            )
        )
    ).fetchall()
    category_counts = Counter(str(row.listing_kind) for row in listing_rows)
    top_sellers = Counter(str(row.seller_persona_id) for row in contract_rows if row.status in {"fulfilled", "completed"})
    top_buyers = Counter(str(row.buyer_persona_id) for row in contract_rows if row.status in {"fulfilled", "completed"})
    listing_value = sum(_money(row.price) * Decimal(int(row.quantity_available or 0)) for row in listing_rows)
    recent_window = _now() - timedelta(hours=24)
    fulfilled_24h = sum(1 for row in contract_rows if row.status in {"fulfilled", "completed"} and row.created_at >= recent_window)
    return {
        "active_listings": len(listing_rows),
        "pending_contracts": sum(1 for row in contract_rows if row.status == "pending_fulfillment"),
        "fulfilled_contracts_24h": fulfilled_24h,
        "total_listing_value": float(_money(listing_value)),
        "category_breakdown": dict(category_counts),
        "top_seller_ids": [seller_id for seller_id, _ in top_sellers.most_common(5)],
        "top_buyer_ids": [buyer_id for buyer_id, _ in top_buyers.most_common(5)],
    }


async def get_marketplace_listings(conn: AsyncConnection, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            sa.select(
                marketplace_listings.c.listing_id,
                marketplace_listings.c.listing_kind,
                marketplace_listings.c.price,
                marketplace_listings.c.quantity_available,
                marketplace_listings.c.status,
                marketplace_listings.c.description,
                marketplace_listings.c.metadata_json,
                marketplace_listings.c.created_at,
                agent_personas.c.persona_id.label("seller_persona_id"),
                agent_personas.c.persona_name.label("seller_name"),
                agent_personas.c.role_class.label("seller_role_class"),
                market_templates.c.template_code,
                market_templates.c.title.label("template_title"),
            )
            .join(agent_personas, marketplace_listings.c.seller_persona_id == agent_personas.c.persona_id)
            .join(market_templates, marketplace_listings.c.template_id == market_templates.c.template_id)
            .order_by(
                sa.case((marketplace_listings.c.status == "active", 0), else_=1),
                marketplace_listings.c.created_at.desc(),
            )
            .limit(limit)
        )
    ).fetchall()
    return [
        {
            "listing_id": row.listing_id,
            "listing_kind": row.listing_kind,
            "price": float(_money(row.price)),
            "quantity_available": int(row.quantity_available or 0),
            "status": row.status,
            "description": row.description,
            "metadata": dict(row.metadata_json or {}),
            "created_at": row.created_at,
            "seller_persona_id": row.seller_persona_id,
            "seller_name": row.seller_name,
            "seller_role_class": row.seller_role_class,
            "template_code": row.template_code,
            "template_title": row.template_title,
        }
        for row in rows
    ]


async def get_service_contracts(conn: AsyncConnection, *, limit: int = 50) -> list[dict[str, Any]]:
    buyer_alias = agent_personas.alias("buyer_personas")
    seller_alias = agent_personas.alias("seller_personas")
    rows = (
        await conn.execute(
            sa.select(
                service_contracts.c.contract_id,
                service_contracts.c.status,
                service_contracts.c.agreed_price,
                service_contracts.c.quantity,
                service_contracts.c.created_at,
                service_contracts.c.fulfilled_at,
                service_contracts.c.refunded_at,
                service_contracts.c.target_objective_id,
                service_contracts.c.target_finding_id,
                service_contracts.c.service_objective_id,
                service_contracts.c.fulfillment_summary,
                market_templates.c.template_code,
                market_templates.c.title.label("template_title"),
                buyer_alias.c.persona_id.label("buyer_persona_id"),
                buyer_alias.c.persona_name.label("buyer_name"),
                seller_alias.c.persona_id.label("seller_persona_id"),
                seller_alias.c.persona_name.label("seller_name"),
            )
            .join(marketplace_listings, service_contracts.c.listing_id == marketplace_listings.c.listing_id)
            .join(market_templates, marketplace_listings.c.template_id == market_templates.c.template_id)
            .join(buyer_alias, service_contracts.c.buyer_persona_id == buyer_alias.c.persona_id)
            .join(seller_alias, service_contracts.c.seller_persona_id == seller_alias.c.persona_id)
            .order_by(service_contracts.c.created_at.desc())
            .limit(limit)
        )
    ).fetchall()
    return [
        {
            "contract_id": row.contract_id,
            "status": row.status,
            "agreed_price": float(_money(row.agreed_price)),
            "quantity": int(row.quantity or 0),
            "created_at": row.created_at,
            "fulfilled_at": row.fulfilled_at,
            "refunded_at": row.refunded_at,
            "target_objective_id": row.target_objective_id,
            "target_finding_id": row.target_finding_id,
            "service_objective_id": row.service_objective_id,
            "fulfillment_summary": row.fulfillment_summary,
            "template_code": row.template_code,
            "template_title": row.template_title,
            "buyer_persona_id": row.buyer_persona_id,
            "buyer_name": row.buyer_name,
            "seller_persona_id": row.seller_persona_id,
            "seller_name": row.seller_name,
        }
        for row in rows
    ]


async def get_market_activity(conn: AsyncConnection, *, limit: int = 50) -> list[dict[str, Any]]:
    from nexus_core.models.events import events

    rows = (
        await conn.execute(
            sa.select(events)
            .where(
                sa.or_(
                    events.c.event_type.like("market_%"),
                    events.c.event_type.like("service_contract_%"),
                    events.c.event_type.like("security_%"),
                    events.c.event_type.like("instrument_%"),
                    events.c.event_type.like("position_%"),
                    events.c.event_type.like("settlement_%"),
                )
            )
            .order_by(events.c.created_at.desc())
            .limit(limit)
        )
    ).fetchall()
    return [
        {
            "event_id": row.event_id,
            "event_type": row.event_type,
            "entity_id": row.entity_id,
            "entity_type": row.entity_type,
            "payload": dict(row.payload or {}),
            "created_at": row.created_at,
        }
        for row in rows
    ]


async def get_securities_overview(conn: AsyncConnection) -> dict[str, Any]:
    instrument_rows = (await conn.execute(sa.select(market_instruments))).fetchall()
    open_orders = int(
        await conn.scalar(
            sa.select(sa.func.count()).select_from(market_orders).where(market_orders.c.status == STATUS_OPEN)
        )
        or 0
    )
    trade_volume = _money(
        await conn.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(market_trades.c.notional), Decimal("0")))
        )
        or Decimal("0")
    )
    halted = sum(1 for row in instrument_rows if row.halted)
    settlement_backlog = sum(1 for row in instrument_rows if row.settlement_status == "open" and row.settlement_at and row.settlement_at <= _now())
    return {
        "instrument_count": len(instrument_rows),
        "open_order_count": open_orders,
        "trade_volume": float(trade_volume),
        "halted_count": halted,
        "settlement_backlog": settlement_backlog,
    }


async def get_market_instruments(conn: AsyncConnection, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            sa.select(market_instruments)
            .order_by(
                sa.case((market_instruments.c.settlement_status == "open", 0), else_=1),
                market_instruments.c.updated_at.desc(),
            )
            .limit(limit)
        )
    ).fetchall()
    return [
        {
            "instrument_id": row.instrument_id,
            "symbol": row.symbol,
            "name": row.name,
            "family": row.family,
            "risk_tier": row.risk_tier,
            "halted": bool(row.halted),
            "settlement_status": row.settlement_status,
            "settlement_value": float(_money(row.settlement_value)) if row.settlement_value is not None else None,
            "last_trade_price": float(_money(row.last_trade_price)),
            "mark_price": float(_money(row.mark_price)),
            "expiry_at": row.expiry_at,
            "settlement_at": row.settlement_at,
            "metadata": dict(row.metadata_json or {}),
            "underlying_objective_id": row.underlying_objective_id,
            "underlying_finding_id": row.underlying_finding_id,
            "underlying_persona_id": row.underlying_persona_id,
        }
        for row in rows
    ]


async def get_order_book(
    conn: AsyncConnection,
    *,
    instrument_id: UUID | None = None,
) -> dict[str, Any]:
    if instrument_id is None:
        row = (
            await conn.execute(
                sa.select(market_instruments.c.instrument_id, market_instruments.c.symbol)
                .where(market_instruments.c.settlement_status == "open")
                .order_by(market_instruments.c.updated_at.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return {"instrument_id": None, "instrument_symbol": None, "bids": [], "asks": []}
        instrument_id = row.instrument_id
        instrument_symbol = row.symbol
    else:
        instrument_symbol = await conn.scalar(
            sa.select(market_instruments.c.symbol).where(market_instruments.c.instrument_id == instrument_id)
        )

    bid_rows = (
        await conn.execute(
            sa.select(
                market_orders.c.order_id,
                market_orders.c.price,
                market_orders.c.quantity,
                market_orders.c.filled_quantity,
                agent_personas.c.persona_name,
            )
            .join(agent_personas, market_orders.c.persona_id == agent_personas.c.persona_id)
            .where(
                market_orders.c.instrument_id == instrument_id,
                market_orders.c.side == "buy",
                market_orders.c.status == STATUS_OPEN,
            )
            .order_by(market_orders.c.price.desc(), market_orders.c.created_at.asc())
            .limit(15)
        )
    ).fetchall()
    ask_rows = (
        await conn.execute(
            sa.select(
                market_orders.c.order_id,
                market_orders.c.price,
                market_orders.c.quantity,
                market_orders.c.filled_quantity,
                agent_personas.c.persona_name,
            )
            .join(agent_personas, market_orders.c.persona_id == agent_personas.c.persona_id)
            .where(
                market_orders.c.instrument_id == instrument_id,
                market_orders.c.side == "sell",
                market_orders.c.status == STATUS_OPEN,
            )
            .order_by(market_orders.c.price.asc(), market_orders.c.created_at.asc())
            .limit(15)
        )
    ).fetchall()

    return {
        "instrument_id": instrument_id,
        "instrument_symbol": instrument_symbol,
        "bids": [
            {
                "order_id": row.order_id,
                "price": float(_money(row.price)),
                "remaining_quantity": float(_qty(row.quantity - row.filled_quantity)),
                "persona_name": row.persona_name,
            }
            for row in bid_rows
        ],
        "asks": [
            {
                "order_id": row.order_id,
                "price": float(_money(row.price)),
                "remaining_quantity": float(_qty(row.quantity - row.filled_quantity)),
                "persona_name": row.persona_name,
            }
            for row in ask_rows
        ],
    }


async def get_trades(conn: AsyncConnection, *, limit: int = 50) -> list[dict[str, Any]]:
    buyer_alias = agent_personas.alias("trade_buyer")
    seller_alias = agent_personas.alias("trade_seller")
    rows = (
        await conn.execute(
            sa.select(
                market_trades.c.trade_id,
                market_trades.c.price,
                market_trades.c.quantity,
                market_trades.c.notional,
                market_trades.c.created_at,
                market_instruments.c.instrument_id,
                market_instruments.c.symbol,
                buyer_alias.c.persona_name.label("buyer_name"),
                seller_alias.c.persona_name.label("seller_name"),
            )
            .join(market_instruments, market_trades.c.instrument_id == market_instruments.c.instrument_id)
            .join(buyer_alias, market_trades.c.buyer_persona_id == buyer_alias.c.persona_id)
            .join(seller_alias, market_trades.c.seller_persona_id == seller_alias.c.persona_id)
            .order_by(market_trades.c.created_at.desc())
            .limit(limit)
        )
    ).fetchall()
    return [
        {
            "trade_id": row.trade_id,
            "instrument_id": row.instrument_id,
            "instrument_symbol": row.symbol,
            "price": float(_money(row.price)),
            "quantity": float(_qty(row.quantity)),
            "notional": float(_money(row.notional)),
            "created_at": row.created_at,
            "buyer_name": row.buyer_name,
            "seller_name": row.seller_name,
        }
        for row in rows
    ]


async def get_positions(conn: AsyncConnection, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            sa.select(
                market_positions.c.position_id,
                market_positions.c.net_quantity,
                market_positions.c.average_entry_price,
                market_positions.c.realized_pnl,
                market_positions.c.market_value,
                market_positions.c.updated_at,
                market_instruments.c.instrument_id,
                market_instruments.c.symbol,
                agent_personas.c.persona_id,
                agent_personas.c.persona_name,
                agent_personas.c.role_class,
            )
            .join(market_instruments, market_positions.c.instrument_id == market_instruments.c.instrument_id)
            .join(agent_personas, market_positions.c.persona_id == agent_personas.c.persona_id)
            .where(market_positions.c.net_quantity != Decimal("0.0000"))
            .order_by(sa.func.abs(market_positions.c.market_value).desc())
            .limit(limit)
        )
    ).fetchall()
    return [
        {
            "position_id": row.position_id,
            "instrument_id": row.instrument_id,
            "instrument_symbol": row.symbol,
            "persona_id": row.persona_id,
            "persona_name": row.persona_name,
            "role_class": row.role_class,
            "net_quantity": float(_qty(row.net_quantity)),
            "average_entry_price": float(_money(row.average_entry_price)),
            "realized_pnl": float(_money(row.realized_pnl)),
            "market_value": float(_money(row.market_value)),
            "updated_at": row.updated_at,
        }
        for row in rows
    ]
