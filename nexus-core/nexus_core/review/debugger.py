"""Debugger-agent failure diagnosis workflow."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
import structlog

from nexus_core.models.instances import agent_instances
from nexus_core.models.institutional_memory import institutional_memory
from nexus_core.models.personas import agent_personas
from nexus_core.models.telemetry import agent_telemetry
from nexus_core.utils.cost import calculate_cost_breakdown, coerce_decimal_rate
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)


async def diagnose_failure(
    conn,
    kimi_client,
    failed_instance_id: UUID,
    failed_persona_id: UUID,
    objective_id: UUID,
    input_prompt: str,
    error_message: str,
    failed_persona_prompt: str = "",
    partial_output: str = "",
) -> UUID | None:
    """Spawn the debugger persona and write the diagnosis into institutional memory."""
    debugger_q = await conn.execute(
        sa.select(
            agent_personas.c.persona_id,
            agent_personas.c.persona_name,
            agent_personas.c.system_prompt_template,
        )
        .where(
            agent_personas.c.role_class == "debugger",
            agent_personas.c.status == "active",
        )
        .order_by(agent_personas.c.reputation_score.desc())
        .limit(1)
    )
    debugger = debugger_q.one_or_none()
    if debugger is None:
        await conn.execute(
            institutional_memory.insert().values(
                memory_type="failure_diagnosis",
                title="Failure without debugger persona",
                content=(
                    f"Instance {failed_instance_id} failed and no debugger persona was available.\n"
                    f"Persona: {failed_persona_id}\n"
                    f"Error: {error_message}"
                ),
                source_objective_id=objective_id,
                source_instance_id=failed_instance_id,
                relevance_tags=["debugger", "fallback", "failure"],
            )
        )
        return None

    diagnostic_prompt = (
        "You are diagnosing a failed NEXUS agent run.\n\n"
        f"Failed persona id: {failed_persona_id}\n"
        f"Failed persona prompt:\n{failed_persona_prompt or 'Unavailable'}\n\n"
        f"Original input prompt:\n{input_prompt}\n\n"
        f"Error message:\n{error_message}\n\n"
        f"Partial output:\n{partial_output or 'No partial output captured.'}\n\n"
        "Produce a concise but specific diagnosis covering:\n"
        "1. probable root cause\n"
        "2. severity\n"
        "3. remediation steps\n"
        "4. prevention guidance"
    )

    inst_result = await conn.execute(
        agent_instances.insert()
        .values(
            persona_id=debugger.persona_id,
            objective_id=objective_id,
            input_prompt=diagnostic_prompt,
            spawn_reason="failure_debugging",
            spawned_by=failed_instance_id,
            status="running",
        )
        .returning(agent_instances.c.instance_id)
    )
    debugger_instance_id = inst_result.scalar_one()

    try:
        response = await kimi_client.call_thinking(
            system=debugger.system_prompt_template,
            user=diagnostic_prompt,
        )
        client_settings = getattr(kimi_client, "_settings", None)
        cost_breakdown = calculate_cost_breakdown(
            input_tokens=response.input_tokens,
            thinking_tokens=response.thinking_tokens,
            output_tokens=response.output_tokens,
            cost_input_per_million=coerce_decimal_rate(
                getattr(client_settings, "COST_INPUT_PER_MILLION", None),
                Decimal("0.60"),
            ),
            cost_output_per_million=coerce_decimal_rate(
                getattr(client_settings, "COST_OUTPUT_PER_MILLION", None),
                Decimal("2.50"),
            ),
        )
        cost_total = cost_breakdown.total_cost_usd

        await conn.execute(
            agent_instances.update()
            .where(agent_instances.c.instance_id == debugger_instance_id)
            .values(
                status="completed",
                output_content=response.content,
                thinking_content=response.reasoning,
                tokens_input=response.input_tokens,
                tokens_thinking=response.thinking_tokens,
                tokens_output=response.output_tokens,
                cost_usd=cost_total,
                latency_ms=response.latency_ms,
                completed_at=sa.func.now(),
            )
        )
        await conn.execute(
            agent_telemetry.insert().values(
                instance_id=debugger_instance_id,
                persona_id=debugger.persona_id,
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
        memory_result = await conn.execute(
            institutional_memory.insert()
            .values(
                memory_type="failure_diagnosis",
                title=f"Debugger diagnosis for failed instance {failed_instance_id}",
                content=response.content,
                source_objective_id=objective_id,
                source_instance_id=failed_instance_id,
                relevance_tags=["debugger", "failure", "diagnosis"],
            )
            .returning(institutional_memory.c.memory_id)
        )
        memory_id = memory_result.scalar_one()
        await emit_event(
            conn,
            "debugger_diagnosis_logged",
            entity_id=failed_instance_id,
            entity_type="instance",
            payload={
                "debugger_instance_id": str(debugger_instance_id),
                "memory_id": str(memory_id),
            },
        )
        logger.info(
            "debugger_diagnosis_logged",
            failed_instance_id=str(failed_instance_id),
            debugger_instance_id=str(debugger_instance_id),
        )
        return memory_id
    except Exception as exc:
        logger.exception(
            "debugger_diagnosis_failed",
            failed_instance_id=str(failed_instance_id),
        )
        await conn.execute(
            agent_instances.update()
            .where(agent_instances.c.instance_id == debugger_instance_id)
            .values(status="failed", error_message=str(exc)[:500])
        )
        return None
