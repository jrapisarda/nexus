"""nexus scout — manually trigger a scout sweep of external data sources."""

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()

VALID_SOURCES = {"pubmed", "clinicaltrials", "biorxiv", "uspto", "google_patents"}


async def _scout(source: Optional[str]) -> list[dict]:
    """Run scout sweep across external data sources."""
    from nexus_core.config import get_settings
    from nexus_core.database import get_engine, dispose_engine
    from nexus_core.scouts.workflow import run_scout_sweep

    settings = get_settings()
    engine = get_engine(settings)
    try:
        summary = await run_scout_sweep(engine, settings, source=source)
    finally:
        await dispose_engine()

    return summary["persisted_findings"]


def scout(
    source: Optional[str] = typer.Option(
        None,
        "--source",
        "-s",
        help="Specific source: pubmed, clinicaltrials, biorxiv, uspto, google_patents",
    ),
) -> None:
    """Manually trigger a scout sweep of external data sources."""
    if source and source not in VALID_SOURCES:
        console.print(f"[red]Invalid source '{source}'. Valid: {', '.join(sorted(VALID_SOURCES))}[/]")
        raise typer.Exit(code=1)

    console.print("[bold cyan]Starting scout sweep...[/]\n")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Scanning external sources...", total=None)
            findings = asyncio.run(_scout(source))
            progress.update(task, description="[green]Scout sweep complete!")

        if not findings:
            console.print("[yellow]No findings from scout sweep.[/]")
            return

        table = Table(title="Scout Findings", show_lines=True)
        table.add_column("Title", style="cyan", max_width=50)
        table.add_column("Source", style="magenta")
        table.add_column("Relevance", justify="right", style="yellow")
        table.add_column("Date", style="dim")

        for f in findings:
            table.add_row(
                str(f["title"])[:50],
                str(f["source"]),
                f"{f['relevance']:.2f}",
                str(f["date"]),
            )

        console.print(table)
        console.print(f"\n[dim]Total: {len(findings)} findings[/]")

    except Exception as e:
        console.print(f"\n[red]Scout sweep failed:[/] {e}")
        raise typer.Exit(code=1)
