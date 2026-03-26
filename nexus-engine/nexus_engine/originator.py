import asyncio
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from nexus_core.config import NexusSettings
from nexus_core.models.instances import agent_instances
from nexus_core.models.findings import findings
from nexus_core.llm.client import KimiClient
from nexus_core.models.objectives import objectives
from nexus_core.utils.events import emit_event
from nexus_engine.decomposer import decompose_objective
from nexus_engine.dispatcher import Dispatcher
from nexus_engine.integrator import (
    _reconcile_objective_state_from_finding,
    integrate_results,
)
import structlog

logger = structlog.get_logger(__name__)


class OriginatorLoop:
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
        self._dispatcher = Dispatcher(engine, kimi_client, settings, shutdown_event)
        self._paused = False

    async def run(self):
        """Main originator loop -- polls for new objectives and processes them."""
        logger.info("originator_started")
        while not self._shutdown.is_set():
            if self._paused:
                await asyncio.sleep(5)
                continue

            try:
                await self._recover_stale_running_instances()
                await self._reconcile_stranded_objectives()
                await self._resume_revision_requested_objectives()
                await self._process_pending_objectives()
                await self._check_completed_instances()
            except Exception as e:
                logger.error("originator_cycle_error", error=str(e))

            # Poll interval: 5 seconds
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=5.0)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                continue

        logger.info("originator_stopped")

    async def _process_pending_objectives(self):
        """Find and process objectives that need attention."""
        async with self._engine.begin() as conn:
            # Process top-level proposed objectives. Child objectives are handled by the DAG dispatcher.
            result = await conn.execute(
                objectives.select()
                .where(
                    objectives.c.status == "proposed",
                    objectives.c.parent_objective_id.is_(None),
                    objectives.c.objective_type.in_(
                        ["strategic", "tactical", "exploratory"]
                    ),
                )
                .order_by(
                    objectives.c.priority.desc(),
                    objectives.c.created_at.asc(),
                )
            )
            pending = result.fetchall()

        for obj in pending:
            if self._shutdown.is_set():
                break
            await self._process_objective(obj)

    async def _reconcile_stranded_objectives(self):
        """Repair active objectives that have a reviewed finding but no live work."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                sa.select(
                    objectives.c.objective_id,
                    objectives.c.title,
                )
                .where(
                    objectives.c.status == "active",
                    ~sa.exists(
                        sa.select(1)
                        .select_from(agent_instances)
                        .where(
                            agent_instances.c.objective_id == objectives.c.objective_id,
                            agent_instances.c.status.in_(["pending", "running"]),
                        )
                    ),
                )
                .order_by(objectives.c.priority.desc(), objectives.c.created_at.asc())
                .limit(20)
            )
            stranded = result.fetchall()

        for objective in stranded:
            async with self._engine.begin() as conn:
                latest_finding_result = await conn.execute(
                    sa.select(
                        findings.c.finding_id,
                        findings.c.status,
                    )
                    .where(
                        findings.c.objective_id == objective.objective_id,
                        findings.c.status != "superseded",
                    )
                    .order_by(findings.c.created_at.desc())
                    .limit(1)
                )
                latest_finding = latest_finding_result.first()

            if latest_finding is None:
                continue

            recovered_status = await _reconcile_objective_state_from_finding(
                self._engine,
                self._kimi,
                objective_id=objective.objective_id,
                finding_status=latest_finding.status,
                finding_id=latest_finding.finding_id,
                settings=self._settings,
                recovery_reason="originator_stranded_objective_sweep",
            )
            if recovered_status is not None:
                logger.info(
                    "stranded_objective_reconciled",
                    objective_id=str(objective.objective_id),
                    title=objective.title,
                    recovered_status=recovered_status,
                )

    async def _resume_revision_requested_objectives(self):
        """Resume stranded objectives that were waiting for a revision rerun."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                objectives.select()
                .where(objectives.c.status == "revision_requested")
                .order_by(
                    objectives.c.priority.desc(),
                    objectives.c.created_at.asc(),
                )
                .limit(10)
            )
            revision_requested = result.fetchall()

        for obj in revision_requested:
            if self._shutdown.is_set():
                break
            logger.info(
                "resuming_revision_requested_objective",
                objective_id=str(obj.objective_id),
                title=obj.title,
            )
            try:
                await self._dispatcher.dispatch_objective(obj.objective_id)
            except Exception as exc:
                logger.error(
                    "resume_revision_requested_failed",
                    objective_id=str(obj.objective_id),
                    error=str(exc),
                )

    async def _process_objective(self, obj):
        """Process a single objective: approve -> decompose -> dispatch."""
        obj_id = obj.objective_id
        logger.info(
            "processing_objective",
            objective_id=str(obj_id),
            title=obj.title,
        )

        async with self._engine.begin() as conn:
            approved_by_type = obj.approved_by_type
            if approved_by_type is None:
                approved_by_type = (
                    "self"
                    if obj.objective_type == "exploratory"
                    and obj.proposed_by_type == "agent"
                    else "system"
                )

            # Approve the objective
            await conn.execute(
                objectives.update()
                .where(objectives.c.objective_id == obj_id)
                .values(status="active", approved_by_type=approved_by_type)
            )
            await emit_event(
                conn,
                "objective_approved",
                entity_id=obj_id,
                entity_type="objective",
            )

        # Decompose into sub-objectives
        try:
            dag = await decompose_objective(
                self._engine, self._kimi, obj_id, self._settings
            )
            logger.info(
                "objective_decomposed",
                objective_id=str(obj_id),
                sub_count=len(dag),
            )
        except Exception as e:
            logger.error(
                "decomposition_failed",
                objective_id=str(obj_id),
                error=str(e),
            )
            async with self._engine.begin() as conn:
                await conn.execute(
                    objectives.update()
                    .where(objectives.c.objective_id == obj_id)
                    .values(
                        status="failed",
                        escalation_reason=f"Decomposition failed: {e}",
                    )
                )
            return

        # Dispatch ready sub-objectives
        await self._dispatcher.dispatch_dag(obj_id)

    async def _check_completed_instances(self):
        """Check for completed agent instances and integrate their results.

        Market-only instances (no findings) are bulk-integrated to prevent
        them from starving research instance processing.
        """
        MARKET_SPAWN_REASONS = {
            "market_listing_decision", "market_purchase_decision",
            "market_order_decision", "market_relisting_decision",
            "security_trade_decision", "market_service_fulfillment",
        }

        # 1. Bulk-integrate market instances that have no findings
        async with self._engine.begin() as conn:
            market_result = await conn.execute(
                sa.select(agent_instances.c.instance_id)
                .where(
                    agent_instances.c.status == "completed",
                    agent_instances.c.spawn_reason.in_(list(MARKET_SPAWN_REASONS)),
                )
                .limit(500)
            )
            market_ids = [row.instance_id for row in market_result]
            if market_ids:
                await conn.execute(
                    agent_instances.update()
                    .where(agent_instances.c.instance_id.in_(market_ids))
                    .values(status="integrated")
                )
                if len(market_ids) >= 100:
                    logger.debug("bulk_integrated_market_instances", count=len(market_ids))

        # 2. Process research instances that may have findings
        async with self._engine.begin() as conn:
            result = await conn.execute(
                agent_instances.select()
                .where(
                    agent_instances.c.status == "completed",
                    agent_instances.c.spawn_reason.notin_(list(MARKET_SPAWN_REASONS)),
                )
                .order_by(agent_instances.c.completed_at.asc())
                .limit(10)
            )
            completed = result.fetchall()

        for instance in completed:
            if self._shutdown.is_set():
                break
            try:
                await integrate_results(
                    self._engine,
                    self._kimi,
                    instance.instance_id,
                    self._settings,
                )
            except Exception as e:
                logger.error(
                    "integration_failed",
                    instance_id=str(instance.instance_id),
                    error=str(e),
                )

        # 3. Fallback: if no research instances, process any remaining completed
        if not completed:
            async with self._engine.begin() as conn:
                result = await conn.execute(
                    agent_instances.select()
                    .where(agent_instances.c.status == "completed")
                    .order_by(agent_instances.c.completed_at.asc())
                    .limit(10)
                )
                remaining = result.fetchall()

            for instance in remaining:
                if self._shutdown.is_set():
                    break
                try:
                    await integrate_results(
                        self._engine,
                        self._kimi,
                        instance.instance_id,
                        self._settings,
                    )
                except Exception as e:
                    logger.error(
                        "integration_failed",
                        instance_id=str(instance.instance_id),
                        error=str(e),
                    )

    async def _recover_stale_running_instances(self):
        """Fail and recover orphaned running instances whose heartbeat expired."""
        cutoff = datetime.now(UTC) - timedelta(
            seconds=self._settings.STALE_INSTANCE_TIMEOUT_SECS
        )

        async with self._engine.begin() as conn:
            result = await conn.execute(
                sa.select(
                    agent_instances.c.instance_id,
                    agent_instances.c.objective_id,
                    agent_instances.c.spawn_reason,
                    agent_instances.c.input_prompt,
                    objectives.c.status.label("objective_status"),
                )
                .join(objectives, objectives.c.objective_id == agent_instances.c.objective_id)
                .where(
                    agent_instances.c.status == "running",
                    agent_instances.c.last_heartbeat < cutoff,
                )
                .order_by(agent_instances.c.last_heartbeat.asc())
                .limit(10)
            )
            stale_instances = result.fetchall()

        for instance in stale_instances:
            work_type = self._classify_instance_work(instance)
            async with self._engine.begin() as conn:
                update_result = await conn.execute(
                    agent_instances.update()
                    .where(
                        agent_instances.c.instance_id == instance.instance_id,
                        agent_instances.c.status == "running",
                    )
                    .values(
                        status="failed",
                        completed_at=sa.func.now(),
                        error_message=(
                            "Recovered stale running instance after heartbeat timeout"
                        ),
                    )
                )
                if update_result.rowcount == 0:
                    continue

                if work_type == "objective_execution":
                    await conn.execute(
                        objectives.update()
                        .where(objectives.c.objective_id == instance.objective_id)
                        .values(assigned_to=None)
                    )

                await emit_event(
                    conn,
                    "stale_instance_recovered",
                    entity_id=instance.instance_id,
                    entity_type="instance",
                    payload={
                        "objective_id": str(instance.objective_id),
                        "work_type": work_type,
                        "requeued": work_type in {"objective_execution", "final_synthesis"},
                    },
                )

            logger.warning(
                "stale_instance_recovered",
                instance_id=str(instance.instance_id),
                objective_id=str(instance.objective_id),
                work_type=work_type,
            )

            try:
                if work_type == "objective_execution":
                    await self._dispatcher.dispatch_objective(instance.objective_id)
                elif work_type == "final_synthesis":
                    from nexus_engine.integrator import _synthesize_parent_objective

                    await _synthesize_parent_objective(
                        self._engine,
                        self._kimi,
                        instance.objective_id,
                        settings=self._settings,
                    )
            except Exception as exc:
                logger.error(
                    "stale_instance_recovery_failed",
                    instance_id=str(instance.instance_id),
                    objective_id=str(instance.objective_id),
                    work_type=work_type,
                    error=str(exc),
                )

    @staticmethod
    def _classify_instance_work(instance) -> str:
        """Classify a running instance for recovery decisions."""
        spawn_reason = (getattr(instance, "spawn_reason", None) or "").strip()
        if spawn_reason:
            return spawn_reason

        prompt = (getattr(instance, "input_prompt", None) or "").lstrip()
        if prompt.startswith("## Finding to Review"):
            return "peer_review"
        if prompt.startswith("## Validated Finding to Challenge"):
            return "red_team_challenge"
        if "Generate a plausible-but-wrong finding as JSON" in prompt:
            return "infiltration_test"
        return "objective_execution"

    def pause(self):
        self._paused = True
        logger.info("originator_paused")

    def resume(self):
        self._paused = False
        logger.info("originator_resumed")
