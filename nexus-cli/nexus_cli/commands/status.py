"""nexus status — show system overview."""

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


async def _status() -> None:
    import sqlalchemy as sa
    from nexus_core.database import get_connection
    from nexus_core.models.objectives import objectives
    from nexus_core.models.instances import agent_instances
    from nexus_core.models.personas import agent_personas
    from nexus_core.models.telemetry import agent_telemetry
    from nexus_core.models.events import events
    from nexus_core.config import get_settings

    settings = get_settings()

    async with get_connection() as conn:
        # Active objectives
        active_obj_q = await conn.execute(
            sa.select(sa.func.count())
            .select_from(objectives)
            .where(objectives.c.status.in_(["proposed", "active"]))
        )
        active_objectives = active_obj_q.scalar_one()

        # Completed objectives
        completed_obj_q = await conn.execute(
            sa.select(sa.func.count())
            .select_from(objectives)
            .where(objectives.c.status == "completed")
        )
        completed_objectives = completed_obj_q.scalar_one()

        # Running instances
        running_q = await conn.execute(
            sa.select(sa.func.count())
            .select_from(agent_instances)
            .where(agent_instances.c.status.in_(["pending", "running"]))
        )
        running_instances = running_q.scalar_one()

        # Agent population
        agent_pop_q = await conn.execute(
            sa.select(sa.func.count())
            .select_from(agent_personas)
            .where(agent_personas.c.status == "active")
        )
        agent_population = agent_pop_q.scalar_one()

        # Total spend
        total_cost_q = await conn.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(agent_telemetry.c.cost_total_usd), 0)
            )
        )
        total_spend = float(total_cost_q.scalar_one())
        budget_ceiling = float(settings.BUDGET_CEILING_USD)
        budget_pct = (total_spend / budget_ceiling * 100) if budget_ceiling > 0 else 0.0

        # Recent events (last 5)
        recent_events_q = await conn.execute(
            events.select()
            .order_by(events.c.created_at.desc())
            .limit(5)
        )
        recent_events = [dict(row._mapping) for row in recent_events_q]

    # Build summary panel
    budget_color = "green" if budget_pct < 50 else ("yellow" if budget_pct < 75 else "red")

    lines = [
        f"[bold cyan]Active Objectives:[/]     {active_objectives}",
        f"[bold cyan]Completed Objectives:[/]  {completed_objectives}",
        f"[bold cyan]Running Instances:[/]     {running_instances}",
        f"[bold cyan]Agent Population:[/]      {agent_population}",
        f"[bold cyan]Budget Utilization:[/]    [{budget_color}]${total_spend:.4f} / ${budget_ceiling:.2f} ({budget_pct:.1f}%)[/]",
    ]

    console.print(Panel("\n".join(lines), title="NEXUS System Status", border_style="green"))

    # Recent events
    if recent_events:
        event_table = Table(title="Recent Events", show_lines=True)
        event_table.add_column("Type", style="cyan")
        event_table.add_column("Entity", style="magenta")
        event_table.add_column("Time", style="dim")

        for ev in recent_events:
            created = ev.get("created_at")
            time_str = created.strftime("%Y-%m-%d %H:%M:%S") if created else "N/A"
            entity_type = ev.get("entity_type", "-") or "-"
            entity_id = str(ev.get("entity_id", "-") or "-")[:8]

            event_table.add_row(
                str(ev.get("event_type", "N/A")),
                f"{entity_type}/{entity_id}...",
                time_str,
            )

        console.print(event_table)
    else:
        console.print("[dim]No recent events.[/]")


def status() -> None:
    """Show NEXUS system status overview."""
    try:
        asyncio.run(_status())
    except Exception as e:
        console.print(f"[red]Error fetching status:[/] {e}")
        raise typer.Exit(code=1)
