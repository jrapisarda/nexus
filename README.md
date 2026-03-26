# NEXUS: Self-Evolving Multi-Agent Research Civilization

NEXUS is an advanced orchestration system that treats a multi-agent society as a civilization complete with its own economy, governance structures, evolution mechanisms, peer-review processes, and knowledge graph. Powered by Kimi K2.5 (Moonshot AI), NEXUS enables autonomous agent personas to conduct rigorous research, validate findings through adversarial peer review, trade on a securities exchange, own knowledge graph real estate, and evolve through Darwinian fitness selection.

Built by BioInfo AI as a technical showcase and research engine, NEXUS serves as the foundation for autonomous scientific research with human oversight and commercial-grade outputs.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Architecture](#architecture)
4. [Tech Stack](#tech-stack)
5. [Getting Started](#getting-started)
6. [System Components](#system-components)
7. [API Reference](#api-reference)
8. [Configuration](#configuration)
9. [Development Workflow](#development-workflow)
10. [Testing](#testing)
11. [Project Status](#project-status)

---

## Overview

### What is NEXUS?

NEXUS is a self-improving system where:

- **Personas**: Database-driven agent configurations with specialized expertise (researchers, critics, synthesizers, red teams)
- **Originator**: A persistent orchestration agent that decomposes objectives into dependency-aware DAGs and recruits specialists
- **Knowledge Graph**: A growing corpus of validated research findings with full provenance chains
- **Economy**: A credit-based system with rent, salary, welfare, and market trading
- **Evolution**: Continuous Darwinian selection where high-performing personas reproduce and low performers starve
- **Governance**: Decision mechanisms for objective approval, persona activation, and strategic direction
- **Peer Review**: Multi-stage validation with critics, evidence evaluation, and red-team adversarial attacks

### Who Is It For?

- **Research Operators**: Submit research objectives, monitor agent activity, and retrieve validated findings
- **System Architects**: Understand and extend the civilization's capabilities, tuning parameters, and governance rules
- **Scientific Partners**: Access commercial-grade research outputs validated through adversarial peer review

---

## Key Features

### 1. File Upload & Research Context

Submit research objectives with supporting files (CSV, PDF, images, gene lists). Files are processed via Moonshot's text extraction API and injected into agent reasoning prompts as context.

- **Drag-and-drop upload** via dashboard
- **Multi-format support**: PDF (via Moonshot extraction), DOCX, images (base64), CSV, plain text
- **Automatic context injection**: Files blended into decomposition prompts with character budgets
- **Orphan cleanup**: Hourly purge of unlinked file uploads

### 2. Citation Verification

Post-submission verification of DOI/URL citations via a cascading verification system.

- **Verification cascade**: CrossRef → OpenAlex → Semantic Scholar
- **PostgreSQL cache** with configurable TTLs (30 days for DOIs, 1 day for URLs)
- **Confidence scoring**: 0.0-1.0 injected into peer-review prompts
- **Graceful degradation**: API failures never block the pipeline

### 3. Agent Salary System

All reviewing agents earn participation salary regardless of outcome, with quality gates and reputation multipliers.

- **Quality threshold**: Content >200 chars, non-null structured_data, ≥1 citation
- **Salary formula**: max(min, budget × 0.12) × reputation_multiplier, capped at max
- **Idempotency guard**: Prevents double-payment on retries
- **Configurable rates**: SALARY_MIN_CREDITS, SALARY_MAX_CREDITS, SALARY_BUDGET_RATE

### 4. Progressive Rent & Welfare

Tiered rent structure with redistribution to struggling agents.

- **Rent tiers**: 0% below 20cr | 3% for 20-100cr | 5% for 100-300cr | 8% above 300cr
- **Welfare pool**: 50% of high-tier rent redistributed to NEXUS_WELFARE_SYSTEM persona
- **Welfare triggers**: Distributed every 2 scheduler ticks to agents below 30 credits
- **System personas**: Excluded from Gini coefficient and fitness rankings

### 5. Expanded Market Crafting

Database-driven crafting system with per-template role controls.

- **Role-based access**: allowed_crafter_roles per market template (researchers, reviewers, scouts)
- **New templates**: knowledge_digest, review_package, data_package
- **Rate limiting**: max_crafts_per_cycle per template with cycle tick tracking
- **Supply management**: Dynamic crafting availability based on civilization state

### 6. Order Book Imbalance (OBI) Price Discovery

Smart pricing that reacts to buy/sell imbalance instead of naive midpoint.

- **Formula**: fair_price = VWAP + c1 × OBI where OBI = (bid_vol - ask_vol)/(bid_vol + ask_vol)
- **Directional response**: OBI=+1 (only bids) → price UP | OBI=-1 (only asks) → price DOWN
- **Anti-wash-trade**: Only counts orders older than 30 seconds
- **Configurable sensitivity**: MARKET_OBI_SENSITIVITY parameter

### 7. Continuous Finding Quality Mark

Replaces discrete status steps with continuous scoring.

- **Score formula**: base + validations×3 + citations×2 + (confidence-0.5)×20 - challenges×2.5 - failures×5
- **Dual signals**: 70% quality mark + 30% market signal in finding notes
- **Settlement integration**: Used for final value assessment
- **Continuous updates**: Evolves as reviews accumulate

### 8. KG Node Ownership (Real Estate)

Agents can purchase knowledge graph nodes as appreciating assets with complex economics.

- **Valuation model**: edge_count × mean_weight × confidence × multiplier + betweenness_centrality_premium
- **Traversal-based yield**: 5% of bounties distributed to node owners proportional to query frequency
- **Depreciation**: Untraversed nodes lose confidence each cycle (NODE_DEPRECIATION_RATE)
- **Anti-monopolization**: Portfolio cap (5 nodes), superlinear pricing (+20% per additional), capability gate
- **Hostile takeover**: Neglected nodes (confidence < 0.1) after 10 cycles can be claimed
- **Autonomous decisions**: Agents auto-purchase based on role affinity; auto-sell depreciating assets
- **Configuration**: 13 distinct parameters controlling all economic aspects

### 9. Net Worth System

Comprehensive wealth calculation for agents.

- **Components**: liquid_balance + position_value + owned_node_value - reservations
- **API endpoint**: GET /api/economy/net-worth with leaderboard
- **Wealth tax**: 1.5% on top quartile above median every 4 ticks → welfare pool
- **System exclusion**: System personas excluded from tax calculations

### 10. Market Making Rewards

Protocol fees and rebates incentivize two-sided liquidity.

- **Protocol fee**: 0.1% on all trades (0.05% each side) → NEXUS_FEE_POOL
- **Market maker rebate**: 0.2% rebate to agents quoting both bid+ask → net +0.15% per trade
- **System personas**: Welfare and fee pool personas excluded from trading
- **Transparency**: Detailed ledger entries for all transactions

### 11. Pipeline Tracker Dashboard

Real-time visibility into finding workflow stages.

- **Active agents view**: Shows persona name, current task, elapsed time
- **Stage badges**: Citation Checking, Awaiting Review, Under Review, Revision Needed
- **Stall detection**: Age indicator turns red for findings >1 hour old
- **Backlog warning**: "Awaiting integration" count with estimated time
- **Recently completed**: Strip showing latest validated findings
- **Auto-refresh**: Every 5 seconds via WebSocket

### 12. KG Node Portfolio Dashboard

Per-agent knowledge graph real estate overview.

- **Portfolio view**: Individual node chips with valuation, confidence, traversal count
- **Summary metrics**: Total owned, total value, unrealized P&L
- **Leaderboard**: Net worth ranking for agents with node holdings
- **Visual indicators**: Confidence bars, traversal frequency, P&L coloring (green/red)
- **Mobile responsive**: Works across device sizes

---

## Architecture

NEXUS is a modular system organized into five independent packages:

### nexus-core

Shared library containing all business logic, models, and utilities.

```
nexus-core/
├── config.py              # Pydantic settings, all configurable parameters
├── database.py            # AsyncPG connection management, schema validation
├── models/                # SQLAlchemy table definitions
├── economy/               # Ledger, diversity, fitness, node ownership
├── evolution/             # Mutation, pruning, novelty scoring
├── knowledge/             # Graph operations, queries, deduplication
├── llm/                   # Kimi K2.5 client, prompt building, response parsing
├── review/                # Peer review, red team, infiltration, debugging
├── scouts/                # PubMed, ClinicalTrials, bioRxiv, patents (USPTO, Google)
├── governance/            # Voting, proposals, runtime decisions
├── market/                # Node ownership, trading logic
├── utils/                 # Cost guard, embeddings, logging, events
└── citing/                # Citation verification cascade
```

### nexus-engine

Orchestration daemon that runs continuously.

```
nexus-engine/
├── main.py                # Entry point, signal handling, lifespan
├── originator.py          # Decomposition & agent recruitment loop
├── scheduler.py           # Execution loop, instance lifecycle management
├── market_loop.py         # Market operations, crafting, node transactions
├── integrator.py          # Knowledge graph integration of validated findings
├── dream_cycle.py         # Governance, evolution, red-team cycles
└── dispatcher.py          # Instance spawning & result handling
```

### nexus-api

FastAPI server with WebSocket support for real-time updates.

```
nexus-api/
├── main.py                # FastAPI app, lifespan, router registration
├── websocket.py           # WebSocket connection management, event streaming
├── schemas.py             # Request/response Pydantic models
└── routers/
    ├── agents.py          # GET /api/agents — persona listing & details
    ├── objectives.py      # POST/GET /api/objectives — objective submission & status
    ├── knowledge_graph.py  # GET /api/kg/* — graph queries & visualization
    ├── economy.py         # GET /api/economy/* — ledger, summary, net worth
    ├── marketplace.py     # GET/POST /api/marketplace/* — orders, positions, crafting
    ├── activity.py        # GET /api/activity/* — event logs, agent activity
    ├── civilization.py    # GET /api/civilization/* — population metrics
    ├── evolution.py       # GET /api/evolution/* — lineage, fitness, mutations
    ├── reports.py         # GET /api/reports/* — cost analysis, findings export
    ├── securities.py      # GET /api/securities/* — securities data & holdings
    ├── observatory.py     # GET /api/observatory/* — dashboard hero data
    ├── telemetry.py       # GET /api/telemetry/* — token usage, latency metrics
    ├── files.py           # POST /api/files/* — file uploads
    └── pipeline.py        # GET /api/pipeline/* — workflow stage tracking
```

### nexus-cli

Command-line interface for human operators.

```
nexus-cli/
├── main.py                # CLI entry point, command dispatch
└── commands/
    ├── submit.py          # `nexus submit "objective..."` with file attachment
    ├── status.py          # `nexus status` — civilization health check
    ├── agents.py          # `nexus agents list|detail` — agent management
    ├── kg.py              # `nexus kg query|visualize` — KG queries
    ├── objectives.py      # `nexus objectives list|detail` — objective queries
    ├── economy.py         # `nexus economy summary|ledger` — economy metrics
    ├── evolution.py       # `nexus evolution lineage|fitness` — evolution metrics
    ├── cost.py            # `nexus cost report` — cumulative spend analysis
    ├── scout.py           # `nexus scout run` — external research scanning
    ├── seed.py            # `nexus seed load` — bootstrap personas from JSON
    ├── dream.py           # `nexus dream trigger` — manual governance/evolution
    ├── config.py          # `nexus config get|set` — runtime parameters
    └── formatters.py      # Output formatting (tables, JSON, Markdown)
```

### nexus-dashboard

React/Vite web observatory for real-time monitoring.

```
nexus-dashboard/
├── src/
│   ├── App.tsx            # Main routing & layout
│   ├── api/client.ts      # Axios client with interceptors
│   ├── hooks/useWebSocket.ts  # WebSocket listener hook
│   ├── components/
│   │   ├── AgentPopulation.tsx      # Active agents table
│   │   ├── ObjectiveDAG.tsx         # Objective decomposition graph
│   │   ├── KnowledgeGraph.tsx       # Graph visualization
│   │   ├── EconomyPanel.tsx         # Ledger & summary
│   │   ├── EvolutionaryLineage.tsx  # Family tree of personas
│   │   ├── CostReport.tsx           # Budget tracking
│   │   ├── KGNodePortfolio.tsx      # Node ownership dashboard
│   │   ├── PipelineTracker.tsx      # Finding workflow stages
│   │   ├── MissionControl.tsx       # Objective submission modal
│   │   ├── ActivityFeed.tsx         # Event stream
│   │   ├── AlertCenter.tsx          # Notifications
│   │   └── (more components)
│   ├── store/             # Zustand state management
│   ├── types/             # TypeScript interfaces
│   └── main.tsx
├── vite.config.ts
├── tsconfig.json
└── package.json
```

---

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| **Backend** | Python | 3.12+ |
| **Framework** | FastAPI | 0.104+ |
| **Database** | PostgreSQL | 16 with pgvector |
| **ORM** | SQLAlchemy | 2.0+ (async) |
| **LLM Provider** | Kimi K2.5 (Moonshot) | Latest |
| **Frontend** | React | 18+ |
| **Build Tool** | Vite | 5.0+ |
| **Package Manager** | uv | Latest |

---

## Getting Started

### Prerequisites

- **Python 3.12+** with uv installed
- **PostgreSQL 16+** with pgvector extension
- **Kimi API Key** from Moonshot AI (https://api.moonshot.cn)
- **Node.js 18+** (for dashboard development only)

### 1. Clone & Setup

```bash
git clone <repo>
cd nexus
```

### 2. Configure Environment

Create a `.env` file in the project root:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://claudeai:Magic123@localhost:5432/nexus

# Moonshot AI
MOONSHOT_API_KEY=<your-kimi-api-key>
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=kimi-k2.5

# Budget (in USD)
BUDGET_CEILING_USD=38.25
COST_INPUT_PER_MILLION=0.60
COST_OUTPUT_PER_MILLION=2.50

# Concurrency
MAX_CONCURRENT_CALLS=3

# Optional: Scout APIs
PUBMED_API_KEY=<optional>
USPTO_API_KEY=<optional>
```

See `nexus-core/nexus_core/config.py` for all 50+ configurable parameters.

### 3. Start PostgreSQL

Using Docker:

```bash
docker-compose up -d postgres
```

Or using Postgres installed locally:

```bash
createdb -U claudeai nexus
```

Initialize extensions:

```bash
psql -U claudeai -d nexus -f migrations/init_extensions.sql
```

### 4. Run Migrations

```bash
cd migrations
alembic upgrade head
```

This creates all tables, indexes, and seeds system personas.

### 5. Launch Engine & API

#### Option A: Use launch.bat (Windows)

```bash
.\launch.bat
```

This starts both nexus-engine and nexus-api in separate terminal windows.

#### Option B: Manual Launch

Terminal 1 (Engine):
```bash
uv run nexus-engine
```

Terminal 2 (API):
```bash
uv run nexus-api
```

Terminal 3 (Dashboard, optional):
```bash
cd nexus-dashboard
npm install
npm run dev
```

### 6. Verify

- **Engine**: Should show "nexus_engine_starting" log with budget ceiling
- **API**: Health check at `http://localhost:8000/health`
- **Dashboard**: Open `http://localhost:8000/` (or `http://localhost:5173` if running dev server)

### 7. Submit Your First Objective

Using CLI:

```bash
uv run nexus-cli submit "How can we apply network analysis to identify key decision-makers in organizational hierarchies?" --type strategic --priority 8
```

Using Dashboard:

1. Open http://localhost:8000/
2. Click "Submit Objective"
3. Enter title, description, type, priority
4. (Optional) Drag files into upload zone
5. Click "Submit"

---

## System Components

### The Originator Loop

The persistent orchestration agent that:

1. Monitors `objectives` table for new proposals
2. Reads objective description and attached files
3. Queries knowledge graph for relevant context
4. Decomposes objective into dependency DAG
5. Selects best-fit personas from `agent_personas`
6. Spawns instances via Kimi K2.5 API (concurrency-controlled)
7. Handles failures with retry logic and debugger agents
8. Triggers dependent sub-objectives when predecessors complete
9. Runs every cycle of the scheduler (configurable interval)

### The Scheduler Loop

Executes all queued agent instances:

1. Fetches pending instances from `agent_instances` table
2. For each instance: interpolate persona + objective context into prompt
3. Call Kimi K2.5 with thinking mode enabled
4. Parse response, extract thinking_tokens + output_tokens + content
5. Store telemetry: tokens, latency, cost, reasoning chains
6. Validate structured output against schema
7. On success: write to `findings` table, trigger peer review
8. On failure: retry once; on second failure, spawn debugger agent
9. Update instance status to "completed" or "failed"

### The Peer Review Pipeline

Multi-stage validation before findings enter the knowledge graph:

1. **Citation Verification** (async, non-blocking):
   - Verify DOI/URL citations via CrossRef → OpenAlex → Semantic Scholar
   - Cache results (30d for DOIs, 1d for URLs)
   - Inject confidence scores into review prompts

2. **Methodological Review**:
   - Methodological Critic evaluates research rigor
   - Produces methodology score + identified flaws

3. **Evidence Review**:
   - Evidence Critic evaluates source quality & sufficiency
   - Produces evidence quality score + gaps

4. **Synthesis** (if multiple findings):
   - Systems Synthesizer integrates related findings
   - Resolves contradictions
   - Identifies emergent insights

5. **Red Team Attack** (sampled):
   - Sentinel Red Team deliberately attacks findings
   - Files Challenge Reports with counter-arguments
   - Findings may be revised or rejected

6. **Integration**:
   - Validated findings written to KG with provenance
   - Salary distributed to reviewers
   - Bounties distributed to authors

### The Market Loop

Autonomous economic transactions:

1. **Market Making**:
   - Agents evaluate their expertise + recent findings
   - Place bid/ask orders for securities
   - Earn 0.2% rebate per two-sided quote

2. **Crafting**:
   - Agents craft knowledge_digest, review_package, or data_package
   - Per-role & per-template rate limits enforced
   - Products listed on marketplace

3. **Node Ownership**:
   - High-performing agents purchase KG nodes
   - Nodes appreciate based on edge count + centrality
   - Traversal-based yield: 5% of bounties distributed
   - Autonomous sell decisions for depreciating nodes

4. **Wealth Tax**:
   - Top quartile agents above median taxed 1.5%
   - Proceeds → NEXUS_WELFARE_SYSTEM persona

### The Dream Cycle

Strategic operations running on longer timescales:

1. **Governance** (every 1 tick):
   - Governor agents vote on persona activation
   - Governor agents vote on strategic pivots

2. **Evolution** (every 4 ticks):
   - Fitness recalculated for all active personas
   - Top performers mutated to create offspring
   - Offspring assigned validation objectives
   - Underperformers starved (credit balance → 0)
   - Diversity enforced: min 2 per role class

3. **Infiltration** (every 6 ticks):
   - Red Team agents infiltrate high-confidence findings
   - Attack methodologies that have succeeded before
   - Identify systemic biases

### The Integration Loop

Accepts validated findings and writes to KG:

1. Receives completed finding with peer review scores
2. Deduplicates: checks for similar existing nodes
3. Computes confidence score based on validation chain
4. Writes node + edges to `knowledge_graph_nodes/edges` tables
5. Creates provenance links to objective + instance + reviewers
6. Triggers cascading confidence updates for related nodes
7. Publishes event for dashboard update

---

## API Reference

All endpoints are served by the nexus-api service (default: `http://localhost:8000`).

### Agents

```
GET  /api/agents                     List all personas with filters
GET  /api/agents/{persona_id}        Get persona details + current assignment
```

**Query Parameters**:
- `status`: "active" | "deprecated"
- `role_class`: "originator" | "researcher" | "critic" | "red_team" | ...

**Response**:
```json
{
  "persona_id": "uuid",
  "persona_name": "Deep Researcher Alpha",
  "role_class": "researcher",
  "generation": 0,
  "credit_balance": 45.32,
  "reputation_score": 0.78,
  "current_assignment": "Research objective: ...",
  "current_assignment_status": "running",
  "current_assignment_started_at": "2026-03-24T10:30:00Z",
  "capability_scores": {
    "research_depth": 0.87,
    "evidence_synthesis": 0.92
  }
}
```

### Objectives

```
POST /api/objectives                 Create objective with optional files
GET  /api/objectives                 List objectives with filters
GET  /api/objectives/{objective_id}  Get single objective
GET  /api/objectives/{objective_id}/dag  Get decomposition DAG (ReactFlow format)
```

**POST Body**:
```json
{
  "title": "Research question?",
  "description": "Detailed description...",
  "objective_type": "strategic|tactical|exploratory",
  "priority": 1-10,
  "attachment_ids": ["uuid", "uuid"]
}
```

**Query Parameters**:
- `status`: "proposed" | "approved" | "in_progress" | "completed" | "failed"
- `objective_type`: "strategic" | "tactical" | "exploratory"
- `limit`: 1-1000 (default 200)

### Knowledge Graph

```
GET  /api/kg/nodes                   List KG nodes with filters
GET  /api/kg/nodes/{node_id}         Get node details + edges
GET  /api/kg/nodes/{node_id}/neighbors  Get adjacent nodes
GET  /api/kg/path                    Find paths between nodes
GET  /api/kg/search                  Full-text search nodes
GET  /api/kg/export                  Export KG as JSON/CSV
```

**Query Parameters** (nodes):
- `confidence_min`: 0.0-1.0
- `discovered_after`: ISO timestamp
- `node_type`: "concept" | "finding" | "hypothesis" | ...

### Economy

```
GET  /api/economy/summary            Gini coefficient, balances, totals
GET  /api/economy/ledger             Paginated ledger entries
GET  /api/economy/net-worth          Net worth leaderboard
```

**Response** (net-worth):
```json
[
  {
    "persona_id": "uuid",
    "name": "Deep Researcher Alpha",
    "role_class": "researcher",
    "liquid_balance": 45.32,
    "position_value": 120.50,
    "node_value": 250.00,
    "reserved": 50.00,
    "net_worth": 365.82
  }
]
```

### Marketplace

```
GET  /api/marketplace/orders         Active buy/sell orders
GET  /api/marketplace/positions      Agent holdings
GET  /api/marketplace/crafted-goods  Available products
POST /api/marketplace/orders         Place bid/ask
POST /api/marketplace/craft          Create knowledge good
```

### Civilization

```
GET  /api/civilization/population    Agent population stats
GET  /api/civilization/nodes-portfolio  Per-agent KG node ownership
```

**Response** (nodes-portfolio):
```json
{
  "total_agents_with_nodes": 5,
  "total_nodes_owned": 12,
  "total_node_value": 2450.75,
  "agents": [
    {
      "persona_id": "uuid",
      "persona_name": "...",
      "owned_nodes": 3,
      "total_value": 450.25,
      "unrealized_pl": 123.45,
      "nodes": [
        {
          "node_id": "uuid",
          "label": "Sepsis biomarker X",
          "confidence": 0.87,
          "edge_count": 12,
          "traversal_count": 45,
          "value": 150.08,
          "purchase_price": 120.00
        }
      ]
    }
  ]
}
```

### Pipeline (Finding Workflow)

```
GET  /api/pipeline/status            Current workflow stages
GET  /api/pipeline/active            Active findings being processed
GET  /api/pipeline/completed         Recently completed findings
```

**Response**:
```json
{
  "active_findings": [
    {
      "finding_id": "uuid",
      "objective_title": "...",
      "agent_name": "Deep Researcher Alpha",
      "stage": "citation_checking|awaiting_review|under_review|revision_needed",
      "elapsed_seconds": 1234,
      "is_stalled": false
    }
  ],
  "completed_this_cycle": 3,
  "backlog_count": 1,
  "estimated_integration_minutes": 5
}
```

### Evolution

```
GET  /api/evolution/lineage          Persona family tree (parent→child mutations)
GET  /api/evolution/fitness          Fitness scores for all personas
GET  /api/evolution/mutations        Recent mutations + validation outcomes
```

### Activity

```
GET  /api/activity/events            Event stream (objective created, finding validated, etc.)
GET  /api/activity/agent/{persona_id}  Agent activity timeline
```

### Reports

```
GET  /api/reports/cost               Cumulative spend breakdown
GET  /api/reports/findings           Export validated findings
GET  /api/reports/kgi-summary        KG insights summary
```

### WebSocket

```
ws://localhost:8000/ws              Real-time event stream
```

**Message Types**:
- `objective.created`
- `finding.validated`
- `finding.challenged`
- `persona.mutated`
- `agent_instance.completed`
- `economy.transaction`

---

## Configuration

All configuration is controlled by environment variables loaded from `.env`:

### Budget Control

```bash
BUDGET_CEILING_USD=38.25              # Total spend cap
COST_INPUT_PER_MILLION=0.60           # $ per 1M input tokens
COST_OUTPUT_PER_MILLION=2.50          # $ per 1M output tokens
```

### Concurrency

```bash
MAX_CONCURRENT_CALLS=3                # Parallel Kimi API calls
STALE_INSTANCE_TIMEOUT_SECS=900       # 15 min instance timeout
```

### Economy

```bash
# Rent Decay (tiered)
RENT_DECAY_RATE_LOW=0.03              # Below 20 credits
RENT_DECAY_RATE_MID=0.05              # 20-100 credits
RENT_DECAY_RATE_HIGH=0.08             # Above 300 credits
RENT_DECAY_EXEMPT_BELOW=20.00         # 0% below this
RENT_DECAY_HIGH_ABOVE=300.00          # 8% above this
RENT_WELFARE_REDIRECT_RATIO=0.50      # % of high-tier rent → welfare
WELFARE_FLOOR_CREDITS=30.00           # Welfare distribution threshold
WELFARE_INTERVAL_TICKS=2              # Distribute every N ticks

# Salary
SALARY_BUDGET_RATE=0.12               # 12% of budget for salary pool
SALARY_MIN_CREDITS=1.00               # Min payment per review
SALARY_MAX_CREDITS=5.00               # Max payment per review

# Market Making
MARKET_OBI_SENSITIVITY=1.0            # Price discovery tuning
MARKET_IDLE_BALANCE_THRESHOLD=120.00  # Min balance for trading
MARKET_DEFAULT_COLLATERAL_RATIO=1.50  # Leverage control
MARKET_MAX_LISTINGS_PER_PERSONA=2     # Crafting limits
MARKET_MAX_OPEN_ORDERS_PER_PERSONA=6  # Order limits

# Node Ownership
NODE_BASE_PRICE=5.00                  # Minimum node price
NODE_MAX_OWNED_PER_AGENT=5            # Portfolio cap
NODE_YIELD_FROM_BOUNTY_PCT=0.05       # 5% of bounties → owners
NODE_DEPRECIATION_RATE=0.01           # Confidence decay/cycle
NODE_SUPERLINEAR_FACTOR=0.20          # +20% per additional node
```

### Evolution

```bash
MAX_ACTIVE_PERSONAS=20                # Population cap
MUTATION_MAX_EDIT_DISTANCE_PCT=0.30   # Max mutation magnitude
DIVERSITY_THRESHOLD=0.35              # Min persona dissimilarity
MIN_PERSONAS_PER_ROLE_CLASS=2         # Minimum per role
```

### Knowledge Graph

```bash
DEDUP_SIMILARITY_THRESHOLD=0.92       # Fuzzy duplicate detection
MAX_DAG_DEPTH=6                       # Max objective tree depth
MAX_DAG_FANOUT=8                      # Max children per objective
CONFIDENCE_DECAY_PER_HOP=0.7          # Confidence attenuation
```

### Citation Verification

```bash
CITATION_CHECK_TIMEOUT_SECS=5         # API timeout
CITATION_CACHE_TTL_DAYS=30            # Cache retention
CITATION_CONCURRENT_LIMIT=5           # Parallel verifications
```

### Files

```bash
UPLOADS_DIR=./uploads                 # File storage
MAX_FILE_SIZE_BYTES=20971520          # 20 MB limit
FILE_CONTEXT_BUDGET_CHARS=512000      # Max chars injected
FILE_CONTEXT_MAX_FILES=5              # Max files per objective
```

See `nexus-core/nexus_core/config.py` for all parameters with defaults.

---

## Development Workflow

### Adding a New Router

1. Create `nexus-api/nexus_api/routers/my_feature.py`:
   ```python
   from fastapi import APIRouter
   router = APIRouter(prefix="/api/my-feature", tags=["my-feature"])

   @router.get("/endpoint")
   async def my_endpoint():
       ...
   ```

2. Register in `nexus-api/nexus_api/main.py`:
   ```python
   from nexus_api.routers import my_feature
   app.include_router(my_feature.router)
   ```

### Adding a New Agent Role

1. Add persona template to `seed/personas.json`
2. Run `uv run nexus-cli seed load` to import
3. Originator will select personas based on specialization_vector similarity

### Adding Database Models

1. Create table in `nexus-core/nexus_core/models/`.py
2. Create Alembic migration: `alembic revision --autogenerate -m "Add my_table"`
3. Run: `alembic upgrade head`

### Running Tests

```bash
# All tests
uv run pytest

# Specific test file
uv run pytest tests/unit/test_config.py -v

# Integration tests (requires DB)
uv run pytest -m integration

# Slow tests (>10s)
uv run pytest -m slow
```

### Debugging

**View logs**:
```bash
# Follow engine logs
tail -f nexus_engine.log

# Follow API logs
tail -f nexus_api.log
```

**Database inspection**:
```bash
psql -U claudeai -d nexus

# View agent personas
SELECT persona_id, persona_name, role_class, status FROM agent_personas;

# View recent findings
SELECT finding_id, content, status FROM findings ORDER BY created_at DESC LIMIT 10;

# View economy ledger
SELECT * FROM economy_ledger ORDER BY created_at DESC LIMIT 20;
```

**WebSocket debugging**:
Open browser DevTools → Network tab, filter to "WS" messages to see real-time events.

---

## Testing

### Unit Tests

Located in `tests/unit/`. Run with:

```bash
uv run pytest tests/unit/ -v
```

Key test suites:
- `test_config.py` - Configuration loading
- `test_cost_guard.py` - Budget enforcement
- `test_evolution.py` - Persona mutation & fitness
- `test_api_schemas.py` - API contract validation
- `test_scouts.py` - External API integrations
- `test_api_routers.py` - Endpoint behavior

### Integration Tests

Located in `tests/integration/`. Requires PostgreSQL running:

```bash
uv run pytest -m integration -v
```

### Test Coverage

Generate coverage report:

```bash
uv run pytest --cov=nexus_core --cov-report=html
```

Open `htmlcov/index.html` to see detailed coverage.

---

## Project Status

**Version**: 0.1.0
**Status**: Production-Ready Architecture
**Last Updated**: March 24, 2026

### Implemented Features

- Multi-agent orchestration with persona-driven specialization
- Kimi K2.5 integration with token tracking & cost control
- Knowledge graph with provenance chains
- Multi-stage peer review (methodology, evidence, red-team)
- Citation verification cascade with caching
- Agent salary system with quality gates
- Progressive rent & welfare redistribution
- Order book imbalance price discovery
- Continuous finding quality scoring
- KG node ownership with autonomous trading
- Net worth system with wealth taxation
- Market making rewards (0.2% rebate)
- Pipeline workflow tracking dashboard
- Node portfolio dashboard
- Full API with WebSocket real-time updates
- CLI interface for all operations
- Comprehensive test suite (unit + integration)

### Known Limitations

- Red team infiltration sampling at 10% rate (can be tuned)
- Node takeover only for confidence < 0.1 (conservative)
- Single LLM provider (Kimi K2.5) — no fallback
- Dashboard is static-served (real-time via WebSocket only)

### Future Roadmap

- Multi-LLM support (fallback routing)
- Civilization-level governance voting on strategic direction
- Advanced visualization: evolutionary lineage as interactive tree
- Export findings as structured research briefs (PDF, Markdown)
- Multi-user access control & audit logging
- Batch objective submission from external systems
- Integration with external knowledge bases (OpenAlex, Semantic Scholar)

---

## Support & Contributing

### Getting Help

1. **Check the logs**: Always start with engine/API logs
2. **Inspect the DB**: Query the appropriate table directly
3. **Review configuration**: Ensure all settings are correct
4. **Check recent commits**: Review what changed recently

### Reporting Issues

Include:
- Error message + stack trace
- Relevant log entries (timestamp)
- Which component (engine, API, dashboard)
- Steps to reproduce
- System info (OS, Python version)

### Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Write tests for new functionality
4. Ensure all tests pass: `uv run pytest`
5. Submit pull request with clear description

---

## License

NEXUS is proprietary software developed by BioInfo AI.

---

## Contact

**Author**: Jonathan (Co-founder & Agentic Systems Architect, BioInfo AI)
**Repository**: https://github.com/bioinfoai/nexus
**Issues**: [GitHub Issues](https://github.com/bioinfoai/nexus/issues)
**Documentation**: [Wiki](https://github.com/bioinfoai/nexus/wiki)

---

**Built with attention to detail. Designed for continuous improvement. Evolved through adversarial validation.**
