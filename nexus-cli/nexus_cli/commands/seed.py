"""nexus seed — load seed data from seed/ directory."""

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console

console = Console()


async def _seed() -> dict:
    """Load seed data and return counts."""
    from nexus_core.config import get_settings
    from nexus_core.database import get_engine
    from nexus_core.utils.seed import load_seed_data

    settings = get_settings()
    engine = get_engine(settings)

    # Determine seed directory
    seed_dir = Path(__file__).parent.parent.parent.parent / "seed"

    if not seed_dir.exists():
        raise FileNotFoundError(f"Seed directory not found: {seed_dir}")

    # Count items to be loaded
    personas_file = seed_dir / "personas.json"
    tools_file = seed_dir / "tools.json"

    persona_count = 0
    tool_count = 0

    if personas_file.exists():
        personas = json.loads(personas_file.read_text(encoding="utf-8"))
        persona_count = len(personas)

    if tools_file.exists():
        tools = json.loads(tools_file.read_text(encoding="utf-8"))
        tool_count = len(tools)

    # Load seed data
    await load_seed_data(engine, seed_dir)

    return {
        "personas_loaded": persona_count,
        "tools_loaded": tool_count,
        "seed_dir": str(seed_dir),
    }


def seed() -> None:
    """Load seed data (personas and tools) from the seed/ directory."""
    console.print("[bold cyan]Loading seed data...[/]\n")

    try:
        results = asyncio.run(_seed())

        console.print(f"\n[bold green]Seed data loaded successfully.[/]")
        console.print(f"  [cyan]Personas:[/]  {results['personas_loaded']}")
        console.print(f"  [cyan]Tools:[/]     {results['tools_loaded']}")
        console.print(f"  [cyan]Source:[/]    {results['seed_dir']}\n")

    except FileNotFoundError as e:
        console.print(f"[red]Seed directory not found:[/] {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Error loading seed data:[/] {e}")
        raise typer.Exit(code=1)
