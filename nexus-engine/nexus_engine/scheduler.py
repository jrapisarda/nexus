import asyncio
from decimal import Decimal

import sqlalchemy as sa

from nexus_core.civilization.service import run_civilization_shadow_cycle
from nexus_core.config import NexusSettings
from nexus_core.llm.client import KimiClient
from nexus_core.economy.ledger import apply_rent_decay, apply_wealth_tax
from nexus_core.economy.diversity import check_role_class_minimums
from nexus_core.economy.welfare import distribute_welfare
from nexus_core.knowledge.centrality import refresh_betweenness_scores
from nexus_core.market.node_ownership import (
    apply_node_depreciation,
    distribute_node_yields,
    reset_traversal_counts,
)
from nexus_core.evolution.pruner import run_evolution_cycle
from nexus_core.governance.runtime import process_pending_proposals
from nexus_core.models.objectives import objectives
from nexus_core.review.infiltrator import inject_infiltration
from nexus_core.review.red_team import (
    dispatch_challenge,
    process_challenge,
    select_findings_for_challenge,
)
from nexus_core.scouts.workflow import run_scout_sweep
from nexus_engine.dream_cycle import run_dream_cycle
import structlog

logger = structlog.get_logger(__name__)


class SchedulerLoop:
    def __init__(
        self,
        engine,
        kimi_client: KimiClient,
        settings: NexusSettings,
        shutdown_event: asyncio.Event,
    ):
        self._engine = engine
        self._kimi = kimi_client
        self._settings = settings
        self._shutdown = shutdown_event
        self._tick_count = 0

    async def run(self):
        """Main scheduler loop -- runs periodic tasks."""
        logger.info("scheduler_started")

        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=float(self._settings.RENT_DECAY_INTERVAL_MINS * 60),
                )
                break  # Shutdown
            except asyncio.TimeoutError:
                pass  # Time for periodic tasks

            if self._shutdown.is_set():
                break

            self._tick_count += 1

            # Run periodic tasks
            await self._run_rent_decay()
            await self._run_welfare_distribution()
            await self._maybe_run_wealth_tax()
            await self._recover_stalled_citations()
            await self._check_diversity()
            await self._run_governance_cycle()
            await self._run_red_team_cycle()
            await self._run_civilization_shadow_cycle()
            await self._maybe_infiltration_test()
            await self._maybe_run_evolution()
            await self._run_node_ownership_cycle()
            await self._maybe_run_scout_cycle()
            await self._maybe_dream_cycle()

        logger.info("scheduler_stopped")

    async def _run_rent_decay(self):
        """Apply tiered rent decay to all active personas."""
        try:
            s = self._settings
            async with self._engine.begin() as conn:
                count = await apply_rent_decay(
                    conn,
                    s.RENT_DECAY_RATE,
                    exempt_below=s.RENT_DECAY_EXEMPT_BELOW,
                    rate_low=s.RENT_DECAY_RATE_LOW,
                    rate_mid=s.RENT_DECAY_RATE_MID,
                    rate_high=s.RENT_DECAY_RATE_HIGH,
                    high_above=s.RENT_DECAY_HIGH_ABOVE,
                    welfare_redirect_ratio=s.RENT_WELFARE_REDIRECT_RATIO,
                )
            logger.info("rent_decay_applied", personas_affected=count)
        except Exception as e:
            logger.error("rent_decay_failed", error=str(e))

    async def _run_welfare_distribution(self):
        """Distribute welfare pool credits to low-balance agents."""
        if self._tick_count % max(self._settings.WELFARE_INTERVAL_TICKS, 1) != 0:
            return
        try:
            async with self._engine.begin() as conn:
                count = await distribute_welfare(
                    conn, floor=self._settings.WELFARE_FLOOR_CREDITS
                )
            if count > 0:
                logger.info("welfare_distributed", recipients=count)
        except Exception as e:
            logger.error("welfare_distribution_failed", error=str(e))

    async def _maybe_run_wealth_tax(self):
        """Apply wealth tax on top quartile agents."""
        if self._tick_count % max(self._settings.WEALTH_TAX_INTERVAL_TICKS, 1) != 0:
            return
        try:
            async with self._engine.begin() as conn:
                taxed = await apply_wealth_tax(
                    conn,
                    top_rate=self._settings.WEALTH_TAX_TOP_RATE,
                    mid_rate=self._settings.WEALTH_TAX_MID_RATE,
                )
            if taxed > 0:
                logger.info("wealth_tax_applied", agents_taxed=taxed)
        except Exception as e:
            logger.error("wealth_tax_failed", error=str(e))

    async def _recover_stalled_citations(self):
        """Advance findings stuck in citation_checking to pending_review."""
        try:
            from nexus_core.models.findings import findings
            async with self._engine.begin() as conn:
                stalled = await conn.execute(
                    sa.select(findings.c.finding_id)
                    .where(
                        findings.c.status == "citation_checking",
                        findings.c.citation_check_started_at < sa.func.now() - sa.text("INTERVAL '5 minutes'"),
                    )
                )
                stalled_ids = [row.finding_id for row in stalled]
                for fid in stalled_ids:
                    await conn.execute(
                        findings.update()
                        .where(findings.c.finding_id == fid)
                        .values(
                            status="pending_review",
                            citation_confidence_score=sa.text("0.500"),
                        )
                    )
            if stalled_ids:
                logger.warning("stalled_citations_recovered", count=len(stalled_ids))
        except Exception as e:
            logger.error("stalled_citation_recovery_failed", error=str(e))

    async def _check_diversity(self):
        """Check role class minimums and log warnings."""
        try:
            async with self._engine.begin() as conn:
                below = await check_role_class_minimums(
                    conn, self._settings.MIN_PERSONAS_PER_ROLE_CLASS
                )
            if below:
                logger.warning("role_class_below_minimum", role_classes=below)
        except Exception as e:
            logger.error("diversity_check_failed", error=str(e))

    async def _maybe_dream_cycle(self):
        """Run dream cycle if conditions are met (low activity)."""
        try:
            if self._tick_count % 3 == 0:
                await run_dream_cycle(self._engine, self._kimi)
        except Exception as e:
            logger.error("dream_cycle_failed", error=str(e))

    def increment_objective_count(self):
        self._tick_count += 1

    async def _run_governance_cycle(self):
        if self._tick_count % max(self._settings.GOVERNANCE_INTERVAL_TICKS, 1) != 0:
            return
        try:
            async with self._engine.begin() as conn:
                outcomes = await process_pending_proposals(conn, self._settings)
            if outcomes:
                logger.info("governance_cycle_complete", proposals=len(outcomes))
        except Exception as e:
            logger.error("governance_cycle_failed", error=str(e))

    async def _run_red_team_cycle(self):
        try:
            async with self._engine.begin() as conn:
                finding_ids = await select_findings_for_challenge(
                    conn, sample_rate=self._settings.RED_TEAM_SAMPLE_RATE
                )
                challenged = 0
                for finding_id in finding_ids:
                    report = await dispatch_challenge(conn, self._kimi, finding_id)
                    if report is None:
                        continue
                    await process_challenge(conn, report, finding_id)
                    challenged += 1
            if challenged:
                logger.info("red_team_cycle_complete", challenged=challenged)
        except Exception as e:
            logger.error("red_team_cycle_failed", error=str(e))

    async def _run_civilization_shadow_cycle(self):
        try:
            async with self._engine.begin() as conn:
                summary = await run_civilization_shadow_cycle(conn, self._settings)
            if any(summary.values()):
                logger.info("civilization_shadow_cycle_complete", **summary)
        except Exception as e:
            logger.error("civilization_shadow_cycle_failed", error=str(e))

    async def _maybe_infiltration_test(self):
        if self._tick_count % max(self._settings.INFILTRATION_INTERVAL_TICKS, 1) != 0:
            return
        try:
            async with self._engine.begin() as conn:
                objective_q = await conn.execute(
                    sa.select(objectives.c.objective_id)
                    .where(objectives.c.status == "active")
                    .order_by(objectives.c.priority.desc(), objectives.c.created_at.asc())
                    .limit(1)
                )
                objective = objective_q.one_or_none()
                if objective is not None:
                    await inject_infiltration(conn, self._kimi, objective.objective_id)
        except Exception as e:
            logger.error("infiltration_cycle_failed", error=str(e))

    async def _maybe_run_evolution(self):
        if self._tick_count % max(self._settings.EVOLUTION_INTERVAL_TICKS, 1) != 0:
            return
        try:
            await run_evolution_cycle(self._engine, self._kimi, self._settings)
        except Exception as e:
            logger.error("evolution_cycle_failed", error=str(e))

    async def _run_node_ownership_cycle(self):
        """Run KG node ownership tasks: centrality refresh, yield distribution, depreciation."""
        try:
            async with self._engine.begin() as conn:
                # 1. Refresh betweenness centrality (every 2 ticks)
                if self._tick_count % 2 == 0:
                    await refresh_betweenness_scores(conn)

                # 2. Compute yield pool (5% of recent bounties this cycle)
                from nexus_core.models.economy import economy_ledger
                recent_bounties = await conn.scalar(
                    sa.select(sa.func.coalesce(sa.func.sum(economy_ledger.c.amount), Decimal("0")))
                    .where(
                        economy_ledger.c.transaction_type == "bounty_claim",
                        economy_ledger.c.created_at >= sa.func.now() - sa.text(
                            f"INTERVAL '{self._settings.RENT_DECAY_INTERVAL_MINS} minutes'"
                        ),
                    )
                )
                yield_pool = Decimal(str(recent_bounties)) * self._settings.NODE_YIELD_FROM_BOUNTY_PCT
                if yield_pool > Decimal("0.01"):
                    recipients = await distribute_node_yields(conn, yield_pool)
                    if recipients > 0:
                        logger.info("node_yields_distributed", recipients=recipients, pool=str(yield_pool))

                # 3. Apply depreciation to neglected nodes
                depreciated = await apply_node_depreciation(
                    conn,
                    depreciation_rate=self._settings.NODE_DEPRECIATION_RATE,
                )
                if depreciated > 0:
                    logger.info("node_depreciation_applied", nodes=depreciated)

                # 4. Reset traversal counts for next cycle
                await reset_traversal_counts(conn)

        except Exception as e:
            logger.error("node_ownership_cycle_failed", error=str(e))

    async def _maybe_run_scout_cycle(self):
        if self._tick_count % max(self._settings.SCOUT_SWEEP_INTERVAL_TICKS, 1) != 0:
            return
        try:
            summary = await run_scout_sweep(self._engine, self._settings)
            if summary["persisted_findings"]:
                logger.info(
                    "scout_cycle_complete",
                    persisted=len(summary["persisted_findings"]),
                    proposed_objectives=summary["proposed_objectives"],
                )
        except Exception as e:
            logger.error("scout_cycle_failed", error=str(e))
