import asyncio
from uuid import UUID

import networkx as nx
import sqlalchemy as sa

from nexus_core.config import NexusSettings
from nexus_core.llm.client import KimiClient, MalformedModelResponseError
from nexus_core.llm.prompt_builder import PromptBuilder
from nexus_core.llm.response_parser import ResponseParser
from nexus_core.models.objectives import objectives
from nexus_core.models.decomposition import objective_decomposition
from nexus_core.knowledge.query import get_context_for_objective
from nexus_core.utils.file_context import (
    AttachmentContext,
    FileContextBudget,
    FileContextLoader,
)
import structlog

logger = structlog.get_logger(__name__)


class DAGCycleError(Exception):
    pass


async def decompose_objective(
    engine,
    kimi_client: KimiClient,
    objective_id: UUID,
    settings: NexusSettings,
    max_retries: int = 3,
) -> list[dict]:
    """Decompose an objective into a DAG of sub-objectives.

    Returns list of sub-objective dicts with dependency info.
    """
    # Get the objective
    async with engine.begin() as conn:
        result = await conn.execute(
            objectives.select().where(objectives.c.objective_id == objective_id)
        )
        obj = result.first()
        if obj is None:
            raise ValueError(f"Objective {objective_id} not found")

        # Get KG context from anchor nodes
        anchor_ids = obj.knowledge_graph_anchor or []
        kg_context = await get_context_for_objective(
            conn,
            [UUID(a) for a in anchor_ids] if anchor_ids else [],
        )

    # Load file context if attachments are present
    file_context_section = ""
    file_attachment_ids = getattr(obj, "file_attachment_ids", None) or []
    if file_attachment_ids:
        try:
            attachment_uuids = [UUID(str(aid)) for aid in file_attachment_ids]
            contexts = await FileContextLoader.load(engine, attachment_uuids)
            contexts = FileContextBudget.check_and_truncate(
                contexts, settings.FILE_CONTEXT_BUDGET_CHARS
            )
            file_context_section = PromptBuilder.build_file_context_section(contexts)
            if file_context_section:
                logger.info(
                    "file_context_injected",
                    objective_id=str(objective_id),
                    attachment_count=len(contexts),
                    total_chars=len(file_context_section),
                )
        except Exception as exc:
            logger.warning(
                "file_context_load_failed",
                objective_id=str(objective_id),
                error=str(exc),
            )

    # Build decomposition prompt
    system_prompt, user_prompt = PromptBuilder.build_decomposition_prompt(
        objective_title=obj.title,
        objective_description=obj.description,
        kg_context=kg_context,
        max_depth=settings.MAX_DAG_DEPTH,
        max_fanout=settings.MAX_DAG_FANOUT,
        file_context=file_context_section,
    )

    # Try decomposition with retries
    decomposition = None
    last_failure_reason = ""
    for attempt in range(max_retries):
        retry_prompt = user_prompt
        if attempt > 0:
            retry_prompt += (
                "\n\nIMPORTANT: Your previous response was invalid or incomplete "
                f"({last_failure_reason or 'structured output failure'}). "
                "Return COMPLETE valid raw JSON only, with no markdown fences "
                "and no explanatory text."
            )
            if "cycle" in last_failure_reason:
                retry_prompt += (
                    "\nEnsure ALL dependencies form a valid DAG with NO cycles."
                )

        try:
            response = await kimi_client.call_thinking(system_prompt, retry_prompt)
        except MalformedModelResponseError as exc:
            last_failure_reason = str(exc)
            logger.warning(
                "decomposition_response_invalid",
                objective_id=str(objective_id),
                attempt=attempt,
                error=str(exc),
            )
            continue

        decomposition = ResponseParser.parse_decomposition(response.content)

        if not decomposition.sub_objectives:
            last_failure_reason = "empty_or_invalid_decomposition"
            logger.warning(
                "empty_decomposition",
                objective_id=str(objective_id),
                attempt=attempt,
            )
            continue

        # Validate DAG is acyclic
        try:
            _validate_dag(decomposition.sub_objectives, settings)
            break
        except DAGCycleError as e:
            last_failure_reason = str(e)
            logger.warning(
                "dag_cycle_detected",
                objective_id=str(objective_id),
                attempt=attempt,
                error=str(e),
            )
            if attempt == max_retries - 1:
                raise

    if decomposition is None or not decomposition.sub_objectives:
        raise ValueError(
            f"Failed to decompose objective {objective_id} after {max_retries} attempts"
        )

    # Write sub-objectives and decomposition to DB
    sub_objectives = []
    created_sub_objectives: list[tuple[int, object, UUID]] = []
    sub_id_to_objective_id: dict[str, UUID] = {}
    async with engine.begin() as conn:
        for idx, sub in enumerate(decomposition.sub_objectives):
            # Create sub-objective row
            result = await conn.execute(
                objectives.insert()
                .values(
                    parent_objective_id=objective_id,
                    title=sub.title,
                    description=sub.description,
                    objective_type="tactical",
                    impact_level=sub.impact_level,
                    priority=obj.priority,
                    status="proposed",
                    proposed_by_type="agent",
                    acceptance_criteria=(
                        f"Required role class: {sub.role_class}\n"
                        f"Sub-objective of: {obj.title}"
                    ),
                    output_type="analysis",
                    file_attachment_ids=file_attachment_ids,
                )
                .returning(objectives.c.objective_id)
            )
            sub_obj_id = result.scalar_one()
            created_sub_objectives.append((idx, sub, sub_obj_id))
            sub_id_to_objective_id[sub.id] = sub_obj_id

        for idx, sub, sub_obj_id in created_sub_objectives:
            resolved_dependencies: list[str] = []
            missing_dependencies = []
            for dep in sub.depends_on:
                dep_obj_id = sub_id_to_objective_id.get(dep)
                if dep_obj_id is None:
                    missing_dependencies.append(dep)
                    continue
                resolved_dependencies.append(str(dep_obj_id))

            if missing_dependencies:
                raise ValueError(
                    "Decomposition referenced unknown sub-objective dependencies: "
                    f"{missing_dependencies}"
                )

            # Create decomposition link with real child-objective UUID dependencies.
            await conn.execute(
                objective_decomposition.insert().values(
                    parent_objective_id=objective_id,
                    child_objective_id=sub_obj_id,
                    decomposition_rationale=sub.rationale,
                    dependency_type=sub.dependency_type,
                    depends_on=resolved_dependencies,
                    execution_order=idx,
                )
            )

            sub_objectives.append(
                {
                    "sub_id": sub.id,
                    "objective_id": sub_obj_id,
                    "title": sub.title,
                    "role_class": sub.role_class,
                    "dependency_type": sub.dependency_type,
                    "depends_on": resolved_dependencies,
                    "impact_level": sub.impact_level,
                }
            )

    logger.info(
        "decomposition_complete",
        objective_id=str(objective_id),
        sub_objectives=len(sub_objectives),
    )

    return sub_objectives


def _validate_dag(sub_objectives, settings: NexusSettings):
    """Validate the decomposition forms a valid DAG."""
    G = nx.DiGraph()
    sub_ids = [sub.id for sub in sub_objectives]

    if len(sub_ids) != len(set(sub_ids)):
        raise DAGCycleError("Decomposition contains duplicate sub-objective IDs")

    for sub in sub_objectives:
        G.add_node(sub.id)
        for dep in sub.depends_on:
            if dep not in sub_ids:
                raise DAGCycleError(
                    f"Decomposition references unknown dependency '{dep}' for sub-objective '{sub.id}'"
                )
            G.add_edge(dep, sub.id)

    # Check acyclic
    if not nx.is_directed_acyclic_graph(G):
        cycles = list(nx.simple_cycles(G))
        raise DAGCycleError(f"Decomposition contains cycles: {cycles}")

    # Check depth
    if G.nodes:
        longest_path = nx.dag_longest_path_length(G)
        if longest_path > settings.MAX_DAG_DEPTH:
            raise DAGCycleError(
                f"DAG depth {longest_path} exceeds maximum {settings.MAX_DAG_DEPTH}"
            )

    # Check fan-out
    for node in G.nodes:
        if G.out_degree(node) > settings.MAX_DAG_FANOUT:
            raise DAGCycleError(
                f"Node {node} has fan-out {G.out_degree(node)} "
                f"exceeding max {settings.MAX_DAG_FANOUT}"
            )
