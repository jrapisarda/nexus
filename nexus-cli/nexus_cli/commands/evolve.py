"""nexus evolve — manually trigger an evolution cycle."""

import asyncio

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


async def _evolve() -> None:
    from nexus_core.config import get_settings
    from nexus_core.database import get_engine
    from nexus_core.llm.client import KimiClient
    from nexus_core.utils.cost import CostGuard
    from nexus_core.evolution.pruner import run_evolution_cycle

    settings = get_settings()
    engine = get_engine(settings)
    cost_guard = CostGuard.from_settings(settings)
    kimi_client = KimiClient(settings, cost_guard)

    try:
        await run_evolution_cycle(engine, kimi_client, settings)
    finally:
        await kimi_client.close()


def evolve() -> None:
    """Manually trigger an evolution cycle (mutate, evaluate, prune)."""
    console.print("[bold cyan]Starting evolution cycle...[/]\n")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Running evolution cycle...", total=None)
            asyncio.run(_evolve())
            progress.update(task, description="[green]Evolution cycle complete!")

        console.print("\n[bold green]Evolution cycle finished successfully.[/]")
        console.print("[dim]Check 'nexus agents' to see updated population.[/]")
    except Exception as e:
        console.print(f"\n[red]Evolution cycle failed:[/] {e}")
        raise typer.Exit(code=1)
