from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from nexus_core.economy.ledger import mint_credits
from nexus_core.market.service import (
    create_reservation,
    ensure_market_objectives,
    get_marketplace_overview,
    get_securities_overview,
    maybe_create_listings,
    maybe_relist_owned_assets,
    maybe_submit_purchases,
    process_service_contracts,
    run_market_cycle,
    seed_market_templates,
    settle_expired_instruments,
)
from nexus_core.models.economy import economy_ledger
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.market import (
    market_assets,
    market_instruments,
    market_positions,
    market_reservations,
    market_templates,
    marketplace_listings,
    service_contracts,
)
from nexus_core.models.objectives import objectives
from nexus_core.models.personas import agent_personas


async def _seed_market_persona(
    conn,
    *,
    name: str,
    role_class: str,
    reputation: str,
    credits: str,
) -> UUID:
    result = await conn.execute(
        agent_personas.insert()
        .values(
            persona_name=name,
            role_class=role_class,
            system_prompt_template=f"You are the {role_class} persona for NEXUS.",
            reputation_score=Decimal(reputation),
            status="active",
        )
        .returning(agent_personas.c.persona_id)
    )
    persona_id = result.scalar_one()
    await mint_credits(
        conn,
        Decimal(credits),
        persona_id,
        memo=f"Seed balance for {name}",
    )
    return persona_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_market_cycle_creates_market_activity_on_real_postgres(clean_database, settings):
    engine = clean_database
    runtime_settings = settings.model_copy(
        update={
            "MARKET_IDLE_BALANCE_THRESHOLD": Decimal("100.00"),
            "MARKET_MAX_LISTINGS_PER_PERSONA": 2,
            "MARKET_MAX_OPEN_ORDERS_PER_PERSONA": 8,
            "MARKET_SERVICE_TIMEOUT_MINS": 30,
        }
    )

    async with engine.begin() as conn:
        researcher_id = await _seed_market_persona(
            conn,
            name="Red Team Treasury",
            role_class="red_team",
            reputation="0.880",
            credits="260.00",
        )
        await _seed_market_persona(
            conn,
            name="Systems Market Maker",
            role_class="synthesizer",
            reputation="0.920",
            credits="320.00",
        )
        await _seed_market_persona(
            conn,
            name="Prompt Artisan",
            role_class="tool_forger",
            reputation="0.850",
            credits="280.00",
        )

        objective_id = uuid4()
        await conn.execute(
            objectives.insert().values(
                objective_id=objective_id,
                title="Measure agentic coding adoption constraints",
                description="Seed a non-market objective for market-linked service contracts.",
                objective_type="strategic",
                impact_level="high-impact",
                priority=9,
                status="active",
                proposed_by_type="human",
                approved_by_type="system",
                compute_budget_allocated=Decimal("25.00"),
            )
        )
        instance_id = (
            await conn.execute(
                agent_instances.insert()
                .values(
                    persona_id=researcher_id,
                    objective_id=objective_id,
                    spawn_reason="seed_finding",
                    input_prompt="seed prompt",
                    output_content="seed output",
                    status="completed",
                    completed_at=datetime.now(UTC),
                )
                .returning(agent_instances.c.instance_id)
            )
        ).scalar_one()
        await conn.execute(
            findings.insert().values(
                objective_id=objective_id,
                instance_id=instance_id,
                finding_type="research",
                title="Seed validated finding",
                content="This finding exists to back a finding note.",
                structured_data={"confidence": 0.8, "citations": []},
                status="validated",
                impact_level="routine",
            )
        )

        summary = await run_market_cycle(conn, runtime_settings)
        marketplace_overview = await get_marketplace_overview(conn)
        securities_overview = await get_securities_overview(conn)

        market_objective_count = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(objectives)
                .where(objectives.c.objective_type == "market")
            )
            or 0
        )
        template_count = int(
            await conn.scalar(sa.select(sa.func.count()).select_from(market_templates))
            or 0
        )
        listing_count = int(
            await conn.scalar(sa.select(sa.func.count()).select_from(marketplace_listings))
            or 0
        )
        contract_count = int(
            await conn.scalar(sa.select(sa.func.count()).select_from(service_contracts))
            or 0
        )
        instrument_count = int(
            await conn.scalar(sa.select(sa.func.count()).select_from(market_instruments))
            or 0
        )
        trade_count = int(
            await conn.scalar(sa.select(sa.func.count()).select_from(economy_ledger).where(economy_ledger.c.transaction_type == "security_trade_cash"))
            or 0
        )
        service_objective_count = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(objectives)
                .where(objectives.c.output_type == "market_service")
            )
            or 0
        )

    assert summary["listings_created"] >= 1
    assert summary["purchases"] >= 1
    assert summary["orders_placed"] >= 2
    assert summary["trades"] >= 1
    assert market_objective_count >= 2
    assert template_count >= 6
    assert listing_count >= 1
    assert contract_count >= 1
    assert instrument_count >= 3
    assert trade_count >= 1
    assert service_objective_count >= 1
    assert marketplace_overview["active_listings"] >= 0
    assert marketplace_overview["fulfilled_contracts_24h"] >= 1
    assert securities_overview["instrument_count"] >= 3
    assert securities_overview["trade_volume"] > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_distressed_persona_can_create_inventory_for_sale(clean_database, settings):
    engine = clean_database
    runtime_settings = settings.model_copy(
        update={
            "MARKET_IDLE_BALANCE_THRESHOLD": Decimal("100.00"),
            "MARKET_MAX_LISTINGS_PER_PERSONA": 2,
        }
    )

    async with engine.begin() as conn:
        distressed_id = await _seed_market_persona(
            conn,
            name="Distressed Researcher",
            role_class="researcher",
            reputation="0.540",
            credits="0.20",
        )
        await _seed_market_persona(
            conn,
            name="Treasury Buyer",
            role_class="governor",
            reputation="0.900",
            credits="220.00",
        )
        objective_ids = await ensure_market_objectives(conn)
        await seed_market_templates(conn)

        created = await maybe_create_listings(
            conn,
            settings=runtime_settings,
            objective_id=objective_ids["marketplace"],
        )
        distressed_assets = (
            await conn.execute(
                sa.select(market_assets.c.asset_id, market_assets.c.metadata_json).where(
                    market_assets.c.crafted_by_persona_id == distressed_id
                )
            )
        ).fetchall()

    assert created >= 1
    assert distressed_assets
    assert any((row.metadata_json or {}).get("distress_inventory") for row in distressed_assets)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_process_service_contracts_refunds_expired_escrow(clean_database, settings):
    engine = clean_database

    async with engine.begin() as conn:
        buyer_id = await _seed_market_persona(
            conn,
            name="Buyer Persona",
            role_class="researcher",
            reputation="0.700",
            credits="120.00",
        )
        seller_id = await _seed_market_persona(
            conn,
            name="Seller Scout",
            role_class="scout",
            reputation="0.820",
            credits="140.00",
        )
        await seed_market_templates(conn)
        template = (
            await conn.execute(
                sa.select(market_templates).where(market_templates.c.template_code == "scout_package")
            )
        ).first()
        assert template is not None

        asset_id = (
            await conn.execute(
                market_assets.insert()
                .values(
                    template_id=template.template_id,
                    owner_persona_id=seller_id,
                    crafted_by_persona_id=seller_id,
                    asset_kind=template.listing_kind,
                    title="Scout Package",
                    description=template.description,
                    quantity_available=1,
                )
                .returning(market_assets.c.asset_id)
            )
        ).scalar_one()
        listing_id = (
            await conn.execute(
                marketplace_listings.insert()
                .values(
                    asset_id=asset_id,
                    seller_persona_id=seller_id,
                    template_id=template.template_id,
                    listing_kind=template.listing_kind,
                    price=Decimal("20.00"),
                    quantity_available=1,
                    description=template.description,
                )
                .returning(marketplace_listings.c.listing_id)
            )
        ).scalar_one()
        reservation_id = await create_reservation(
            conn,
            persona_id=buyer_id,
            amount=Decimal("20.00"),
            reservation_type="escrow",
            listing_id=listing_id,
            memo="Expired escrow test",
        )
        assert reservation_id is not None

        contract_id = (
            await conn.execute(
                service_contracts.insert()
                .values(
                    listing_id=listing_id,
                    buyer_persona_id=buyer_id,
                    seller_persona_id=seller_id,
                    reservation_id=reservation_id,
                    status="pending_fulfillment",
                    agreed_price=Decimal("20.00"),
                    quantity=1,
                    service_payload={"template_code": "scout_package"},
                    expires_at=datetime.now(UTC) - timedelta(minutes=2),
                )
                .returning(service_contracts.c.contract_id)
            )
        ).scalar_one()

        fulfilled, refunded = await process_service_contracts(conn, settings=settings)
        contract_row = (
            await conn.execute(
                sa.select(service_contracts.c.status, service_contracts.c.refunded_at).where(
                    service_contracts.c.contract_id == contract_id
                )
            )
        ).first()
        reservation_row = (
            await conn.execute(
                sa.select(market_reservations.c.status, market_reservations.c.remaining_amount).where(
                    market_reservations.c.reservation_id == reservation_id
                )
            )
        ).first()

    assert fulfilled == 0
    assert refunded == 1
    assert contract_row is not None
    assert contract_row.status == "refunded"
    assert contract_row.refunded_at is not None
    assert reservation_row is not None
    assert reservation_row.status == "released"
    assert Decimal(str(reservation_row.remaining_amount)) == Decimal("0.00")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_contract_rights_can_be_relisted_and_transfer_obligation(clean_database, settings):
    engine = clean_database
    runtime_settings = settings.model_copy(
        update={
            "MARKET_IDLE_BALANCE_THRESHOLD": Decimal("100.00"),
            "MARKET_MAX_LISTINGS_PER_PERSONA": 3,
            "MARKET_SERVICE_TIMEOUT_MINS": 30,
        }
    )

    async with engine.begin() as conn:
        seller_id = await _seed_market_persona(
            conn,
            name="Scout Seller",
            role_class="scout",
            reputation="0.820",
            credits="20.00",
        )
        first_buyer_id = await _seed_market_persona(
            conn,
            name="Primary Buyer",
            role_class="researcher",
            reputation="0.700",
            credits="120.00",
        )
        second_buyer_id = await _seed_market_persona(
            conn,
            name="Secondary Buyer",
            role_class="synthesizer",
            reputation="0.760",
            credits="95.00",
        )

        await seed_market_templates(conn)
        objective_ids = await ensure_market_objectives(conn)
        target_objective_id = uuid4()
        await conn.execute(
            objectives.insert().values(
                objective_id=target_objective_id,
                title="Marketplace target objective",
                description="Target for bounded service execution.",
                objective_type="strategic",
                impact_level="routine",
                priority=6,
                status="active",
                proposed_by_type="human",
                approved_by_type="system",
            )
        )
        template = (
            await conn.execute(
                sa.select(market_templates).where(market_templates.c.template_code == "scout_package")
            )
        ).first()
        assert template is not None

        asset_id = (
            await conn.execute(
                market_assets.insert()
                .values(
                    template_id=template.template_id,
                    owner_persona_id=seller_id,
                    crafted_by_persona_id=seller_id,
                    asset_kind=template.listing_kind,
                    title="Scout Package",
                    description=template.description,
                    quantity_available=1,
                )
                .returning(market_assets.c.asset_id)
            )
        ).scalar_one()
        await conn.execute(
            marketplace_listings.insert().values(
                asset_id=asset_id,
                seller_persona_id=seller_id,
                template_id=template.template_id,
                listing_kind=template.listing_kind,
                price=Decimal("20.00"),
                quantity_available=1,
                description=template.description,
                metadata_json={"template_code": "scout_package", "sale_channel": "primary_market"},
            )
        )

        first_purchase_count = await maybe_submit_purchases(
            conn,
            settings=runtime_settings,
            objective_id=objective_ids["marketplace"],
        )
        pending_contract = (
            await conn.execute(
                sa.select(service_contracts).where(
                    service_contracts.c.status == "pending_fulfillment",
                    service_contracts.c.seller_persona_id == seller_id,
                )
            )
        ).first()
        assert pending_contract is not None
        assert pending_contract.buyer_persona_id == first_buyer_id

        contract_assets = (
            await conn.execute(
                sa.select(market_assets).where(
                    market_assets.c.owner_persona_id == first_buyer_id,
                )
            )
        ).fetchall()
        contract_asset = next(
            (row for row in contract_assets if (row.metadata_json or {}).get("asset_class") == "contract_right"),
            None,
        )
        assert contract_asset is not None

        relisted = await maybe_relist_owned_assets(
            conn,
            settings=runtime_settings,
            objective_id=objective_ids["marketplace"],
        )
        second_purchase_count = await maybe_submit_purchases(
            conn,
            settings=runtime_settings,
            objective_id=objective_ids["marketplace"],
        )
        transferred_contract = (
            await conn.execute(
                sa.select(service_contracts).where(
                    service_contracts.c.contract_id == pending_contract.contract_id
                )
            )
        ).first()
        transferred_asset = (
            await conn.execute(
                sa.select(market_assets).where(
                    market_assets.c.asset_id == contract_asset.asset_id
                )
            )
        ).first()
        fulfilled, refunded = await process_service_contracts(conn, settings=runtime_settings)
        fulfilled_contract = (
            await conn.execute(
                sa.select(service_contracts.c.status).where(
                    service_contracts.c.contract_id == pending_contract.contract_id
                )
            )
        ).first()
        seller_reputation = await conn.scalar(
            sa.select(agent_personas.c.reputation_score).where(agent_personas.c.persona_id == seller_id)
        )
        reseller_reputation = await conn.scalar(
            sa.select(agent_personas.c.reputation_score).where(agent_personas.c.persona_id == first_buyer_id)
        )

    assert first_purchase_count >= 1
    assert relisted >= 1
    assert second_purchase_count >= 1
    assert transferred_contract is not None
    assert transferred_contract.buyer_persona_id == second_buyer_id
    assert transferred_asset is not None
    assert transferred_asset.owner_persona_id == second_buyer_id
    assert fulfilled >= 1
    assert refunded == 0
    assert fulfilled_contract is not None
    assert fulfilled_contract.status == "fulfilled"
    assert Decimal(str(seller_reputation)) > Decimal("0.820")
    assert Decimal(str(reseller_reputation)) > Decimal("0.700")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_settle_expired_instruments_marks_positions_and_credits_payouts(clean_database):
    engine = clean_database

    async with engine.begin() as conn:
        holder_id = await _seed_market_persona(
            conn,
            name="Settlement Holder",
            role_class="researcher",
            reputation="0.760",
            credits="50.00",
        )
        objective_id = uuid4()
        await conn.execute(
            objectives.insert().values(
                objective_id=objective_id,
                title="Settlement target objective",
                description="This objective determines settlement value.",
                objective_type="strategic",
                impact_level="routine",
                priority=5,
                status="completed",
                proposed_by_type="human",
                approved_by_type="system",
                completed_at=datetime.now(UTC),
            )
        )
        instrument_id = (
            await conn.execute(
                market_instruments.insert()
                .values(
                    symbol="OBJ-SETTLE",
                    name="Objective Note: Settlement target objective",
                    family="objective_note",
                    underlying_objective_id=objective_id,
                    settlement_status="open",
                    last_trade_price=Decimal("55.00"),
                    mark_price=Decimal("55.00"),
                    expiry_at=datetime.now(UTC) - timedelta(minutes=1),
                    settlement_at=datetime.now(UTC) - timedelta(minutes=1),
                )
                .returning(market_instruments.c.instrument_id)
            )
        ).scalar_one()
        position_id = (
            await conn.execute(
                market_positions.insert()
                .values(
                    instrument_id=instrument_id,
                    persona_id=holder_id,
                    net_quantity=Decimal("2.0000"),
                    average_entry_price=Decimal("40.00"),
                    market_value=Decimal("110.00"),
                )
                .returning(market_positions.c.position_id)
            )
        ).scalar_one()
        reservation_id = (
            await conn.execute(
                market_reservations.insert()
                .values(
                    persona_id=holder_id,
                    reservation_type="order_cash",
                    instrument_id=instrument_id,
                    reserved_amount=Decimal("10.00"),
                    remaining_amount=Decimal("10.00"),
                    memo="Release on settlement",
                )
                .returning(market_reservations.c.reservation_id)
            )
        ).scalar_one()

        settled = await settle_expired_instruments(conn)
        instrument_row = (
            await conn.execute(
                sa.select(
                    market_instruments.c.settlement_status,
                    market_instruments.c.settlement_value,
                    market_instruments.c.mark_price,
                ).where(market_instruments.c.instrument_id == instrument_id)
            )
        ).first()
        position_row = (
            await conn.execute(
                sa.select(market_positions.c.net_quantity, market_positions.c.market_value).where(
                    market_positions.c.position_id == position_id
                )
            )
        ).first()
        reservation_row = (
            await conn.execute(
                sa.select(market_reservations.c.status, market_reservations.c.remaining_amount).where(
                    market_reservations.c.reservation_id == reservation_id
                )
            )
        ).first()
        payout_amount = await conn.scalar(
            sa.select(sa.func.sum(economy_ledger.c.amount)).where(
                economy_ledger.c.to_persona_id == holder_id,
                economy_ledger.c.transaction_type == "security_settlement_payout",
            )
        )

    assert settled == 1
    assert instrument_row is not None
    assert instrument_row.settlement_status == "settled"
    assert Decimal(str(instrument_row.settlement_value)) == Decimal("90.00")
    assert Decimal(str(instrument_row.mark_price)) == Decimal("90.00")
    assert position_row is not None
    assert Decimal(str(position_row.net_quantity)) == Decimal("0.0000")
    assert Decimal(str(position_row.market_value)) == Decimal("0.00")
    assert reservation_row is not None
    assert reservation_row.status == "released"
    assert Decimal(str(reservation_row.remaining_amount)) == Decimal("0.00")
    assert Decimal(str(payout_amount or 0)) == Decimal("180.00")
