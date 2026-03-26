"""Add autonomous marketplace and securities exchange schema.

Revision ID: 005
Revises: 004
Create Date: 2026-03-20
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "persona_market_profiles"):
        op.create_table(
            "persona_market_profiles",
            sa.Column(
                "persona_id",
                sa.Uuid,
                sa.ForeignKey("agent_personas.persona_id"),
                primary_key=True,
            ),
            sa.Column("risk_tier", sa.VARCHAR(20), nullable=False, server_default="standard"),
            sa.Column("max_open_orders", sa.Integer, nullable=False, server_default=sa.text("4")),
            sa.Column(
                "max_position_notional",
                sa.Numeric(12, 2),
                nullable=False,
                server_default=sa.text("150.00"),
            ),
            sa.Column(
                "collateral_ratio",
                sa.Numeric(5, 2),
                nullable=False,
                server_default=sa.text("1.50"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "market_templates"):
        op.create_table(
            "market_templates",
            sa.Column("template_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("template_code", sa.VARCHAR(80), nullable=False, unique=True),
            sa.Column("template_kind", sa.VARCHAR(20), nullable=False),
            sa.Column("listing_kind", sa.VARCHAR(30), nullable=False),
            sa.Column("title", sa.VARCHAR(255), nullable=False),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("settlement_hook", sa.VARCHAR(50), nullable=False),
            sa.Column("fulfillment_mode", sa.VARCHAR(30), nullable=False),
            sa.Column("privilege_boundary", sa.VARCHAR(50), nullable=False),
            sa.Column("allowed_custom_fields", sa.JSON, server_default=sa.text("'[]'::jsonb")),
            sa.Column("craft_cost", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("default_price", sa.Numeric(12, 2), nullable=False, server_default=sa.text("1.00")),
            sa.Column("default_quantity", sa.Integer, nullable=False, server_default=sa.text("1")),
            sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "market_assets"):
        op.create_table(
            "market_assets",
            sa.Column("asset_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("template_id", sa.Uuid, sa.ForeignKey("market_templates.template_id"), nullable=False),
            sa.Column("owner_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("crafted_by_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("asset_kind", sa.VARCHAR(30), nullable=False),
            sa.Column("title", sa.VARCHAR(255), nullable=False),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("quantity_available", sa.Integer, nullable=False, server_default=sa.text("1")),
            sa.Column("transferable", sa.Boolean, nullable=False, server_default=sa.text("true")),
            sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "marketplace_listings"):
        op.create_table(
            "marketplace_listings",
            sa.Column("listing_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("asset_id", sa.Uuid, sa.ForeignKey("market_assets.asset_id"), nullable=False),
            sa.Column("seller_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("template_id", sa.Uuid, sa.ForeignKey("market_templates.template_id"), nullable=False),
            sa.Column("listing_kind", sa.VARCHAR(30), nullable=False),
            sa.Column("price", sa.Numeric(12, 2), nullable=False),
            sa.Column("quantity_available", sa.Integer, nullable=False, server_default=sa.text("1")),
            sa.Column("audience", sa.JSON, server_default=sa.text("'[]'::jsonb")),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "service_contracts"):
        op.create_table(
            "service_contracts",
            sa.Column("contract_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("listing_id", sa.Uuid, sa.ForeignKey("marketplace_listings.listing_id"), nullable=False),
            sa.Column("buyer_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("seller_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("reservation_id", sa.Uuid, nullable=True),
            sa.Column("target_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
            sa.Column("target_finding_id", sa.Uuid, sa.ForeignKey("findings.finding_id"), nullable=True),
            sa.Column("service_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
            sa.Column("status", sa.VARCHAR(30), nullable=False, server_default="pending_fulfillment"),
            sa.Column("agreed_price", sa.Numeric(12, 2), nullable=False),
            sa.Column("quantity", sa.Integer, nullable=False, server_default=sa.text("1")),
            sa.Column("service_payload", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("fulfillment_summary", sa.Text, nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_table(inspector, "market_instruments"):
        op.create_table(
            "market_instruments",
            sa.Column("instrument_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("symbol", sa.VARCHAR(32), nullable=False, unique=True),
            sa.Column("name", sa.VARCHAR(255), nullable=False),
            sa.Column("family", sa.VARCHAR(30), nullable=False),
            sa.Column("issuer_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
            sa.Column("underlying_objective_id", sa.Uuid, sa.ForeignKey("objectives.objective_id"), nullable=True),
            sa.Column("underlying_finding_id", sa.Uuid, sa.ForeignKey("findings.finding_id"), nullable=True),
            sa.Column("underlying_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=True),
            sa.Column("risk_tier", sa.VARCHAR(20), nullable=False, server_default="standard"),
            sa.Column("halted", sa.Boolean, nullable=False, server_default=sa.text("false")),
            sa.Column("settlement_status", sa.VARCHAR(20), nullable=False, server_default="open"),
            sa.Column("settlement_value", sa.Numeric(12, 2), nullable=True),
            sa.Column("last_trade_price", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("mark_price", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("expiry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("settlement_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "market_orders"):
        op.create_table(
            "market_orders",
            sa.Column("order_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("instrument_id", sa.Uuid, sa.ForeignKey("market_instruments.instrument_id"), nullable=False),
            sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("side", sa.VARCHAR(10), nullable=False),
            sa.Column("order_type", sa.VARCHAR(10), nullable=False, server_default="limit"),
            sa.Column("price", sa.Numeric(12, 2), nullable=False),
            sa.Column("quantity", sa.Numeric(12, 4), nullable=False, server_default=sa.text("1.0000")),
            sa.Column("filled_quantity", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0.0000")),
            sa.Column("reservation_id", sa.Uuid, nullable=True),
            sa.Column("risk_tier", sa.VARCHAR(20), nullable=False, server_default="standard"),
            sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="open"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_table(inspector, "market_trades"):
        op.create_table(
            "market_trades",
            sa.Column("trade_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("instrument_id", sa.Uuid, sa.ForeignKey("market_instruments.instrument_id"), nullable=False),
            sa.Column("buy_order_id", sa.Uuid, sa.ForeignKey("market_orders.order_id"), nullable=False),
            sa.Column("sell_order_id", sa.Uuid, sa.ForeignKey("market_orders.order_id"), nullable=False),
            sa.Column("buyer_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("seller_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("price", sa.Numeric(12, 2), nullable=False),
            sa.Column("quantity", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0.0000")),
            sa.Column("notional", sa.Numeric(12, 2), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "market_positions"):
        op.create_table(
            "market_positions",
            sa.Column("position_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("instrument_id", sa.Uuid, sa.ForeignKey("market_instruments.instrument_id"), nullable=False),
            sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("net_quantity", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0.0000")),
            sa.Column("average_entry_price", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("realized_pnl", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("market_value", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint(
                "instrument_id",
                "persona_id",
                name="uq_market_positions_instrument_persona",
            ),
        )

    if not _has_table(inspector, "market_price_history"):
        op.create_table(
            "market_price_history",
            sa.Column("price_point_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("instrument_id", sa.Uuid, sa.ForeignKey("market_instruments.instrument_id"), nullable=False),
            sa.Column("last_trade_price", sa.Numeric(12, 2), nullable=False),
            sa.Column("mark_price", sa.Numeric(12, 2), nullable=False),
            sa.Column("traded_volume", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0.0000")),
            sa.Column("source", sa.VARCHAR(30), nullable=False, server_default="mark"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(inspector, "market_reservations"):
        op.create_table(
            "market_reservations",
            sa.Column("reservation_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
            sa.Column("reservation_type", sa.VARCHAR(30), nullable=False),
            sa.Column("listing_id", sa.Uuid, sa.ForeignKey("marketplace_listings.listing_id"), nullable=True),
            sa.Column("instrument_id", sa.Uuid, sa.ForeignKey("market_instruments.instrument_id"), nullable=True),
            sa.Column("order_id", sa.Uuid, sa.ForeignKey("market_orders.order_id"), nullable=True),
            sa.Column("related_contract_id", sa.Uuid, nullable=True),
            sa.Column("reserved_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("remaining_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="open"),
            sa.Column("memo", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        )
    else:
        op.alter_column(
            "market_reservations",
            "status",
            existing_type=sa.VARCHAR(20),
            server_default="open",
        )
        op.execute(
            sa.text(
                "UPDATE market_reservations SET status = 'open' WHERE status = 'active'"
            )
        )

    _create_index_if_not_exists(
        "ix_persona_market_profiles_risk_tier",
        "persona_market_profiles",
        "risk_tier",
    )
    _create_index_if_not_exists(
        "ix_market_templates_status_kind",
        "market_templates",
        "status, template_kind",
    )
    _create_index_if_not_exists(
        "ix_market_assets_owner_status",
        "market_assets",
        "owner_persona_id, status, created_at",
    )
    _create_index_if_not_exists(
        "ix_marketplace_listings_status_kind_created",
        "marketplace_listings",
        "status, listing_kind, created_at",
    )
    _create_index_if_not_exists(
        "ix_marketplace_listings_seller_status",
        "marketplace_listings",
        "seller_persona_id, status, created_at",
    )
    _create_index_if_not_exists(
        "ix_service_contracts_status_created",
        "service_contracts",
        "status, created_at",
    )
    _create_index_if_not_exists(
        "ix_service_contracts_targets",
        "service_contracts",
        "target_objective_id, target_finding_id",
    )
    _create_index_if_not_exists(
        "ix_market_instruments_family_status",
        "market_instruments",
        "family, settlement_status, halted",
    )
    _create_index_if_not_exists(
        "ix_market_orders_book_scan",
        "market_orders",
        "instrument_id, status, side, price, created_at",
    )
    _create_index_if_not_exists(
        "ix_market_orders_persona_status",
        "market_orders",
        "persona_id, status, created_at",
    )
    _create_index_if_not_exists(
        "ix_market_trades_instrument_created",
        "market_trades",
        "instrument_id, created_at",
    )
    _create_index_if_not_exists(
        "ix_market_positions_persona",
        "market_positions",
        "persona_id, updated_at",
    )
    _create_index_if_not_exists(
        "ix_market_price_history_instrument_created",
        "market_price_history",
        "instrument_id, created_at",
    )
    _create_index_if_not_exists(
        "ix_market_reservations_persona_status",
        "market_reservations",
        "persona_id, status, created_at",
    )
    _create_index_if_not_exists(
        "ix_market_reservations_refs",
        "market_reservations",
        "listing_id, instrument_id, order_id",
    )


def downgrade() -> None:
    for index_name in [
        "ix_market_reservations_refs",
        "ix_market_reservations_persona_status",
        "ix_market_price_history_instrument_created",
        "ix_market_positions_persona",
        "ix_market_trades_instrument_created",
        "ix_market_orders_persona_status",
        "ix_market_orders_book_scan",
        "ix_market_instruments_family_status",
        "ix_service_contracts_targets",
        "ix_service_contracts_status_created",
        "ix_marketplace_listings_seller_status",
        "ix_marketplace_listings_status_kind_created",
        "ix_market_assets_owner_status",
        "ix_market_templates_status_kind",
        "ix_persona_market_profiles_risk_tier",
    ]:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {index_name}"))

    for table_name in [
        "market_reservations",
        "market_price_history",
        "market_positions",
        "market_trades",
        "market_orders",
        "market_instruments",
        "service_contracts",
        "marketplace_listings",
        "market_assets",
        "market_templates",
        "persona_market_profiles",
    ]:
        if _has_table(sa.inspect(op.get_bind()), table_name):
            op.drop_table(table_name)


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _create_index_if_not_exists(index_name: str, table_name: str, columns_sql: str) -> None:
    op.execute(
        sa.text(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {table_name} ({columns_sql})"
        )
    )
