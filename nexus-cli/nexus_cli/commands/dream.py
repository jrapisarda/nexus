"""nexus dream — manually trigger a Dream Cycle."""

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


async def _dream() -> dict:
    """Run a dream cycle: cross-pollinate knowledge, generate hypotheses.

    The dream cycle queries the KG for recent nodes and uses the LLM to
    generate novel hypotheses by combining disparate knowledge areas.
    """
    import sqlalchemy as sa
    from nexus_core.config import get_settings
    from nexus_core.database import get_connection
    from nexus_core.knowledge.query import get_recent_nodes
    from nexus_core.llm.client import KimiClient
    from nexus_core.utils.cost import CostGuard
    from nexus_core.utils.events import emit_event

    settings = get_settings()
    cost_guard = CostGuard.from_settings(settings)
    kimi_client = KimiClient(settings, cost_guard)

    results = {
        "recent_nodes_analyzed": 0,
        "hypotheses_generated": 0,
        "objectives_proposed": 0,
    }

    try:
        async with get_connection() as conn:
            # Get recent KG nodes for cross-pollination
            recent_nodes = await get_recent_nodes(conn, limit=20)
            results["recent_nodes_analyzed"] = len(recent_nodes)

            if not recent_nodes:
                return results

            # Build context from recent knowledge
            node_summaries = []
            for node in recent_nodes:
                label = node.get("label", "")
                ntype = node.get("node_type", "")
                node_summaries.append(f"[{ntype}] {label}")

            context = "\n".join(node_summaries)

            # Ask LLM to generate cross-domain hypotheses
            system_prompt = (
                "You are the NEXUS Dream Engine. Your role is to find non-obvious "
                "connections between disparate research findings and propose novel "
                "hypotheses that could lead to breakthroughs. Be creative but grounded."
            )
            user_prompt = (
                f"Here are recent knowledge graph entries:\n\n{context}\n\n"
                "Identify 2-3 non-obvious connections and propose research hypotheses "
                "that bridge these areas. For each, provide:\n"
                "1. The connection you see\n"
                "2. A testable hypothesis\n"
                "3. A suggested research objective\n\n"
                "Format as structured text."
            )

            response = await kimi_client.call_thinking(
                system=system_prompt,
                user=user_prompt,
                max_tokens=4096,
            )

            results["hypotheses_generated"] = response.content.count("hypothesis") + response.content.count("Hypothesis")
            results["dream_output"] = response.content

            # Emit event
            async with conn.begin():
                await emit_event(
                    conn,
                    "dream_cycle.completed",
                    payload={
                        "nodes_analyzed": results["recent_nodes_analyzed"],
                        "cost_usd": str(response.cost_usd),
                    },
                )
    finally:
        await kimi_client.close()

    return results


def dream() -> None:
    """Manually trigger a Dream Cycle (cross-pollinate knowledge, generate hypotheses)."""
    console.print("[bold magenta]Initiating Dream Cycle...[/]\n")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Dreaming... (analyzing KG, generating hypotheses)", total=None)
            results = asyncio.run(_dream())
            progress.update(task, description="[green]Dream cycle complete!")

        console.print(Panel(
            f"[cyan]Nodes Analyzed:[/]       {results['recent_nodes_analyzed']}\n"
            f"[cyan]Hypotheses Found:[/]     {results.get('hypotheses_generated', 0)}",
            title="Dream Cycle Results",
            border_style="magenta",
        ))

        if results.get("dream_output"):
            console.print("\n[bold]Dream Output:[/]")
            console.print(results["dream_output"])

    except Exception as e:
        console.print(f"\n[red]Dream cycle failed:[/] {e}")
        raise typer.Exit(code=1)
