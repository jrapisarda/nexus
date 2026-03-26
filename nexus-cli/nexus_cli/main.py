"""NEXUS CLI — command-line interface for the agent civilization."""

import typer

app = typer.Typer(
    name="nexus",
    help="NEXUS -- Self-Evolving Agent Research Civilization",
    add_completion=False,
)

# Import and register command groups
from nexus_cli.commands import (  # noqa: E402
    submit,
    status,
    agents,
    objectives,
    kg,
    economy,
    evolve,
    dream,
    scout,
    cost,
    config,
    seed,
)

app.command()(submit.submit)
app.command()(status.status)
app.command(name="agents")(agents.agents)
app.command(name="agent")(agents.agent_detail)
app.command(name="objectives")(objectives.objectives_cmd)
app.command(name="kg-stats")(kg.kg_stats)
app.command(name="kg-search")(kg.kg_search)
app.command(name="kg-repair")(kg.kg_repair)
app.command(name="economy")(economy.economy_cmd)
app.command()(evolve.evolve)
app.command()(dream.dream)
app.command()(scout.scout)
app.command()(cost.cost)
app.command()(config.config)
app.command()(seed.seed)


if __name__ == "__main__":
    app()
