"""Rich table formatters for NEXUS CLI terminal output."""

from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def format_personas_table(personas: list[dict]) -> Table:
    """Format a list of persona dicts into a Rich table.

    Expected keys: persona_name, role_class, generation, fitness,
                   status, assigned_objective (optional).
    """
    table = Table(title="Agent Personas", show_lines=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Role", style="magenta")
    table.add_column("Gen", justify="right", style="green")
    table.add_column("Fitness", justify="right", style="yellow")
    table.add_column("Status", style="bold")
    table.add_column("Assignment", style="dim")

    for p in personas:
        status = p.get("status", "unknown")
        status_style = {
            "active": "green",
            "candidate": "yellow",
            "deprecated": "red",
        }.get(status, "white")

        table.add_row(
            str(p.get("persona_name", "N/A")),
            str(p.get("role_class", "N/A")),
            str(p.get("generation", 0)),
            f"{p.get('fitness', 0.0):.4f}",
            Text(status, style=status_style),
            str(p.get("assigned_objective", "-")),
        )

    return table


def format_objectives_table(objectives: list[dict]) -> Table:
    """Format a list of objective dicts into a Rich table.

    Expected keys: title, objective_type, priority, status, created_at.
    """
    table = Table(title="Objectives", show_lines=True)
    table.add_column("Title", style="cyan", max_width=50)
    table.add_column("Type", style="magenta")
    table.add_column("Priority", justify="right", style="yellow")
    table.add_column("Status", style="bold")
    table.add_column("Created", style="dim")

    for o in objectives:
        status = o.get("status", "unknown")
        status_style = {
            "proposed": "blue",
            "active": "green",
            "completed": "bright_green",
            "failed": "red",
            "escalated": "yellow",
        }.get(status, "white")

        created = o.get("created_at")
        created_str = created.strftime("%Y-%m-%d %H:%M") if created else "N/A"

        table.add_row(
            str(o.get("title", "N/A"))[:50],
            str(o.get("objective_type", "N/A")),
            str(o.get("priority", "-")),
            Text(status, style=status_style),
            created_str,
        )

    return table


def format_economy_table(balances: dict) -> Table:
    """Format persona balances into a Rich table.

    Args:
        balances: dict mapping persona name/id -> {"balance": float, "change": float}
    """
    table = Table(title="Economy — Agent Balances", show_lines=True)
    table.add_column("Persona", style="cyan")
    table.add_column("Balance", justify="right", style="yellow")
    table.add_column("Change", justify="right")

    for name, info in balances.items():
        balance = info.get("balance", 0.0)
        change = info.get("change", 0.0)
        change_style = "green" if change >= 0 else "red"
        change_prefix = "+" if change >= 0 else ""

        table.add_row(
            str(name),
            f"{balance:.2f}",
            Text(f"{change_prefix}{change:.2f}", style=change_style),
        )

    return table


def format_cost_table(telemetry: list[dict]) -> Table:
    """Format cost telemetry into a Rich table.

    Expected keys: persona_name, call_count, total_tokens, total_cost.
    """
    table = Table(title="Cost Report — Per Agent", show_lines=True)
    table.add_column("Agent", style="cyan")
    table.add_column("Calls", justify="right", style="green")
    table.add_column("Tokens", justify="right", style="yellow")
    table.add_column("Cost ($)", justify="right", style="red")

    for t in telemetry:
        table.add_row(
            str(t.get("persona_name", "N/A")),
            str(t.get("call_count", 0)),
            f"{t.get('total_tokens', 0):,}",
            f"${t.get('total_cost', 0.0):.6f}",
        )

    return table


def format_kg_stats(stats: dict) -> Panel:
    """Format KG statistics into a Rich panel.

    Expected keys from KGStats dataclass fields.
    """
    lines = [
        f"[bold cyan]Nodes:[/]          {stats.get('node_count', 0):,}",
        f"[bold cyan]Edges:[/]          {stats.get('edge_count', 0):,}",
        f"[bold cyan]Avg Confidence:[/] {stats.get('avg_confidence', 0.0):.3f}",
        "",
        "[bold]Status Breakdown:[/]",
        f"  Validated:  {stats.get('validated_count', 0):,}",
        f"  Proposed:   {stats.get('proposed_count', 0):,}",
        f"  Contested:  {stats.get('contested_count', 0):,}",
    ]

    node_types = stats.get("node_type_counts", {})
    if node_types:
        lines.append("")
        lines.append("[bold]Node Types:[/]")
        for ntype, count in sorted(node_types.items(), key=lambda x: -x[1]):
            lines.append(f"  {ntype}: {count:,}")

    rel_types = stats.get("relationship_type_counts", {})
    if rel_types:
        lines.append("")
        lines.append("[bold]Relationship Types:[/]")
        for rtype, count in sorted(rel_types.items(), key=lambda x: -x[1]):
            lines.append(f"  {rtype}: {count:,}")

    return Panel("\n".join(lines), title="Knowledge Graph Statistics", border_style="blue")
