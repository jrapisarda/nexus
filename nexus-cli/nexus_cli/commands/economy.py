"""nexus economy — economy health summary."""

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


async def _economy() -> None:
    import sqlalchemy as sa
    from nexus_core.database import get_connection
    from nexus_core.economy.diversity import get_economy_summary
    from nexus_core.economy.ledger import get_all_balances
    from nexus_core.models.personas import agent_personas

    async with get_connection() as conn:
        summary = await get_economy_summary(conn)
        balances = await get_all_balances(conn)

        # Map persona IDs to names
        if balances:
            persona_ids = list(balances.keys())
            result = await conn.execute(
                sa.select(agent_personas.c.persona_id, agent_personas.c.persona_name)
                .where(agent_personas.c.persona_id.in_(persona_ids))
            )
            id_to_name = {row.persona_id: row.persona_name for row in result}
        else:
            id_to_name = {}

    # Summary panel
    gini = summary.get("gini_coefficient", 0.0)
    gini_color = "green" if gini < 0.3 else ("yellow" if gini < 0.5 else "red")

    lines = [
        f"[bold cyan]Total Personas:[/]         {summary.get('total_personas', 0)}",
        f"[bold cyan]Total Credits Minted:[/]   {summary.get('total_credits_minted', 0.0):.2f}",
        f"[bold cyan]Total Rent Collected:[/]   {summary.get('total_rent_collected', 0.0):.2f}",
        f"[bold cyan]Net Credits in System:[/]  {summary.get('net_credits_in_system', 0.0):.2f}",
        f"[bold cyan]Gini Coefficient:[/]       [{gini_color}]{gini:.4f}[/]",
        f"[bold cyan]Mean Balance:[/]           {summary.get('mean_balance', 0.0):.2f}",
        f"[bold cyan]Top Balance:[/]            {summary.get('top_balance', 0.0):.2f}",
        f"[bold cyan]Bottom Balance:[/]         {summary.get('bottom_balance', 0.0):.2f}",
    ]

    console.print(Panel("\n".join(lines), title="Economy Health", border_style="green"))

    # Balances table
    if balances:
        sorted_balances = sorted(balances.items(), key=lambda x: float(x[1]), reverse=True)

        table = Table(title="Agent Balances", show_lines=True)
        table.add_column("Persona", style="cyan")
        table.add_column("Balance", justify="right", style="yellow")

        for pid, bal in sorted_balances:
            name = id_to_name.get(pid, str(pid)[:8] + "...")
            bal_float = float(bal)
            bal_style = "green" if bal_float >= 50 else ("yellow" if bal_float >= 10 else "red")
            table.add_row(name, f"[{bal_style}]{bal_float:.2f}[/]")

        console.print(table)
    else:
        console.print("[dim]No balances recorded yet.[/]")


def economy_cmd() -> None:
    """Show economy health summary: credits, Gini coefficient, balances."""
    try:
        asyncio.run(_economy())
    except Exception as e:
        console.print(f"[red]Error fetching economy data:[/] {e}")
        raise typer.Exit(code=1)
