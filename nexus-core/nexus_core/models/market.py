"""Marketplace and securities exchange table definitions."""

import sqlalchemy as sa

from nexus_core.models import metadata


persona_market_profiles = sa.Table(
    "persona_market_profiles",
    metadata,
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
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    ),
)


market_templates = sa.Table(
    "market_templates",
    metadata,
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
    sa.Column(
        "default_price",
        sa.Numeric(12, 2),
        nullable=False,
        server_default=sa.text("1.00"),
    ),
    sa.Column("default_quantity", sa.Integer, nullable=False, server_default=sa.text("1")),
    sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "allowed_crafter_roles",
        sa.JSON,
        nullable=False,
        server_default=sa.text("""'["consolidator","synthesizer","tool_forger","architect"]'::jsonb"""),
    ),
    sa.Column("max_crafts_per_cycle", sa.Integer, nullable=True),
    sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active"),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)


market_assets = sa.Table(
    "market_assets",
    metadata,
    sa.Column("asset_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("template_id", sa.Uuid, sa.ForeignKey("market_templates.template_id"), nullable=False),
    sa.Column(
        "owner_persona_id",
        sa.Uuid,
        sa.ForeignKey("agent_personas.persona_id"),
        nullable=False,
    ),
    sa.Column(
        "crafted_by_persona_id",
        sa.Uuid,
        sa.ForeignKey("agent_personas.persona_id"),
        nullable=False,
    ),
    sa.Column("asset_kind", sa.VARCHAR(30), nullable=False),
    sa.Column("title", sa.VARCHAR(255), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("quantity_available", sa.Integer, nullable=False, server_default=sa.text("1")),
    sa.Column("transferable", sa.Boolean, nullable=False, server_default=sa.text("true")),
    sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
    sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active"),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    ),
)


marketplace_listings = sa.Table(
    "marketplace_listings",
    metadata,
    sa.Column("listing_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("asset_id", sa.Uuid, sa.ForeignKey("market_assets.asset_id"), nullable=False),
    sa.Column(
        "seller_persona_id",
        sa.Uuid,
        sa.ForeignKey("agent_personas.persona_id"),
        nullable=False,
    ),
    sa.Column("template_id", sa.Uuid, sa.ForeignKey("market_templates.template_id"), nullable=False),
    sa.Column("listing_kind", sa.VARCHAR(30), nullable=False),
    sa.Column("price", sa.Numeric(12, 2), nullable=False),
    sa.Column("quantity_available", sa.Integer, nullable=False, server_default=sa.text("1")),
    sa.Column("audience", sa.JSON, server_default=sa.text("'[]'::jsonb")),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
    sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active"),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    ),
)


service_contracts = sa.Table(
    "service_contracts",
    metadata,
    sa.Column("contract_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("listing_id", sa.Uuid, sa.ForeignKey("marketplace_listings.listing_id"), nullable=False),
    sa.Column(
        "buyer_persona_id",
        sa.Uuid,
        sa.ForeignKey("agent_personas.persona_id"),
        nullable=False,
    ),
    sa.Column(
        "seller_persona_id",
        sa.Uuid,
        sa.ForeignKey("agent_personas.persona_id"),
        nullable=False,
    ),
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


market_instruments = sa.Table(
    "market_instruments",
    metadata,
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
    sa.Column("par_value", sa.Numeric(12, 2), nullable=False, server_default=sa.text("50.00")),
    sa.Column("expiry_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("settlement_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("metadata_json", sa.JSON, server_default=sa.text("'{}'::jsonb")),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    ),
)


market_orders = sa.Table(
    "market_orders",
    metadata,
    sa.Column("order_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("instrument_id", sa.Uuid, sa.ForeignKey("market_instruments.instrument_id"), nullable=False),
    sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
    sa.Column("side", sa.VARCHAR(10), nullable=False),
    sa.Column("order_type", sa.VARCHAR(10), nullable=False, server_default="limit"),
    sa.Column("price", sa.Numeric(12, 2), nullable=False),
    sa.Column(
        "quantity",
        sa.Numeric(12, 4),
        nullable=False,
        server_default=sa.text("1.0000"),
    ),
    sa.Column(
        "filled_quantity",
        sa.Numeric(12, 4),
        nullable=False,
        server_default=sa.text("0.0000"),
    ),
    sa.Column("reservation_id", sa.Uuid, nullable=True),
    sa.Column("risk_tier", sa.VARCHAR(20), nullable=False, server_default="standard"),
    sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="open"),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    ),
    sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
)


market_trades = sa.Table(
    "market_trades",
    metadata,
    sa.Column("trade_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("instrument_id", sa.Uuid, sa.ForeignKey("market_instruments.instrument_id"), nullable=False),
    sa.Column("buy_order_id", sa.Uuid, sa.ForeignKey("market_orders.order_id"), nullable=False),
    sa.Column("sell_order_id", sa.Uuid, sa.ForeignKey("market_orders.order_id"), nullable=False),
    sa.Column(
        "buyer_persona_id",
        sa.Uuid,
        sa.ForeignKey("agent_personas.persona_id"),
        nullable=False,
    ),
    sa.Column(
        "seller_persona_id",
        sa.Uuid,
        sa.ForeignKey("agent_personas.persona_id"),
        nullable=False,
    ),
    sa.Column("price", sa.Numeric(12, 2), nullable=False),
    sa.Column(
        "quantity",
        sa.Numeric(12, 4),
        nullable=False,
        server_default=sa.text("0.0000"),
    ),
    sa.Column("notional", sa.Numeric(12, 2), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)


market_positions = sa.Table(
    "market_positions",
    metadata,
    sa.Column("position_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("instrument_id", sa.Uuid, sa.ForeignKey("market_instruments.instrument_id"), nullable=False),
    sa.Column("persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
    sa.Column(
        "net_quantity",
        sa.Numeric(12, 4),
        nullable=False,
        server_default=sa.text("0.0000"),
    ),
    sa.Column(
        "average_entry_price",
        sa.Numeric(12, 2),
        nullable=False,
        server_default=sa.text("0.00"),
    ),
    sa.Column("realized_pnl", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
    sa.Column("market_value", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    ),
    sa.UniqueConstraint("instrument_id", "persona_id", name="uq_market_positions_instrument_persona"),
)


market_price_history = sa.Table(
    "market_price_history",
    metadata,
    sa.Column("price_point_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("instrument_id", sa.Uuid, sa.ForeignKey("market_instruments.instrument_id"), nullable=False),
    sa.Column("last_trade_price", sa.Numeric(12, 2), nullable=False),
    sa.Column("mark_price", sa.Numeric(12, 2), nullable=False),
    sa.Column(
        "traded_volume",
        sa.Numeric(12, 4),
        nullable=False,
        server_default=sa.text("0.0000"),
    ),
    sa.Column("source", sa.VARCHAR(30), nullable=False, server_default="mark"),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)


market_reservations = sa.Table(
    "market_reservations",
    metadata,
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


kg_node_bids = sa.Table(
    "kg_node_bids",
    metadata,
    sa.Column("bid_id", sa.Uuid, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
    sa.Column("node_id", sa.Uuid, sa.ForeignKey("knowledge_graph_nodes.node_id"), nullable=False),
    sa.Column("bidder_persona_id", sa.Uuid, sa.ForeignKey("agent_personas.persona_id"), nullable=False),
    sa.Column("bid_amount", sa.Numeric(12, 2), nullable=False),
    sa.Column("bid_type", sa.VARCHAR(20), nullable=False, server_default="purchase"),
    sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="open"),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
)
