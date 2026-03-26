"""Autonomous market orchestrator for the NEXUS engine."""

from __future__ import annotations

import asyncio

import structlog

from nexus_core.config import NexusSettings
from nexus_core.market.service import run_market_cycle


logger = structlog.get_logger(__name__)


class MarketLoop:
    """Short-interval loop that advances the marketplace and securities exchange."""

    def __init__(
        self,
        engine,
        settings: NexusSettings,
        shutdown_event: asyncio.Event,
    ):
        self._engine = engine
        self._settings = settings
        self._shutdown = shutdown_event
        self._cycle_count = 0

    async def run(self):
        logger.info("market_loop_started")
        while not self._shutdown.is_set():
            self._cycle_count += 1
            try:
                async with self._engine.begin() as conn:
                    summary = await run_market_cycle(conn, self._settings, cycle_tick=self._cycle_count)
                if any(summary.values()):
                    logger.info("market_cycle_complete", **summary)
            except Exception as exc:
                logger.error("market_cycle_failed", error=str(exc))

            if self._shutdown.is_set():
                break
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=float(self._settings.MARKET_LOOP_INTERVAL_SECS),
                )
                break
            except asyncio.TimeoutError:
                continue

        logger.info("market_loop_stopped")
