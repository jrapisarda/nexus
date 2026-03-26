import json
from decimal import Decimal
from pathlib import Path


async def load_seed_data(engine, seed_dir: str | Path | None = None):
    """Load seed personas and tools from JSON files. Idempotent (upsert by name)."""
    if seed_dir is None:
        # Default to project root's seed/ directory
        seed_dir = Path(__file__).parent.parent.parent.parent / "seed"
    seed_dir = Path(seed_dir)

    async with engine.begin() as conn:
        # Load personas
        personas_file = seed_dir / "personas.json"
        if personas_file.exists():
            personas = json.loads(personas_file.read_text(encoding="utf-8"))
            await _upsert_personas(conn, personas)

        # Load tools
        tools_file = seed_dir / "tools.json"
        if tools_file.exists():
            tools = json.loads(tools_file.read_text(encoding="utf-8"))
            await _upsert_tools(conn, tools)


async def _upsert_personas(conn, personas: list[dict]):
    """Upsert personas by persona_name."""
    from nexus_core.models.personas import agent_personas
    from nexus_core.economy.ledger import get_balance, mint_credits
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    for persona in personas:
        persona_data = dict(persona)
        desired_balance = Decimal(
            str(persona_data.pop("initial_credits", persona_data.pop("credit_balance", 0)))
        )

        stmt = (
            pg_insert(agent_personas)
            .values(**persona_data)
            .returning(agent_personas.c.persona_id)
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["persona_name"],
            set_={k: v for k, v in persona_data.items() if k != "persona_name"},
        )
        result = await conn.execute(stmt)
        persona_id = result.scalar_one()

        if desired_balance > Decimal("0"):
            current_balance = await get_balance(conn, persona_id)
            delta = desired_balance - current_balance
            if delta > Decimal("0"):
                await mint_credits(
                    conn,
                    delta,
                    persona_id,
                    memo="Seeded initial persona balance",
                )


async def _upsert_tools(conn, tools: list[dict]):
    """Upsert tools by tool_name."""
    from nexus_core.models.tool_registry import tool_registry
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    for tool in tools:
        stmt = pg_insert(tool_registry).values(**tool)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tool_name"],
            set_={k: v for k, v in tool.items() if k != "tool_name"},
        )
        await conn.execute(stmt)
