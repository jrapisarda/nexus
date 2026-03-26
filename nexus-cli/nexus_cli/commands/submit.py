"""nexus submit — create a new objective with optional file attachments."""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

console = Console()


async def _upload_file_via_api(api_url: str, file_path: Path) -> str:
    """Upload a file to the NEXUS API and return the attachment_id."""
    import httpx

    async with httpx.AsyncClient(timeout=60.0) as client:
        with open(file_path, "rb") as f:
            resp = await client.post(
                f"{api_url}/api/files",
                files={"file": (file_path.name, f)},
            )
        resp.raise_for_status()
        data = resp.json()
        return data["attachment_id"]


async def _submit_via_api(
    api_url: str,
    description: str,
    priority: int,
    objective_type: str,
    attachment_ids: list[str],
) -> dict:
    """Submit an objective via the NEXUS API."""
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{api_url}/api/objectives",
            json={
                "title": description[:500],
                "description": description,
                "objective_type": objective_type,
                "priority": priority,
                "attachment_ids": attachment_ids,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _submit_direct(description: str, priority: int, objective_type: str) -> None:
    """Direct DB submission (no files, no API required)."""
    from nexus_core.database import get_connection
    from nexus_core.models.objectives import objectives
    from nexus_core.utils.events import emit_event

    async with get_connection() as conn:
        async with conn.begin():
            result = await conn.execute(
                objectives.insert()
                .values(
                    title=description[:500],
                    description=description,
                    objective_type=objective_type,
                    priority=priority,
                    status="proposed",
                    proposed_by_type="human",
                )
                .returning(objectives.c.objective_id, objectives.c.created_at)
            )
            row = result.first()
            objective_id = row.objective_id
            created_at = row.created_at

            await emit_event(
                conn,
                "objective.created",
                entity_id=objective_id,
                entity_type="objective",
                payload={
                    "title": description[:500],
                    "type": objective_type,
                    "priority": priority,
                },
            )

    console.print(f"\n[bold green]Objective created successfully.[/]")
    console.print(f"  [cyan]ID:[/]       {objective_id}")
    console.print(f"  [cyan]Type:[/]     {objective_type}")
    console.print(f"  [cyan]Priority:[/] {priority}")
    console.print(f"  [cyan]Created:[/]  {created_at}")
    console.print(f"  [cyan]Status:[/]   proposed\n")


async def _submit_with_files(
    description: str,
    priority: int,
    objective_type: str,
    file_paths: list[Path],
) -> None:
    """Upload files via API, then submit objective with attachment IDs."""
    from nexus_core.config import get_settings

    settings = get_settings()
    api_url = settings.NEXUS_API_URL

    # Upload each file
    attachment_ids: list[str] = []
    for fp in file_paths:
        if not fp.exists():
            console.print(f"[red]File not found: {fp}[/]")
            raise typer.Exit(code=1)
        console.print(f"  Uploading [cyan]{fp.name}[/]...", end=" ")
        try:
            att_id = await _upload_file_via_api(api_url, fp)
            attachment_ids.append(att_id)
            console.print(f"[green]OK[/] ({att_id[:8]}...)")
        except Exception as e:
            console.print(f"[red]FAILED[/]: {e}")
            raise typer.Exit(code=1)

    # Submit objective
    try:
        data = await _submit_via_api(
            api_url, description, priority, objective_type, attachment_ids
        )
    except Exception as e:
        console.print(f"[red]Error submitting objective:[/] {e}")
        raise typer.Exit(code=1)

    console.print(f"\n[bold green]Objective created successfully.[/]")
    console.print(f"  [cyan]ID:[/]       {data['objective_id']}")
    console.print(f"  [cyan]Type:[/]     {objective_type}")
    console.print(f"  [cyan]Priority:[/] {priority}")
    console.print(f"  [cyan]Files:[/]    {len(attachment_ids)}")
    console.print(f"  [cyan]Status:[/]   proposed\n")


def submit(
    description: str = typer.Argument(..., help="Description of the objective"),
    priority: int = typer.Option(5, "--priority", "-p", min=1, max=10, help="Priority (1-10)"),
    objective_type: str = typer.Option(
        "strategic",
        "--type",
        "-t",
        help="Objective type: strategic, tactical, or exploratory",
    ),
    file: Optional[list[Path]] = typer.Option(
        None,
        "--file",
        "-f",
        help="Attach a research context file (repeatable). Requires API to be running.",
        exists=True,
        readable=True,
    ),
) -> None:
    """Submit a new research objective to NEXUS.

    Optionally attach research context files (gene lists, CSVs, PDFs, images)
    using the --file flag. Files are uploaded via the NEXUS API.
    """
    if objective_type not in ("strategic", "tactical", "exploratory"):
        console.print(f"[red]Invalid type '{objective_type}'. Must be strategic, tactical, or exploratory.[/]")
        raise typer.Exit(code=1)

    try:
        if file:
            console.print(f"\n[bold]Submitting objective with {len(file)} file(s)...[/]")
            asyncio.run(_submit_with_files(description, priority, objective_type, file))
        else:
            asyncio.run(_submit_direct(description, priority, objective_type))
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error submitting objective:[/] {e}")
        raise typer.Exit(code=1)
