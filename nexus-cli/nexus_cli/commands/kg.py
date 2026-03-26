"""nexus kg-stats / nexus kg-search — knowledge graph commands."""

import asyncio
from dataclasses import asdict

import typer
from rich.console import Console
from rich.table import Table

from nexus_cli.formatters import format_kg_stats

console = Console()


async def _kg_stats() -> None:
    from nexus_core.database import get_connection
    from nexus_core.knowledge.query import get_kg_stats as _get_stats

    async with get_connection() as conn:
        stats = await _get_stats(conn)

    panel = format_kg_stats(asdict(stats))
    console.print(panel)


async def _kg_search(query: str, limit: int) -> None:
    from nexus_core.database import get_connection
    from nexus_core.knowledge.query import search_nodes

    async with get_connection() as conn:
        results = await search_nodes(conn, query, limit=limit)

    if not results:
        console.print(f"[yellow]No nodes found matching '{query}'.[/]")
        return

    table = Table(title=f"KG Search: '{query}'", show_lines=True)
    table.add_column("Label", style="cyan", max_width=40)
    table.add_column("Type", style="magenta")
    table.add_column("Confidence", justify="right", style="yellow")
    table.add_column("Status", style="bold")
    table.add_column("Similarity", justify="right", style="green")

    for node in results:
        confidence = node.get("confidence_score")
        conf_str = f"{float(confidence):.3f}" if confidence is not None else "N/A"
        sim = node.get("sim_score")
        sim_str = f"{float(sim):.3f}" if sim is not None else "N/A"

        table.add_row(
            str(node.get("label", "N/A"))[:40],
            str(node.get("node_type", "N/A")),
            conf_str,
            str(node.get("status", "N/A")),
            sim_str,
        )

    console.print(table)
    console.print(f"\n[dim]Found {len(results)} results[/]")


async def _kg_repair(*, apply_changes: bool) -> None:
    from nexus_core.database import get_connection
    from nexus_core.knowledge.repair import repair_duplicate_nodes

    async with get_connection() as conn:
        async with conn.begin():
            summary = await repair_duplicate_nodes(conn, dry_run=not apply_changes)

    mode_label = "apply" if apply_changes else "dry-run"
    console.print(f"[bold]KG duplicate repair ({mode_label})[/]")
    console.print(f"  clusters: {len(summary.clusters)}")
    console.print(f"  merged nodes: {summary.merged_node_count}")
    console.print(f"  deleted nodes: {summary.deleted_node_count}")
    console.print(f"  merged edges: {summary.merged_edge_count}")
    console.print(f"  deleted edges: {summary.deleted_edge_count}")

    if summary.clusters:
        table = Table(title="Duplicate node clusters", show_lines=True)
        table.add_column("Type", style="magenta")
        table.add_column("Canonical label", style="cyan", max_width=28)
        table.add_column("Primary", style="green", max_width=28)
        table.add_column("Duplicates", style="yellow", max_width=50)
        for cluster in summary.clusters:
            table.add_row(
                cluster.node_type,
                cluster.canonical_label,
                cluster.primary_label,
                ", ".join(cluster.duplicate_labels),
            )
        console.print(table)


def kg_stats() -> None:
    """Show knowledge graph statistics."""
    try:
        asyncio.run(_kg_stats())
    except Exception as e:
        console.print(f"[red]Error fetching KG stats:[/] {e}")
        raise typer.Exit(code=1)


def kg_search(
    query: str = typer.Argument(..., help="Search query for KG node labels"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results to return"),
) -> None:
    """Search knowledge graph nodes by label (fuzzy matching)."""
    try:
        asyncio.run(_kg_search(query, limit))
    except Exception as e:
        console.print(f"[red]Error searching KG:[/] {e}")
        raise typer.Exit(code=1)


def kg_repair(
    apply_changes: bool = typer.Option(
        False,
        "--apply",
        help="Apply the duplicate-node repair instead of running a dry-run audit.",
    ),
) -> None:
    """Audit or repair duplicate knowledge graph nodes."""
    try:
        asyncio.run(_kg_repair(apply_changes=apply_changes))
    except Exception as e:
        console.print(f"[red]Error repairing KG:[/] {e}")
        raise typer.Exit(code=1)
