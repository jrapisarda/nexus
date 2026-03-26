"""nexus config — update runtime configuration."""

import asyncio
import os

import typer
from rich.console import Console

console = Console()

# Allowed configuration keys and their types for validation
ALLOWED_KEYS = {
    "MOONSHOT_API_KEY": str,
    "MOONSHOT_BASE_URL": str,
    "MOONSHOT_MODEL": str,
    "BUDGET_CEILING_USD": float,
    "MAX_CONCURRENT_CALLS": int,
    "RENT_DECAY_RATE": float,
    "RENT_DECAY_INTERVAL_MINS": int,
    "SURVIVAL_THRESHOLD": float,
    "MAX_ACTIVE_PERSONAS": int,
    "MUTATION_MAX_EDIT_DISTANCE_PCT": float,
    "DIVERSITY_THRESHOLD": float,
    "CONFIDENCE_DECAY_PER_HOP": float,
    "DEDUP_SIMILARITY_THRESHOLD": float,
    "MAX_DAG_DEPTH": int,
    "MAX_DAG_FANOUT": int,
    "CIRCUIT_BREAKER_FAIL_MAX": int,
    "CIRCUIT_BREAKER_RESET_TIMEOUT_SECS": int,
    "REVIEW_VARIANCE_THRESHOLD": float,
    "LOG_LEVEL": str,
    "LOG_FORMAT": str,
    "PUBMED_API_KEY": str,
    "USPTO_API_KEY": str,
    "DREAM_CYCLE_INACTIVITY_SECS": int,
    "MIN_PERSONAS_PER_ROLE_CLASS": int,
}


def _update_env_file(key: str, value: str) -> None:
    """Update or add a key=value pair in the .env file."""
    from pathlib import Path

    env_path = Path(__file__).parent.parent.parent.parent / ".env"

    lines = []
    found = False

    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                    lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)

    if not found:
        lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def config(
    key: str = typer.Argument(..., help="Configuration key to set"),
    value: str = typer.Argument(..., help="New value for the configuration key"),
) -> None:
    """Update a NEXUS runtime configuration value (writes to .env file)."""
    if key not in ALLOWED_KEYS:
        console.print(f"[red]Unknown config key: {key}[/]")
        console.print(f"\n[dim]Allowed keys:[/]")
        for k in sorted(ALLOWED_KEYS.keys()):
            console.print(f"  {k}")
        raise typer.Exit(code=1)

    # Validate type
    expected_type = ALLOWED_KEYS[key]
    try:
        if expected_type == int:
            int(value)
        elif expected_type == float:
            float(value)
    except ValueError:
        console.print(f"[red]Invalid value for {key}: expected {expected_type.__name__}, got '{value}'[/]")
        raise typer.Exit(code=1)

    try:
        _update_env_file(key, value)
        # Also update the environment variable for the current process
        os.environ[key] = value

        console.print(f"\n[bold green]Configuration updated.[/]")
        console.print(f"  [cyan]{key}[/] = {value}")
        console.print(f"\n[dim]Written to .env file. Restart running services to apply.[/]")
    except Exception as e:
        console.print(f"[red]Error updating configuration:[/] {e}")
        raise typer.Exit(code=1)
