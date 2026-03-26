"""nexus objectives — list objectives with optional status filter."""

import asyncio
from typing import Optional

import typer
from rich.console import Console

from nexus_cli.formatters import format_objectives_table

console = Console()


async def _objectives(status_filter: Optional[str]) -> None:
    from nexus_core.database import get_connection
    from nexus_core.models.objectives import objectives

    async with get_connection() as conn:
        query = objectives.select().order_by(
            objectives.c.priority.asc(),
            objectives.c.created_at.desc(),
        )

        if status_filter:
            query = query.where(objectives.c.status == status_filter)

        result = await conn.execute(query)
        rows = [dict(row._mapping) for row in result]

    if not rows:
        msg = f" with status '{status_filter}'" if status_filter else ""
        console.print(f"[yellow]No objectives found{msg}.[/]")
        return

    table = format_objectives_table(rows)
    console.print(table)
    console.print(f"\n[dim]Total: {len(rows)} objectives[/]")


def objectives_cmd(
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status: proposed, active, completed, failed, escalated",
    ),
) -> None:
    """List objectives with optional status filter."""
    valid_statuses = {"proposed", "active", "completed", "failed", "escalated"}
    if status and status not in valid_statuses:
        console.print(f"[red]Invalid status '{status}'. Valid: {', '.join(sorted(valid_statuses))}[/]")
        raise typer.Exit(code=1)

    try:
        asyncio.run(_objectives(status))
    except Exception as e:
        console.print(f"[red]Error fetching objectives:[/] {e}")
        raise typer.Exit(code=1)
