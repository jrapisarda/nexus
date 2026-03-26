"""nexus agents / nexus agent <id> — list or inspect agent personas."""

import asyncio
from uuid import UUID

import typer
from rich.console import Console
from rich.panel import Panel

from nexus_cli.formatters import format_personas_table

console = Console()


async def _agents() -> None:
    import sqlalchemy as sa
    from nexus_core.database import get_connection
    from nexus_core.models.personas import agent_personas
    from nexus_core.models.objectives import objectives
    from nexus_core.economy.fitness import calculate_fitness

    async with get_connection() as conn:
        result = await conn.execute(
            agent_personas.select()
            .where(agent_personas.c.status.in_(["active", "candidate"]))
            .order_by(agent_personas.c.role_class, agent_personas.c.persona_name)
        )
        rows = [dict(row._mapping) for row in result]

        personas = []
        for row in rows:
            try:
                fitness = await calculate_fitness(conn, row["persona_id"])
            except Exception:
                fitness = 0.0

            # Check if assigned to an active objective
            assigned_q = await conn.execute(
                sa.select(objectives.c.title)
                .where(objectives.c.assigned_to == row["persona_id"])
                .where(objectives.c.status == "active")
                .limit(1)
            )
            assigned_row = assigned_q.first()
            assignment = assigned_row.title[:30] if assigned_row else "-"

            personas.append({
                "persona_name": row["persona_name"],
                "role_class": row["role_class"],
                "generation": row["generation"],
                "fitness": fitness,
                "status": row["status"],
                "assigned_objective": assignment,
            })

    if not personas:
        console.print("[yellow]No active personas found. Run 'nexus seed' to load initial data.[/]")
        return

    table = format_personas_table(personas)
    console.print(table)
    console.print(f"\n[dim]Total: {len(personas)} personas[/]")


async def _agent_detail(persona_id: str) -> None:
    import sqlalchemy as sa
    from nexus_core.database import get_connection
    from nexus_core.models.personas import agent_personas
    from nexus_core.models.instances import agent_instances
    from nexus_core.economy.fitness import calculate_fitness
    from nexus_core.economy.ledger import get_balance, get_ledger_entries

    pid = UUID(persona_id)

    async with get_connection() as conn:
        result = await conn.execute(
            agent_personas.select().where(agent_personas.c.persona_id == pid)
        )
        persona = result.first()

        if persona is None:
            console.print(f"[red]Persona not found: {persona_id}[/]")
            return

        p = dict(persona._mapping)

        # Fitness
        try:
            fitness = await calculate_fitness(conn, pid)
        except Exception:
            fitness = 0.0

        # Credit balance from ledger
        try:
            balance = await get_balance(conn, pid)
        except Exception:
            balance = p.get("credit_balance", 0)

        # Instance history count
        instance_count_q = await conn.execute(
            sa.select(sa.func.count())
            .select_from(agent_instances)
            .where(agent_instances.c.persona_id == pid)
        )
        instance_count = instance_count_q.scalar_one()

        # Lineage
        lineage = []
        current_parent = p.get("parent_persona_id")
        while current_parent:
            parent_q = await conn.execute(
                sa.select(
                    agent_personas.c.persona_id,
                    agent_personas.c.persona_name,
                    agent_personas.c.parent_persona_id,
                ).where(agent_personas.c.persona_id == current_parent)
            )
            parent_row = parent_q.first()
            if parent_row is None:
                break
            lineage.append(f"{parent_row.persona_name} ({str(parent_row.persona_id)[:8]}...)")
            current_parent = parent_row.parent_persona_id

        # Recent ledger entries
        try:
            recent_tx = await get_ledger_entries(conn, persona_id=pid, limit=5)
        except Exception:
            recent_tx = []

    # Display
    lines = [
        f"[bold cyan]Name:[/]            {p['persona_name']}",
        f"[bold cyan]ID:[/]              {p['persona_id']}",
        f"[bold cyan]Role Class:[/]      {p['role_class']}",
        f"[bold cyan]Generation:[/]      {p['generation']}",
        f"[bold cyan]Status:[/]          {p['status']}",
        f"[bold cyan]Autonomy Level:[/]  {p['autonomy_level']}",
        f"[bold cyan]Reasoning:[/]       {p['reasoning_strategy']}",
        f"[bold cyan]Fitness Score:[/]   {fitness:.4f}",
        f"[bold cyan]Credit Balance:[/]  {float(balance):.2f}",
        f"[bold cyan]Reputation:[/]      {float(p.get('reputation_score', 0)):.3f}",
        f"[bold cyan]Instances Run:[/]   {instance_count}",
        f"[bold cyan]Created:[/]         {p['created_at']}",
    ]

    if lineage:
        lines.append(f"\n[bold]Lineage (parent -> grandparent):[/]")
        for i, ancestor in enumerate(lineage):
            lines.append(f"  {'  ' * i}-> {ancestor}")

    if p.get("mutation_diff"):
        lines.append(f"\n[bold]Mutation Diff:[/]")
        diff = p["mutation_diff"]
        lines.append(f"  Type: {diff.get('type', 'N/A')}")
        lines.append(f"  Changes: {diff.get('changes', 'N/A')}")

    console.print(Panel("\n".join(lines), title=f"Persona: {p['persona_name']}", border_style="cyan"))

    if recent_tx:
        from rich.table import Table

        tx_table = Table(title="Recent Transactions", show_lines=True)
        tx_table.add_column("Type", style="magenta")
        tx_table.add_column("Amount", justify="right", style="yellow")
        tx_table.add_column("Memo", style="dim", max_width=40)
        tx_table.add_column("Time", style="dim")

        for tx in recent_tx:
            direction = "+" if tx.get("to_persona_id") == pid else "-"
            amount = float(tx.get("amount", 0))
            created = tx.get("created_at")
            time_str = created.strftime("%Y-%m-%d %H:%M") if created else "N/A"

            tx_table.add_row(
                str(tx.get("transaction_type", "N/A")),
                f"{direction}{amount:.2f}",
                str(tx.get("memo", ""))[:40],
                time_str,
            )

        console.print(tx_table)


def agents() -> None:
    """List all active agent personas with fitness scores."""
    try:
        asyncio.run(_agents())
    except Exception as e:
        console.print(f"[red]Error fetching agents:[/] {e}")
        raise typer.Exit(code=1)


def agent_detail(
    persona_id: str = typer.Argument(..., help="Persona UUID to inspect"),
) -> None:
    """Show detailed information for a specific agent persona."""
    try:
        asyncio.run(_agent_detail(persona_id))
    except ValueError:
        console.print(f"[red]Invalid UUID: {persona_id}[/]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Error fetching agent detail:[/] {e}")
        raise typer.Exit(code=1)
