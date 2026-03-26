import asyncio
import signal
import sys

from nexus_core.config import get_settings
from nexus_core.database import get_engine, dispose_engine, ensure_database_compatibility
from nexus_core.utils.logging import configure_logging, get_logger
from nexus_core.utils.cost import CostGuard
from nexus_core.llm.client import KimiClient

logger = get_logger(__name__)


async def main():
    settings = get_settings()
    configure_logging(settings)

    logger.info(
        "nexus_engine_starting",
        model=settings.MOONSHOT_MODEL,
        budget=str(settings.BUDGET_CEILING_USD),
    )

    engine = get_engine(settings)
    await ensure_database_compatibility(settings)
    cost_guard = CostGuard.from_settings(settings)
    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_CALLS)
    shutdown_event = asyncio.Event()

    kimi_client = KimiClient(settings, cost_guard, semaphore, shutdown_event)

    # Register signal handlers
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown_event.set)
    else:
        # Windows: handle SIGINT via KeyboardInterrupt
        pass

    try:
        from nexus_engine.market_loop import MarketLoop
        from nexus_engine.originator import OriginatorLoop
        from nexus_engine.scheduler import SchedulerLoop

        originator = OriginatorLoop(engine, kimi_client, settings, shutdown_event)
        scheduler = SchedulerLoop(engine, kimi_client, settings, shutdown_event)
        market_loop = MarketLoop(engine, settings, shutdown_event)

        # Run until shutdown
        await asyncio.gather(
            originator.run(),
            scheduler.run(),
            market_loop.run(),
            _orphan_cleanup_loop(engine, settings, shutdown_event),
            _shutdown_watcher(shutdown_event),
        )
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_received")
        shutdown_event.set()
    except Exception as e:
        logger.error("engine_fatal_error", error=str(e))
        raise
    finally:
        logger.info("nexus_engine_shutting_down")
        await kimi_client.close()
        await dispose_engine()
        logger.info("nexus_engine_stopped")


async def _orphan_cleanup_loop(engine, settings, shutdown_event: asyncio.Event):
    """Periodically clean up orphan file attachments (uploaded but never linked)."""
    from pathlib import Path

    import sqlalchemy as sa

    from nexus_core.models.attachments import objective_attachments

    interval = 3600  # 1 hour
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=float(interval))
            break  # shutdown requested
        except asyncio.TimeoutError:
            pass

        try:
            async with engine.begin() as conn:
                # Find orphans older than 1 hour
                cutoff = sa.text("NOW() - INTERVAL '1 hour'")
                result = await conn.execute(
                    sa.select(
                        objective_attachments.c.attachment_id,
                        objective_attachments.c.stored_path,
                        objective_attachments.c.extraction_text_path,
                    ).where(
                        objective_attachments.c.objective_id.is_(None),
                        objective_attachments.c.created_at < cutoff,
                    )
                )
                orphans = result.fetchall()

                if not orphans:
                    continue

                # Delete files from disk
                freed_bytes = 0
                for orphan in orphans:
                    for path_str in [orphan.stored_path, orphan.extraction_text_path]:
                        if path_str:
                            p = Path(path_str)
                            if p.exists():
                                freed_bytes += p.stat().st_size
                                p.unlink(missing_ok=True)

                # Delete DB rows
                await conn.execute(
                    objective_attachments.delete().where(
                        objective_attachments.c.attachment_id.in_(
                            [o.attachment_id for o in orphans]
                        )
                    )
                )

                logger.info(
                    "orphan_files_cleaned",
                    count=len(orphans),
                    total_bytes_freed=freed_bytes,
                )

        except Exception as exc:
            logger.error("orphan_cleanup_error", error=str(exc))


async def _shutdown_watcher(shutdown_event: asyncio.Event):
    """Wait for shutdown signal and exit."""
    await shutdown_event.wait()
    logger.info("shutdown_signal_received")
    # Give other tasks time to clean up
    await asyncio.sleep(2)


def run():
    """Entry point for nexus-engine command."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
