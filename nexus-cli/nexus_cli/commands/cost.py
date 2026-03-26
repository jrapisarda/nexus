"""nexus cost — detailed cost report."""

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nexus_cli.formatters import format_cost_table

console = Console()


async def _cost() -> None:
    import sqlalchemy as sa
    from nexus_core.config import get_settings
    from nexus_core.database import get_connection
    from nexus_core.models.telemetry import agent_telemetry
    from nexus_core.models.personas import agent_personas
    from nexus_core.models.objectives import objectives

    settings = get_settings()

    async with get_connection() as conn:
        # Total spend
        total_q = await conn.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(agent_telemetry.c.cost_total_usd), 0).label("total_cost"),
                sa.func.coalesce(sa.func.sum(agent_telemetry.c.tokens_input), 0).label("total_input"),
                sa.func.coalesce(sa.func.sum(agent_telemetry.c.tokens_output), 0).label("total_output"),
                sa.func.coalesce(sa.func.sum(agent_telemetry.c.tokens_thinking), 0).label("total_thinking"),
                sa.func.count().label("total_calls"),
            )
        )
        totals = dict(total_q.first()._mapping)

        # Per-persona cost
        per_agent_q = await conn.execute(
            sa.select(
                agent_personas.c.persona_name,
                sa.func.count().label("call_count"),
                sa.func.sum(agent_telemetry.c.tokens_input + agent_telemetry.c.tokens_output + agent_telemetry.c.tokens_thinking).label("total_tokens"),
                sa.func.sum(agent_telemetry.c.cost_total_usd).label("total_cost"),
            )
            .join(agent_personas, agent_telemetry.c.persona_id == agent_personas.c.persona_id)
            .group_by(agent_personas.c.persona_name)
            .order_by(sa.desc("total_cost"))
        )
        per_agent = [dict(row._mapping) for row in per_agent_q]

        # Per-objective cost
        per_obj_q = await conn.execute(
            sa.select(
                objectives.c.title,
                sa.func.count().label("call_count"),
                sa.func.sum(agent_telemetry.c.cost_total_usd).label("total_cost"),
            )
            .join(objectives, agent_telemetry.c.objective_id == objectives.c.objective_id)
            .group_by(objectives.c.title)
            .order_by(sa.desc("total_cost"))
            .limit(10)
        )
        per_objective = [dict(row._mapping) for row in per_obj_q]

    budget_ceiling = float(settings.BUDGET_CEILING_USD)
    total_cost = float(totals["total_cost"])
    remaining = budget_ceiling - total_cost
    pct = (total_cost / budget_ceiling * 100) if budget_ceiling > 0 else 0.0

    budget_color = "green" if pct < 50 else ("yellow" if pct < 75 else "red")

    # Summary panel
    lines = [
        f"[bold cyan]Total API Calls:[/]     {totals['total_calls']:,}",
        f"[bold cyan]Input Tokens:[/]        {int(totals['total_input']):,}",
        f"[bold cyan]Thinking Tokens:[/]     {int(totals['total_thinking']):,}",
        f"[bold cyan]Output Tokens:[/]       {int(totals['total_output']):,}",
        "",
        f"[bold cyan]Total Spend:[/]         [{budget_color}]${total_cost:.6f}[/]",
        f"[bold cyan]Budget Ceiling:[/]      ${budget_ceiling:.2f}",
        f"[bold cyan]Remaining:[/]           [{budget_color}]${remaining:.6f}[/]",
        f"[bold cyan]Utilization:[/]         [{budget_color}]{pct:.1f}%[/]",
    ]

    console.print(Panel("\n".join(lines), title="Cost Report", border_style="red"))

    # Per-agent table
    if per_agent:
        agent_table = format_cost_table(per_agent)
        console.print(agent_table)

    # Per-objective table
    if per_objective:
        obj_table = Table(title="Cost Report -- Per Objective (Top 10)", show_lines=True)
        obj_table.add_column("Objective", style="cyan", max_width=40)
        obj_table.add_column("Calls", justify="right", style="green")
        obj_table.add_column("Cost ($)", justify="right", style="red")

        for row in per_objective:
            obj_table.add_row(
                str(row["title"])[:40],
                str(row["call_count"]),
                f"${float(row['total_cost']):.6f}",
            )

        console.print(obj_table)

    if not per_agent and not per_objective:
        console.print("[dim]No telemetry data recorded yet.[/]")


def cost() -> None:
    """Show detailed cost report: total spend, per-agent, per-objective, remaining budget."""
    try:
        asyncio.run(_cost())
    except Exception as e:
        console.print(f"[red]Error fetching cost data:[/] {e}")
        raise typer.Exit(code=1)
