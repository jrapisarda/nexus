"""Securities exchange read APIs for the NEXUS observatory."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from nexus_core.database import get_connection
from nexus_core.market.service import (
    get_market_instruments,
    get_order_book,
    get_positions,
    get_securities_overview,
    get_trades,
)

from nexus_api.schemas import (
    MarketInstrumentResponse,
    OrderBookLevelResponse,
    OrderBookResponse,
    PositionResponse,
    SecuritiesOverviewResponse,
    TradeResponse,
)


router = APIRouter(prefix="/api/securities", tags=["securities"])


@router.get("/overview", response_model=SecuritiesOverviewResponse)
async def securities_overview():
    async with get_connection() as conn:
        payload = await get_securities_overview(conn)
    return SecuritiesOverviewResponse(**payload)


@router.get("/instruments", response_model=list[MarketInstrumentResponse])
async def securities_instruments(limit: int = Query(50, ge=1, le=200)):
    async with get_connection() as conn:
        rows = await get_market_instruments(conn, limit=limit)
    return [MarketInstrumentResponse(**row) for row in rows]


@router.get("/order-book", response_model=OrderBookResponse)
async def securities_order_book(instrument_id: UUID | None = Query(None)):
    async with get_connection() as conn:
        payload = await get_order_book(conn, instrument_id=instrument_id)
    return OrderBookResponse(
        instrument_id=payload["instrument_id"],
        instrument_symbol=payload["instrument_symbol"],
        bids=[OrderBookLevelResponse(**row) for row in payload["bids"]],
        asks=[OrderBookLevelResponse(**row) for row in payload["asks"]],
    )


@router.get("/trades", response_model=list[TradeResponse])
async def securities_trades(limit: int = Query(50, ge=1, le=200)):
    async with get_connection() as conn:
        rows = await get_trades(conn, limit=limit)
    return [TradeResponse(**row) for row in rows]


@router.get("/positions", response_model=list[PositionResponse])
async def securities_positions(limit: int = Query(50, ge=1, le=200)):
    async with get_connection() as conn:
        rows = await get_positions(conn, limit=limit)
    return [PositionResponse(**row) for row in rows]
