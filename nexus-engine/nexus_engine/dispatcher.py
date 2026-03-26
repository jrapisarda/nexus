import asyncio
from uuid import UUID
from graphlib import TopologicalSorter

import numpy as np
import sqlalchemy as sa

from pathlib import Path

from nexus_core.config import NexusSettings
from nexus_core.governance.runtime import ensure_candidate_persona_approved
from nexus_core.knowledge.query import get_context_for_objective
from nexus_core.llm.client import KimiClient
from nexus_core.llm.prompt_builder import PromptBuilder
from nexus_core.llm.response_parser import ResponseParser, StructuredOutputError
from nexus_core.models.attachments import objective_attachments
from nexus_core.models.objectives import objectives
from nexus_core.models.decomposition import objective_decomposition
from nexus_core.models.institutional_memory import institutional_memory
from nexus_core.models.personas import agent_personas
from nexus_core.models.instances import agent_instances
from nexus_core.models.findings import findings
from nexus_core.models.telemetry import agent_telemetry
from nexus_core.review.debugger import diagnose_failure
from nexus_core.utils.cost import calculate_cost_breakdown
from nexus_core.utils.embeddings import EmbeddingService
from nexus_core.utils.events import emit_event
from nexus_core.utils.file_context import is_image
import structlog

logger = structlog.get_logger(__name__)


class Dispatcher:
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

    async def dispatch_dag(self, parent_objective_id: UUID):
        """Dispatch all sub-objectives of a parent following DAG dependencies."""
        # Load the decomposition
        async with self._engine.begin() as conn:
            result = await conn.execute(
                objective_decomposition.select()
                .where(
                    objective_decomposition.c.parent_objective_id
                    == parent_objective_id
                )
                .order_by(objective_decomposition.c.execution_order)
            )
            decomp_rows = result.fetchall()
            child_status_rows = (
                await conn.execute(
                    sa.select(objectives.c.objective_id, objectives.c.status).where(
                        objectives.c.parent_objective_id == parent_objective_id
                    )
                )
            ).fetchall()

        if not decomp_rows:
            logger.warning(
                "no_decomposition_found",
                objective_id=str(parent_objective_id),
            )
            return

        graph = self._build_dependency_graph(decomp_rows)
        objective_statuses = {
            str(row.objective_id): row.status for row in child_status_rows
        }

        # Execute using TopologicalSorter
        sorter = TopologicalSorter(graph)
        sorter.prepare()

        active_tasks: dict[str, asyncio.Task] = {}
        completed_nodes: set[str] = set()
        failed_nodes: set[str] = set()

        while sorter.is_active():
            if self._shutdown.is_set():
                break

            progressed_without_dispatch = False
            ready = sorter.get_ready()
            for node_id in ready:
                status = objective_statuses.get(node_id)
                if status in {"active", "completed", "synthesizing"}:
                    sorter.done(node_id)
                    completed_nodes.add(node_id)
                    progressed_without_dispatch = True
                    continue
                if status in {"failed", "escalated"}:
                    failed_nodes.add(node_id)
                    progressed_without_dispatch = True
                    continue
                obj_uuid = UUID(node_id)
                task = asyncio.create_task(self._dispatch_single(obj_uuid))
                active_tasks[node_id] = task

            if progressed_without_dispatch and not active_tasks:
                continue

            if not active_tasks:
                break

            # Wait for any task to complete
            done, _ = await asyncio.wait(
                active_tasks.values(),
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in done:
                # Find which node this task belongs to
                for nid, t in list(active_tasks.items()):
                    if t is task:
                        try:
                            success = await task
                        except Exception as e:
                            logger.error(
                                "dispatch_task_failed",
                                objective_id=nid,
                                error=str(e),
                            )
                            success = False

                        if success:
                            sorter.done(nid)
                            completed_nodes.add(nid)
                        else:
                            failed_nodes.add(nid)
                        del active_tasks[nid]
                        break

        if failed_nodes:
            blocked_nodes = [
                node_id
                for node_id, deps in graph.items()
                if node_id not in completed_nodes
                and node_id not in failed_nodes
                and deps.intersection(failed_nodes)
            ]
            logger.warning(
                "dispatch_dag_incomplete",
                objective_id=str(parent_objective_id),
                failed_nodes=sorted(failed_nodes),
                blocked_nodes=sorted(blocked_nodes),
            )

    async def dispatch_objective(self, objective_id: UUID) -> bool:
        """Dispatch a single objective outside the parent DAG scheduler."""
        return await self._dispatch_single(objective_id)

    async def _dispatch_single(self, objective_id: UUID):
        """Dispatch a single sub-objective: select persona, build prompt, call API, store results."""
        # Get the objective
        async with self._engine.begin() as conn:
            result = await conn.execute(
                objectives.select().where(
                    objectives.c.objective_id == objective_id
                )
            )
            obj = result.first()
            if obj is None:
                return False

            # Select best-fit persona
            persona = await self._select_persona(conn, obj)
            if persona is None:
                await conn.execute(
                    objectives.update()
                    .where(objectives.c.objective_id == objective_id)
                    .values(
                        status="failed",
                        escalation_reason="No suitable persona available",
                    )
                )
                logger.error(
                    "no_suitable_persona",
                    objective_id=str(objective_id),
                )
                return False

            kg_context, memory_context = await self._build_prompt_context(conn, obj)

            # Update objective status
            await conn.execute(
                objectives.update()
                .where(objectives.c.objective_id == objective_id)
                .values(status="active", assigned_to=persona.persona_id)
            )

        # Build prompt
        system_prompt, user_prompt = PromptBuilder.build_agent_prompt(
            persona_template=persona.system_prompt_template,
            objective_description=f"{obj.title}\n\n{obj.description}",
            kg_context=kg_context,
            institutional_memory=memory_context,
        )

        # Create agent instance
        async with self._engine.begin() as conn:
            result = await conn.execute(
                agent_instances.insert()
                .values(
                    persona_id=persona.persona_id,
                    objective_id=objective_id,
                    input_prompt=user_prompt,
                    spawn_reason="objective_execution",
                    status="running",
                )
                .returning(agent_instances.c.instance_id)
            )
            instance_id = result.scalar_one()
            await emit_event(
                conn,
                "agent_spawned",
                entity_id=instance_id,
                entity_type="instance",
                payload={
                    "persona": persona.persona_name,
                    "objective": obj.title,
                },
            )

        # Check for image attachments to use multimodal dispatch
        image_paths: list[Path] = []
        file_attachment_ids = getattr(obj, "file_attachment_ids", None) or []
        if file_attachment_ids:
            try:
                from uuid import UUID as _UUID
                att_uuids = [_UUID(str(aid)) for aid in file_attachment_ids]
                async with self._engine.begin() as conn:
                    att_result = await conn.execute(
                        objective_attachments.select().where(
                            objective_attachments.c.attachment_id.in_(att_uuids)
                        )
                    )
                    for att_row in att_result:
                        if is_image(att_row.original_filename):
                            p = Path(att_row.stored_path)
                            if p.exists():
                                image_paths.append(p)
            except Exception as exc:
                logger.warning(
                    "image_attachment_load_failed",
                    objective_id=str(objective_id),
                    error=str(exc),
                )

        last_error: Exception | None = None
        attempt_user_prompt = user_prompt
        for attempt in range(2):
            try:
                if image_paths:
                    response = await self._kimi.call_multimodal(
                        system_prompt,
                        attempt_user_prompt,
                        image_paths=image_paths,
                    )
                else:
                    response = await self._kimi.call_thinking(
                        system_prompt,
                        attempt_user_prompt,
                    )
                cost_breakdown = calculate_cost_breakdown(
                    input_tokens=response.input_tokens,
                    thinking_tokens=response.thinking_tokens,
                    output_tokens=response.output_tokens,
                    cost_input_per_million=self._settings.COST_INPUT_PER_MILLION,
                    cost_output_per_million=self._settings.COST_OUTPUT_PER_MILLION,
                )
                cost_total = cost_breakdown.total_cost_usd

                # Parse findings
                finding_data = ResponseParser.parse_research_finding(
                    response.content,
                    strict=True,
                )

                # Store results
                async with self._engine.begin() as conn:
                    await _supersede_revision_requested_findings(
                        conn,
                        objective_id=objective_id,
                    )
                    await conn.execute(
                        agent_instances.update()
                        .where(agent_instances.c.instance_id == instance_id)
                        .values(
                            output_content=response.content,
                            thinking_content=response.reasoning,
                            status="completed",
                            completed_at=sa.func.now(),
                            retry_count=attempt,
                            tokens_input=response.input_tokens,
                            tokens_thinking=response.thinking_tokens,
                            tokens_output=response.output_tokens,
                            cost_usd=cost_total,
                            latency_ms=response.latency_ms,
                            error_message=None,
                        )
                    )
                    await conn.execute(
                        findings.insert().values(
                            objective_id=objective_id,
                            instance_id=instance_id,
                            finding_type="research",
                            title=finding_data.title,
                            content=finding_data.content,
                            structured_data={
                                "confidence": finding_data.confidence,
                                "citations": finding_data.citations,
                                "kg_entities": finding_data.kg_entities,
                                "kg_relationships": finding_data.kg_relationships,
                            },
                            status="pending_review",
                            impact_level=obj.impact_level,
                        )
                    )
                    await conn.execute(
                        agent_telemetry.insert().values(
                            instance_id=instance_id,
                            persona_id=persona.persona_id,
                            objective_id=objective_id,
                            prompt_hash=response.prompt_hash,
                            tokens_input=response.input_tokens,
                            tokens_thinking=response.thinking_tokens,
                            tokens_output=response.output_tokens,
                            cost_input_usd=cost_breakdown.input_cost_usd,
                            cost_thinking_usd=cost_breakdown.thinking_cost_usd,
                            cost_output_usd=cost_breakdown.output_cost_usd,
                            cost_total_usd=cost_total,
                            latency_ms=response.latency_ms,
                            http_status=200,
                            success=True,
                            model_id=response.model,
                        )
                    )
                    await emit_event(
                        conn,
                        "agent_completed",
                        entity_id=instance_id,
                        entity_type="instance",
                        payload={
                            "persona": persona.persona_name,
                            "cost": str(response.cost_usd),
                        },
                    )

                logger.info(
                    "agent_completed",
                    instance_id=str(instance_id),
                    persona=persona.persona_name,
                    cost=str(cost_total),
                    retry_count=attempt,
                )
                return True
            except Exception as e:
                last_error = e
                logger.warning(
                    "agent_execution_attempt_failed",
                    instance_id=str(instance_id),
                    attempt=attempt + 1,
                    error=str(e),
                )
                async with self._engine.begin() as conn:
                    await conn.execute(
                        agent_instances.update()
                        .where(agent_instances.c.instance_id == instance_id)
                        .values(
                            retry_count=attempt + 1,
                            error_message=str(e),
                            status="running" if attempt == 0 else "failed",
                        )
                    )
                if attempt == 0:
                    if isinstance(e, StructuredOutputError):
                        attempt_user_prompt = _build_contract_retry_prompt(
                            original_prompt=user_prompt,
                            contract_error=e,
                        )
                    continue

        async with self._engine.begin() as conn:
            if isinstance(last_error, StructuredOutputError):
                await conn.execute(
                    objectives.update()
                    .where(objectives.c.objective_id == objective_id)
                    .values(
                        status="revision_requested",
                        assigned_to=None,
                        escalation_reason=(
                            "Research output contract violation after retry: "
                            f"{last_error}"
                        ),
                    )
                )
                await emit_event(
                    conn,
                    "objective_revision_requested",
                    entity_id=objective_id,
                    entity_type="objective",
                )
                await emit_event(
                    conn,
                    "research_output_contract_violation",
                    entity_id=objective_id,
                    entity_type="objective",
                    payload={
                        "instance_id": str(instance_id),
                        "persona_id": str(persona.persona_id),
                        "error": str(last_error),
                    },
                )
                logger.warning(
                    "research_output_contract_violation",
                    objective_id=str(objective_id),
                    instance_id=str(instance_id),
                    error=str(last_error),
                )
                return False

            await conn.execute(
                objectives.update()
                .where(objectives.c.objective_id == objective_id)
                .values(
                    status="failed",
                    escalation_reason=f"Agent execution failed after retry: {last_error}",
                )
            )
            await diagnose_failure(
                conn,
                kimi_client=self._kimi,
                failed_instance_id=instance_id,
                failed_persona_id=persona.persona_id,
                objective_id=objective_id,
                input_prompt=user_prompt,
                error_message=str(last_error),
                failed_persona_prompt=persona.system_prompt_template,
            )
        return False

    async def _select_persona(self, conn, obj):
        """Select the best-fit persona for an objective based on role class or specialization."""
        # First try: match by assigned_to if already set
        if obj.assigned_to:
            result = await conn.execute(
                agent_personas.select().where(
                    agent_personas.c.persona_id == obj.assigned_to,
                    agent_personas.c.status == "active",
                )
            )
            persona = result.first()
            if persona:
                return persona

        required_role_class = self._extract_required_role_class(obj)
        objective_vector = EmbeddingService.hash_encode(
            "\n".join(
                filter(
                    None,
                    [
                        required_role_class or "",
                        obj.title,
                        obj.description,
                        getattr(obj, "acceptance_criteria", "") or "",
                    ],
                )
            )
        )

        result = await conn.execute(
            agent_personas.select()
            .where(agent_personas.c.status == "active")
        )
        personas = result.fetchall()
        if not isinstance(personas, list):
            personas = list(personas or [])
        if not personas:
            fallback_persona = result.first()
            if fallback_persona is not None:
                personas = [fallback_persona]
        best_persona = None
        best_score = float("-inf")

        for persona in personas:
            score = self._score_persona_match(
                objective_vector,
                persona,
                required_role_class,
            )
            if score > best_score:
                best_score = score
                best_persona = persona

        if required_role_class and (
            best_persona is None
            or best_persona.role_class != required_role_class
            or best_score < 0.35
        ):
            best_persona = await ensure_candidate_persona_approved(
                conn,
                obj,
                required_role_class,
                self._settings,
            )

        return best_persona

    async def _build_prompt_context(self, conn, obj) -> tuple[str, str]:
        """Collect KG and institutional memory context for the current objective."""
        anchor_ids = []
        for anchor in getattr(obj, "knowledge_graph_anchor", []) or []:
            try:
                anchor_ids.append(UUID(str(anchor)))
            except ValueError:
                continue

        kg_context = await get_context_for_objective(conn, anchor_ids) if anchor_ids else ""
        memory_filters = [institutional_memory.c.source_objective_id == obj.objective_id]
        parent_objective_id = getattr(obj, "parent_objective_id", None)
        if parent_objective_id is not None:
            memory_filters.append(
                institutional_memory.c.source_objective_id == parent_objective_id
            )
        memory_q = await conn.execute(
            sa.select(institutional_memory.c.title, institutional_memory.c.content)
            .where(sa.or_(*memory_filters))
            .order_by(institutional_memory.c.created_at.desc())
            .limit(5)
        )
        memories = list(memory_q)
        memory_context = "\n\n".join(
            f"- {memory.title}: {memory.content}" for memory in memories
        )
        return kg_context, memory_context

    @staticmethod
    def _extract_required_role_class(obj) -> str | None:
        criteria = (getattr(obj, "acceptance_criteria", "") or "").splitlines()
        for line in criteria:
            marker = "Required role class:"
            if line.startswith(marker):
                return line.split(":", 1)[1].strip() or None
        return None

    @staticmethod
    def _score_persona_match(
        objective_vector,
        persona,
        required_role_class: str | None,
    ) -> float:
        persona_vector = getattr(persona, "specialization_vector", None)
        if persona_vector is None:
            persona_vector = EmbeddingService.hash_encode(
                f"{persona.role_class} {persona.persona_name} {persona.system_prompt_template}"
            )
        else:
            persona_vector = np.asarray(persona_vector, dtype=np.float32)

        similarity = EmbeddingService.cosine_similarity(objective_vector, persona_vector)
        role_bonus = 0.35 if required_role_class and persona.role_class == required_role_class else 0.0
        reputation_bonus = float(persona.reputation_score or 0) * 0.1
        return similarity + role_bonus + reputation_bonus

    @staticmethod
    def _build_dependency_graph(decomp_rows) -> dict[str, set[str]]:
        """Build a dependency graph from stored child-objective UUID dependencies."""
        sorted_rows = sorted(decomp_rows, key=lambda r: r.execution_order)
        child_ids = {str(row.child_objective_id) for row in sorted_rows}
        graph: dict[str, set[str]] = {}

        for i, row in enumerate(sorted_rows):
            child_id = str(row.child_objective_id)
            dependencies: set[str] = set()
            raw_dependencies = row.depends_on or []

            if isinstance(raw_dependencies, str):
                raw_dependencies = [raw_dependencies]

            for dep in raw_dependencies:
                dep_id = str(dep)
                if dep_id in child_ids and dep_id != child_id:
                    dependencies.add(dep_id)

            # Backward compatibility for older decompositions that only captured order.
            if not dependencies and row.dependency_type == "sequential" and i > 0:
                dependencies.add(str(sorted_rows[i - 1].child_objective_id))

            graph[child_id] = dependencies

        return graph


async def _supersede_revision_requested_findings(conn, objective_id: UUID) -> None:
    """Mark older revision-requested findings obsolete before storing a rerun."""
    await conn.execute(
        findings.update()
        .where(
            findings.c.objective_id == objective_id,
            findings.c.status == "revision_requested",
        )
        .values(status="superseded")
    )


def _build_contract_retry_prompt(*, original_prompt: str, contract_error: Exception) -> str:
    """Augment the original prompt with explicit repair instructions for one retry."""
    return (
        f"{original_prompt}\n\n"
        "## Correction Required\n"
        "Your previous response was rejected and was not persisted.\n"
        f"Contract failure: {contract_error}\n"
        "Return the full JSON again, fix that exact issue, and keep every required key present.\n"
        "Do not explain the fix. Return raw JSON only."
    )
