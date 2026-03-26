# Requirements Document: NEXUS — Self-Evolving Agent Research Civilization

**Version:** 1.0  
**Date:** March 16, 2026  
**Stakeholder:** Jonathan — Co-founder & Agentic Systems Architect, BioInfo AI  
**Status:** Approved for Implementation

---

## Executive Summary

NEXUS is a self-evolving multi-agent orchestration system where agent personas are database-driven configurations, not hardcoded scripts. A persistent Originator agent reads persona configs from PostgreSQL, instantiates sub-agents via the Kimi K2.5 API, decomposes complex objectives into dependency-aware task DAGs, and orchestrates a civilization of specialized agents that maintain a shared knowledge graph, participate in a market economy, undergo continuous Darwinian evolution, and produce peer-reviewed research deliverables. The system is domain-agnostic by design — the initial acceptance test is a wicked socioeconomic problem ("How do we solve unemployment caused by AI"), not a domain-specific query.

### Business Value

NEXUS is the first system that treats a multi-agent society as a civilization — with economy, governance, evolution, adversarial immune systems, and institutional memory — while producing real-world research output. It serves as:

- **Technical showcase**: The most complex agentic orchestration built by a two-person team, demonstrating BioInfo AI's AI-native development capability
- **Research engine**: Once validated, the civilization pivots to autonomous sepsis/explainable AI research, generating pathway analyses, biomarker validation briefs, and drug target reports for the BioInfo AI commercial pipeline
- **Portfolio flagship**: Demo artifacts (observatory dashboard, evolutionary lineage tree, cost reporting) designed for pharma partner presentations (Aurobac Therapeutics, channel partner physician network)

### Scope Classification

- **Type:** Greenfield
- **Target:** Full Production System (all 7 architectural layers — not a trimmed MVP)
- **Timeline:** No deadline — quality over speed. Milestone-driven development recommended but not enforced.

---

## 1. Stakeholders & Users

### Primary Users

| Role | Technical Level | Primary Actions |
|------|-----------------|-----------------|
| Jonathan (Architect/Operator) | Expert | Submit objectives via CLI, monitor civilization via observatory dashboard, trigger manual interventions, review commercial-grade outputs, approve strategic objectives |
| Mike (Scientific Reviewer) | Expert (PhD Bioinformatics) | Review agent-produced research findings for scientific accuracy, validate KG discoveries, assess output quality for commercial readiness |

### Secondary Users / Systems

| Entity | Interaction Type | Notes |
|--------|------------------|-------|
| Kimi K2.5 API (Moonshot) | External LLM Provider | All agent cognition runs through this API. OpenAI-compatible endpoint at `api.moonshot.ai/v1` |
| PubMed API | External Data Source | Scout agents query for research abstracts |
| ClinicalTrials.gov API | External Data Source | Scout agents monitor active clinical trials |
| bioRxiv/medRxiv API | External Data Source | Scout agents monitor preprint servers |
| USPTO / Google Patents | External Data Source | Scout agents monitor patent filings |
| BioInfo AI Commercial Pipeline | Downstream Consumer | Validated findings feed pitch materials, partner reports |

### Approval Authority

Jonathan is the sole operator and final approval gate for:
- Strategic objective submission and prioritization
- Commercial-grade output release to external partners
- System-level configuration changes

The civilization has internal approval authority for:
- Tactical objectives (Governor agents approve)
- Exploratory objectives (agents self-approve within compute budget caps)
- Persona activation (Governor agents approve agent-proposed new personas)

---

## 2. Functional Requirements

### 2.1 Core User Journeys

#### Journey 1: Submit a Strategic Objective

```
Trigger: Jonathan submits an objective via CLI (e.g., `nexus submit "How do we solve unemployment caused by AI"`)
Steps:
1. Objective written to `objectives` table with status=proposed, objective_type=strategic, proposed_by=human
2. Originator agent picks up the new objective
3. Originator queries KG for existing relevant context (may be empty on first run)
4. Originator decomposes objective into sub-objectives, writes DAG to `objective_decomposition` table
5. For each leaf sub-objective: Originator queries `agent_personas` for best-fit persona (specialization_vector similarity)
6. If no suitable persona exists: Originator proposes a new persona config → Governor agent evaluates and approves/rejects
7. Agent instances spawned via Kimi K2.5 API calls (up to 3 concurrent)
8. Agents execute, write outputs to `findings` table
9. Peer review triggered (adaptive: 2 reviewers for routine, 3+ for high-impact)
10. Red Team agents attempt to challenge validated findings
11. Surviving findings committed to KG with full provenance
12. Economy credits distributed: bounties to completing agents, bonuses for peer review, penalties for failed outputs
13. Evolutionary evaluation: fitness recalculated for all involved personas
14. Dependent sub-objectives triggered via event-driven DB mechanism
15. Cycle repeats until root objective's acceptance criteria met
16. Final synthesis agent produces coherent markdown summary
17. Output surfaced to Jonathan via CLI notification and dashboard
Outcome: KG populated with new validated findings, economy updated, agent population potentially evolved
```

#### Journey 2: Monitor Civilization State

```
Trigger: Jonathan opens observatory dashboard in browser
Steps:
1. Dashboard connects to FastAPI backend via WebSocket
2. Hero view: Agent population table — all active personas with fitness scores, credit balances, generation number, current assignment
3. Secondary panels: Active objective DAGs with completion status, KG node/edge counts, economy circulation metrics
4. Evolutionary lineage tree visualization (parent→child persona mutations across generations)
5. Cost report panel: cumulative spend, per-agent spend, per-objective spend, remaining budget estimate
6. Live updates streamed via WebSocket as agent instances complete tasks
Outcome: Full visibility into civilization state without interrupting autonomous operation
```

#### Journey 3: Civilization Self-Proposes Research Direction

```
Trigger: Scout agent discovers relevant external publication via PubMed/patent scan
Steps:
1. Scout writes intelligence report to `findings` table with type=external_intelligence
2. Scout proposes new exploratory objective linked to the intelligence report
3. Objective auto-approved (exploratory tier — agent self-approval within budget cap)
4. Standard decomposition and execution cycle proceeds
5. If findings are high-impact, Governor agents may escalate to tactical objective requiring their approval
Outcome: Civilization autonomously expands its research agenda based on external signals
```

#### Journey 4: Agent Evolution Cycle

```
Trigger: Any objective completion (continuous evaluation)
Steps:
1. All agent instances involved in the completed objective have their performance recorded
2. Economy ledger updated: credits minted (inflationary), distributed as bounties, rent decay applied to all active personas
3. Fitness recalculated for involved personas (fitness = credit balance, market-based)
4. If any persona's credit balance drops below survival threshold: marked as candidate for deprecation
5. Top-performing personas identified: Originator generates mutated offspring (modified system prompt, adjusted tool permissions, altered reasoning strategy)
6. Mutated persona written to `agent_personas` with status=candidate, parent_persona_id set
7. Candidate persona assigned a validation objective to prove viability
8. If candidate outperforms parent or passes validation: status→active. If not: status→deprecated
9. Role class minimums enforced: evolutionary engine cannot prune below N active personas per role class (diversity pressure)
10. Novelty bonus applied: agents whose outputs are dissimilar to recent KG additions receive credit bonus (anti-convergence mechanism)
Outcome: Agent population continuously adapts — high performers reproduce, underperformers starve, diversity maintained
```

### 2.2 Feature Specifications

#### Feature: Originator Agent (The Stem Cell)

- **Description:** Persistent orchestration agent that monitors the objectives table, decomposes objectives into task DAGs, recruits/creates personas, instantiates agent instances, manages lifecycle, integrates results, and drives evolutionary cycles. Never performs domain research itself — pure meta-cognition.
- **Input:** New/updated rows in `objectives` table, completion events from `agent_instances`, KG state
- **Output:** Rows in `objective_decomposition`, `agent_instances`, `agent_personas` (new proposals), `economy_ledger` (credit minting)
- **Business Rules:**
  - Originator runs as a persistent asyncio daemon process
  - Queries `agent_personas` using specialization_vector cosine similarity for task-persona matching
  - Respects concurrency limit of 3 simultaneous Kimi K2.5 API calls (semaphore-controlled)
  - Can propose new persona configs when no existing persona fits (requires Governor approval to activate)
  - Tags each sub-objective with impact_level (routine/high-impact) based on novelty assessment and KG connectivity
  - Implements circuit breaker: if an objective's outputs fail peer review twice, escalate to human rather than retry
- **Acceptance Criteria:**
  - [ ] Originator picks up new strategic objective within 5 seconds of insertion
  - [ ] Decomposes into valid DAG with correct dependency edges
  - [ ] Selects appropriate personas based on specialization match
  - [ ] Respects 3-concurrent-instance semaphore
  - [ ] Creates new persona proposal when no existing match (governor approval flow works)
  - [ ] Correctly triggers dependent sub-objectives when predecessors complete

#### Feature: Agent Instance Execution

- **Description:** The mechanism by which a persona config is read from the database, a Kimi K2.5 API call is constructed with the persona's system prompt + objective context + relevant KG context, and the response is parsed, validated, and stored.
- **Input:** Row from `agent_personas` (system_prompt_template, tool_permissions, reasoning_strategy, model_tier), row from `objectives` (description, acceptance_criteria, knowledge_graph_anchor), relevant KG context
- **Output:** Row in `findings` table (markdown content), row in `agent_telemetry` (full observability data), updated `agent_instances` status
- **Business Rules:**
  - System prompt constructed by interpolating persona template with objective-specific context and relevant KG nodes/edges
  - Kimi K2.5 called in Thinking mode (temperature=1.0, top_p=0.95) for deep reasoning tasks
  - Full response captured: reasoning_content (thinking tokens) + content (output tokens) + usage metadata
  - Token counts broken down: input_tokens, thinking_tokens, output_tokens — each tracked separately for cost calculation
  - Timeout: 300 seconds per API call (Kimi K2.5 thinking mode can be slow on complex reasoning)
  - On failure (HTTP error, timeout, malformed response): retry once with same persona
  - On second failure: spawn debugger agent to diagnose (receives original prompt + error details + persona config)
  - Debugger agent output stored in `institutional_memory` to prevent future similar failures
- **Acceptance Criteria:**
  - [ ] Persona config correctly interpolated into Kimi K2.5 API call
  - [ ] Thinking mode enabled with correct temperature/top_p
  - [ ] Full telemetry captured (tokens, latency, cost)
  - [ ] Retry logic fires once on failure
  - [ ] Debugger agent spawns on second failure
  - [ ] Debugger diagnosis written to institutional_memory

#### Feature: Knowledge Graph (Collective Mind)

- **Description:** PostgreSQL-backed graph of nodes (entities: concepts, findings, hypotheses, contradictions) and edges (relationships: supports, contradicts, causes, correlates, etc.) with full provenance chains linking every node/edge to the objective and agent instance that created it.
- **Input:** Validated findings from peer review pipeline
- **Output:** Queryable graph accessible to all agents, visualization data for observatory dashboard
- **Business Rules:**
  - KG starts completely empty — no bootstrapping from existing GKG data
  - Every node has: confidence_score (0.0-1.0), validation_count (peer reviews passed), challenge_count (red team attacks survived)
  - Every edge has: weight, confidence_score, evidence_ids (array of finding IDs supporting it), status (proposed/validated/contested/refuted)
  - Full provenance: node.discovered_by_objective_id, node.discovered_by_instance_id, edge.discovered_by_objective_id
  - Epistemic confidence propagation: when an edge's confidence is reduced (via Red Team challenge), all downstream nodes/edges that depend on it have their confidence automatically recalculated (cascading Bayesian update)
  - JSONB properties field on both nodes and edges for flexible domain-specific metadata
  - Nodes are deduplicated: before creating a new node, agents must check for existing nodes with matching labels (fuzzy match)
- **Acceptance Criteria:**
  - [ ] Nodes and edges created with full provenance metadata
  - [ ] Confidence scores update correctly through peer review
  - [ ] Cascading confidence propagation fires when an edge is challenged
  - [ ] Duplicate node detection prevents KG fragmentation
  - [ ] KG queryable by agents via structured SQL (node/edge lookups, path traversals)

#### Feature: Market Economy

- **Description:** Internal credit system that serves as both the resource allocation mechanism and the fitness function for natural selection. Credits are the single source of truth for agent fitness.
- **Input:** Objective completion events, peer review outcomes, Red Team bounty claims, rent decay timer
- **Output:** Updated `economy_ledger` rows, updated persona credit balances (derived from ledger)
- **Business Rules:**
  - **Credit minting (inflationary):** When an objective completes, new credits are minted proportional to the objective's priority level. Distributed as bounties to the completing agent, peer reviewers, and Red Team agents who participated.
  - **Bounty structure:** Completing agent gets 60% of minted credits. Peer reviewers split 25%. Red Team agents who find legitimate flaws get 15% (if no flaws found, 15% goes to completing agent as bonus).
  - **Rent decay:** All active personas pay a fixed rent per evolutionary cycle (configurable, e.g., 5% of current balance). This creates "produce or die" pressure — idle agents lose credits continuously.
  - **Survival threshold:** Personas whose credit balance drops below a configurable floor are flagged for potential deprecation by the evolutionary engine.
  - **Role class minimums:** The economy cannot prune the last N personas (configurable, default=2) in any role class, even if they're below survival threshold. This maintains civilization diversity.
  - **Novelty bonus:** Agents whose findings introduce new KG nodes/edges that are dissimilar (cosine distance on JSONB properties) to nodes created in the last N objectives receive a credit multiplier. This prevents convergent evolution.
  - **Transaction types:** task_payment, bounty_claim, peer_review_fee, red_team_bounty, novelty_bonus, rent_payment, evolution_cost, governance_fee
  - **All transactions are append-only** in the ledger. Current balance is always a derived value (SUM of credits - SUM of debits for a persona_id).
- **Acceptance Criteria:**
  - [ ] Credits minted correctly on objective completion
  - [ ] Bounty distribution follows 60/25/15 split
  - [ ] Rent decay applies to all active personas per cycle
  - [ ] Personas below survival threshold flagged for deprecation
  - [ ] Role class minimums prevent over-pruning
  - [ ] Novelty bonus correctly calculated based on KG dissimilarity
  - [ ] Ledger is append-only, balances derived correctly

#### Feature: Peer Review Protocol

- **Description:** Quality assurance pipeline that validates agent findings before they are committed to the KG as validated knowledge.
- **Input:** Completed finding from an agent instance
- **Output:** Review verdicts, updated finding status (proposed→validated or proposed→rejected), KG updates
- **Business Rules:**
  - **Impact classification:** Originator tags each sub-objective as routine or high-impact at decomposition time based on novelty assessment
  - **Reviewer count:** Routine findings → 2 independent reviewers. High-impact findings → 3+ reviewers.
  - **Reviewer selection:** Reviewers selected from active personas in the same or related role classes. Producing agent is excluded. Reviewers should be from different persona lineages when possible (genetic diversity in review).
  - **Review structure:** Each reviewer produces a structured assessment: methodology_critique (text), evidence_evaluation (text), novelty_assessment (text), confidence_rating (0.0-1.0), verdict (approve/reject/revise)
  - **Consensus rules:** Routine: majority approval → validated. High-impact: unanimous approval required → validated. Any rejection → finding returned to producing agent with reviewer feedback for revision.
  - **Revision limit:** A finding can be revised and resubmitted once. If it fails peer review a second time, the objective is escalated to human (circuit breaker).
  - **Reviewer compensation:** Reviewers earn credits from the bounty pool regardless of their verdict (incentivizes honest review, not rubber-stamping).
- **Acceptance Criteria:**
  - [ ] Correct number of reviewers assigned based on impact level
  - [ ] Reviewers produce structured assessments
  - [ ] Consensus rules correctly applied (majority for routine, unanimous for high-impact)
  - [ ] Failed findings returned with feedback
  - [ ] Circuit breaker fires after two failed reviews
  - [ ] Reviewer credits distributed correctly

#### Feature: Red Team / Adversarial Immune System

- **Description:** Dedicated adversarial agents that actively attempt to find flaws in validated KG findings. Operates as a separate layer from peer review — Red Team attacks findings AFTER they've been validated, testing the civilization's epistemic resilience.
- **Input:** Newly validated KG nodes/edges
- **Output:** Challenge reports, updated KG confidence scores, bounty claims
- **Business Rules:**
  - Red Team agents are a distinct role_class with specialized system prompts designed for critical analysis, logical flaw detection, and counter-evidence search
  - After a finding is validated by peer review and committed to the KG, it enters a "challenge window" (configurable, e.g., the next 3 objective cycles)
  - During the challenge window, Red Team agents can file challenge reports against the finding
  - Challenge reports are structured: flaw_type (methodological, logical, evidential, contradictory), description, counter_evidence, severity (minor/major/critical)
  - Major/critical challenges trigger confidence reduction on the target KG node/edge + cascading confidence propagation
  - Red Team agents earn bounties for legitimate challenges (those accepted by Governor review)
  - Red Team agents receive penalties for frivolous challenges (those rejected by Governor review) — prevents noise
  - **Infiltrator sub-class:** Periodically, a specialized Infiltrator agent injects plausible-but-wrong information into the findings pipeline (before peer review). This tests the peer review system's ability to catch errors. Infiltrator injections are tagged in the DB but invisible to reviewing agents. If the infiltration survives peer review and enters the KG, it's flagged as a system failure for diagnostic purposes.
- **Acceptance Criteria:**
  - [ ] Red Team agents activate on newly validated findings
  - [ ] Challenge reports correctly structured with flaw classification
  - [ ] KG confidence scores update on accepted challenges
  - [ ] Cascading confidence propagation fires correctly
  - [ ] Bounties paid for legitimate challenges, penalties for frivolous ones
  - [ ] Infiltrator injections tagged internally but invisible to reviewers
  - [ ] Infiltrations that survive to KG are logged as system failures

#### Feature: Governance Layer

- **Description:** Constitutional system where Governor agents maintain and evolve the civilization's operating rules through a proposal-and-vote mechanism.
- **Input:** Proposals from any agent, persona activation requests, escalated decisions
- **Output:** Approved/rejected proposals, updated governance rules, activated/deprecated personas
- **Business Rules:**
  - Governor is a distinct role_class with elevated permissions
  - **Proposal types:** rule_change, resource_reallocation, persona_activation, persona_deprecation, priority_shift, new_role_class
  - Any agent can submit a governance proposal
  - Governor agents evaluate proposals based on: alignment with civilization objectives, resource implications, risk assessment
  - **Persona activation flow:** When any agent proposes a new persona type, it's written to `agent_personas` with status=candidate. A Governor agent reviews the proposed config (system prompt, tools, reasoning strategy) and either approves (status→active) or rejects (status→deprecated) with rationale.
  - **Voting:** For rule_change and resource_reallocation proposals, multiple Governor agents vote. Votes are reputation-weighted (higher-fitness Governors have more influence). Simple majority required.
  - Governance decisions are logged in `governance_proposals` and `governance_votes` tables with full rationale for institutional memory.
- **Acceptance Criteria:**
  - [ ] Proposals can be submitted by any agent
  - [ ] Governor agents correctly evaluate persona activation requests
  - [ ] Voting mechanism works with reputation-weighted votes
  - [ ] All governance decisions logged with rationale
  - [ ] Approved rule changes take effect in the next objective cycle

#### Feature: Dream Cycle (Offline Knowledge Consolidation)

- **Description:** A specialized Consolidator agent that runs during low-activity periods, reviewing recent KG additions to identify cross-cutting patterns and propose serendipitous research connections that individual agents missed.
- **Input:** KG nodes/edges added in the last N objective cycles, recent findings
- **Output:** Exploratory objective proposals, pattern reports, KG meta-edges (edges connecting previously unconnected clusters)
- **Business Rules:**
  - Dream Cycle triggered manually via CLI or automatically when the objective queue is empty
  - Consolidator agent receives a high-level summary of recent KG growth (new nodes, new edges, confidence changes)
  - Consolidator looks for: unconnected KG clusters that share semantic similarity, contradictions between validated findings, high-confidence edges that lack supporting diversity (only one evidence source), and emergent patterns across multiple findings
  - Outputs are exploratory objective proposals (self-approved tier) with rationale linking to specific KG nodes
  - Dream Cycle is budget-aware: only runs if remaining API budget exceeds a configurable floor
- **Acceptance Criteria:**
  - [ ] Dream Cycle correctly summarizes recent KG activity
  - [ ] Identifies at least one cross-cutting pattern or connection per run
  - [ ] Proposes valid exploratory objectives with KG provenance links
  - [ ] Respects budget floor constraint

#### Feature: Scout Agents (Foreign Intelligence Service)

- **Description:** Specialized agents that monitor external data sources for information relevant to the civilization's current research agenda, filing intelligence reports and proposing new research directions.
- **Input:** Current KG state (active research topics), external API responses from PubMed, ClinicalTrials.gov, bioRxiv/medRxiv, USPTO, Google Patents
- **Output:** Intelligence reports in `findings` table (type=external_intelligence), exploratory objective proposals
- **Business Rules:**
  - Scout agents are a distinct role_class
  - Each external data source has a dedicated API client module:
    - **PubMed:** NCBI E-utilities API (free, rate-limited at 3 req/sec with API key, 10/sec with NCBI account). Search recent publications matching KG topic keywords.
    - **ClinicalTrials.gov:** REST API. Monitor active/recruiting trials matching KG research themes.
    - **bioRxiv/medRxiv:** RSS feeds or API. Monitor preprints in relevant categories.
    - **USPTO:** PatentsView API (free). Search patent applications matching KG concepts.
    - **Google Patents:** Web scraping or BigQuery public dataset. Search granted patents and applications.
  - Scout runs are triggered periodically (configurable interval, e.g., every 5 objective cycles) or manually via CLI
  - Scout queries are derived from high-confidence KG nodes: extract top-N concept labels, construct search queries
  - Results are filtered for relevance by the Scout agent (LLM call to assess relevance to current research)
  - Relevant results filed as intelligence reports with source attribution
  - Scout proposes exploratory objectives when it finds high-relevance external information
- **Acceptance Criteria:**
  - [ ] API clients for all 5 external sources functional
  - [ ] Scout constructs relevant queries from KG state
  - [ ] Intelligence reports filed with correct source attribution
  - [ ] Exploratory objectives proposed for high-relevance findings
  - [ ] Rate limits respected on all external APIs

#### Feature: Observatory Dashboard

- **Description:** React web application providing real-time visualization of civilization state, served by FastAPI backend with WebSocket for live updates.
- **Input:** All database tables (read-only consumer)
- **Output:** Interactive web UI with multiple visualization panels
- **Business Rules:**
  - **Hero view (default):** Agent population table — all active personas with: persona_name, role_class, generation, fitness_score (credit balance), current_assignment (active objective or idle), status, parent lineage
  - **Evolutionary lineage panel:** Tree/graph visualization showing persona mutation history. Parent→child relationships, generation numbers, fitness trajectory over time. Deprecated personas shown as greyed-out nodes.
  - **Objective DAG panel:** Active and completed objective decomposition trees. Node colors indicate status (pending/active/completed/failed). Click to expand sub-objective details.
  - **Knowledge Graph panel:** Force-directed graph visualization of KG nodes and edges. Node size = confidence score. Edge thickness = weight. Color coding by node_type. Click to see provenance chain.
  - **Economy panel:** Credit circulation metrics — total credits in system, credits minted vs. decayed, top/bottom agents by balance, Gini coefficient (inequality metric to detect degenerate equilibria)
  - **Cost report panel:** Cumulative Moonshot API spend, per-agent spend breakdown, per-objective spend breakdown, tokens consumed (input/thinking/output separately), remaining budget estimate, cost-per-finding metric
  - **Live updates:** FastAPI WebSocket pushes events (agent started, agent completed, finding validated, challenge filed, evolution event, economy transaction) to dashboard in real-time
- **Acceptance Criteria:**
  - [ ] All 6 panels render with correct data
  - [ ] WebSocket connection provides real-time updates
  - [ ] Evolutionary lineage tree correctly shows parent→child relationships
  - [ ] Cost report accurately reflects Moonshot API spending
  - [ ] KG visualization is interactive (click for provenance details)
  - [ ] Economy Gini coefficient calculated and displayed

#### Feature: CLI Interface

- **Description:** Typer-based command-line interface for power operations — objective submission, system control, manual interventions.
- **Input:** User commands
- **Output:** Terminal output (formatted tables, status messages), database mutations
- **Commands:**
  - `nexus submit <description> [--priority N] [--type strategic|tactical|exploratory]` — Submit a new objective
  - `nexus status` — Show active objectives, running instances, population summary
  - `nexus objectives [--status active|completed|failed]` — List objectives with status filters
  - `nexus agents` — Show all active personas with fitness scores and current assignments
  - `nexus agent <persona_id>` — Show detailed persona info including lineage, history, credit balance
  - `nexus kg stats` — KG summary: node count, edge count, avg confidence, cluster count
  - `nexus kg search <query>` — Search KG nodes by label or property
  - `nexus economy` — Economy summary: total credits, circulation rate, Gini coefficient, top/bottom performers
  - `nexus evolve` — Manually trigger an evolution cycle
  - `nexus dream` — Manually trigger a Dream Cycle consolidation
  - `nexus scout` — Manually trigger a Scout intelligence sweep
  - `nexus cost` — Detailed cost report: spend by agent, by objective, remaining budget
  - `nexus pause` — Pause the Originator daemon (no new instances spawned, running instances complete)
  - `nexus resume` — Resume the Originator daemon
  - `nexus config <key> <value>` — Update runtime configuration (concurrency limit, rent rate, survival threshold, etc.)
- **Acceptance Criteria:**
  - [ ] All commands execute correctly and return formatted output
  - [ ] `nexus submit` creates valid objective rows
  - [ ] `nexus status` reflects real-time system state
  - [ ] `nexus pause/resume` correctly controls the Originator daemon
  - [ ] `nexus config` updates take effect without restart

### 2.3 Edge Cases & Error Handling

| Scenario | Expected Behavior | User Feedback |
|----------|-------------------|---------------|
| Kimi K2.5 API returns HTTP 429 (rate limited) | Exponential backoff with jitter, retry up to 3 times, then mark instance as failed | Logged in telemetry, visible in dashboard |
| Kimi K2.5 API returns incoherent/unparseable response | Mark as failure, trigger retry-once → debugger agent pipeline | Debugger diagnosis logged in institutional_memory |
| Agent output fails peer review twice | Circuit breaker: objective escalated to human via CLI notification | `nexus status` shows escalated objective requiring attention |
| All personas in a role class drop below survival threshold | Role class minimum enforced: lowest-fitness persona preserved, flagged for mutation rather than deprecation | Warning in dashboard economy panel |
| Economy enters hyperinflation (total credits growing faster than value produced) | Governance agents can propose rent rate increase or mint rate decrease | Economy Gini coefficient visible in dashboard; manual `nexus config` override available |
| KG deduplication fails (duplicate nodes created) | Merge operation available via Governor proposal or manual CLI command | KG panel shows node count anomalies |
| Moonshot API budget approaches zero | Cost governor logs warning at configurable threshold (e.g., $5 remaining). At $1 remaining, Originator pauses automatically. | CLI warning, dashboard cost panel shows red alert |
| PostgreSQL connection lost | All three processes (engine, API, CLI) retry connection with exponential backoff. Running agent instances fail gracefully — state is always DB-persisted so recovery is clean. | Error logged, dashboard shows connection status |
| Objective decomposition creates circular dependency in DAG | Originator validates DAG is acyclic before committing. Circular references rejected with error. | Error logged with details of cycle |
| Infiltrator injection survives peer review into KG | Tagged as system_failure in internal log. Triggering finding and all reviewer assessments flagged for diagnostic analysis. KG node marked for removal. | Dashboard shows system health alert |

---

## 3. Data Architecture

### 3.1 Data Entities

#### Entity: agent_personas

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| persona_id | UUID | PK, auto-generated | Unique persona identifier |
| persona_name | VARCHAR(255) | NOT NULL | Human-readable name (e.g., "Pathway Analyst Alpha") |
| role_class | VARCHAR(50) | NOT NULL, ENUM | One of: originator, researcher, critic, synthesizer, tool_forger, governor, red_team, scout, librarian, consolidator, debugger, infiltrator, peer_reviewer |
| system_prompt_template | TEXT | NOT NULL | Parameterized system prompt — supports {objective}, {kg_context}, {institutional_memory} interpolation variables |
| tool_permissions | JSONB | DEFAULT '[]' | Array of tool IDs this persona can invoke |
| reasoning_strategy | VARCHAR(50) | DEFAULT 'chain-of-thought' | One of: chain-of-thought, tree-of-thought, debate-with-self, hypothesis-driven, adversarial, analytical |
| model_config | JSONB | DEFAULT '{}' | Model-specific config: temperature, top_p, max_tokens, thinking mode on/off |
| autonomy_level | INTEGER | DEFAULT 3, CHECK 1-5 | 1=minimal (human approval for everything), 5=full autonomy within budget |
| parent_persona_id | UUID | FK agent_personas, NULLABLE | Evolutionary parent (NULL for seed personas) |
| generation | INTEGER | DEFAULT 0 | Evolutionary generation number |
| credit_balance | NUMERIC(12,2) | DEFAULT 100.00 | Current credit balance (derived from ledger, cached here for query performance) |
| reputation_score | NUMERIC(5,3) | DEFAULT 0.500 | Peer-assessed quality rating (0.000-1.000) |
| compute_budget | NUMERIC(10,2) | DEFAULT 50.00 | Max credits this persona can spend per objective |
| status | VARCHAR(20) | DEFAULT 'active' | One of: active, dormant, deprecated, candidate |
| specialization_vector | VECTOR(384) | NULLABLE | Embedding of the persona's domain expertise for task routing (sentence-transformers) |
| mutation_diff | JSONB | NULLABLE | What changed from parent persona (for evolutionary tracking) |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| deprecated_at | TIMESTAMPTZ | NULLABLE | When deprecated |
| deprecation_reason | TEXT | NULLABLE | Why deprecated |

#### Entity: agent_instances

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| instance_id | UUID | PK, auto-generated | Unique instance identifier |
| persona_id | UUID | FK agent_personas, NOT NULL | Which persona blueprint this instance runs |
| objective_id | UUID | FK objectives, NOT NULL | Which objective this instance is working on |
| session_state | JSONB | DEFAULT '{}' | Serialized conversation/reasoning state (for multi-turn if needed) |
| spawned_by | UUID | FK agent_instances, NULLABLE | The originator or parent instance that created this one |
| spawn_reason | TEXT | NULLABLE | Why this instance was created |
| input_prompt | TEXT | NOT NULL | The full prompt sent to Kimi K2.5 API |
| output_content | TEXT | NULLABLE | Raw response content from Kimi K2.5 |
| thinking_content | TEXT | NULLABLE | Reasoning trace from Kimi K2.5 thinking mode |
| started_at | TIMESTAMPTZ | DEFAULT NOW() | Instance start time |
| completed_at | TIMESTAMPTZ | NULLABLE | Instance completion time |
| last_heartbeat | TIMESTAMPTZ | DEFAULT NOW() | Last activity timestamp |
| status | VARCHAR(20) | DEFAULT 'pending' | One of: pending, running, completed, failed, killed, retrying |
| retry_count | INTEGER | DEFAULT 0 | Number of retries attempted |
| tokens_input | INTEGER | DEFAULT 0 | Input tokens consumed |
| tokens_thinking | INTEGER | DEFAULT 0 | Thinking/reasoning tokens consumed |
| tokens_output | INTEGER | DEFAULT 0 | Output tokens consumed |
| cost_usd | NUMERIC(8,6) | DEFAULT 0 | Computed cost in USD |
| latency_ms | INTEGER | NULLABLE | End-to-end latency in milliseconds |
| error_message | TEXT | NULLABLE | Error details if failed |

#### Entity: objectives

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| objective_id | UUID | PK, auto-generated | Unique objective identifier |
| parent_objective_id | UUID | FK objectives, NULLABLE | For hierarchical decomposition |
| title | VARCHAR(500) | NOT NULL | Short objective title |
| description | TEXT | NOT NULL | Full objective description |
| objective_type | VARCHAR(20) | NOT NULL | One of: strategic, tactical, exploratory |
| impact_level | VARCHAR(20) | DEFAULT 'routine' | One of: routine, high-impact (determines peer review intensity) |
| priority | INTEGER | DEFAULT 5, CHECK 1-10 | 1=lowest, 10=highest |
| status | VARCHAR(20) | DEFAULT 'proposed' | One of: proposed, approved, active, blocked, completed, failed, abandoned, escalated |
| proposed_by_type | VARCHAR(10) | NOT NULL | 'human' or 'agent' |
| proposed_by_id | UUID | NULLABLE | persona_id if proposed by agent |
| approved_by_type | VARCHAR(10) | NULLABLE | 'human', 'governor', or 'self' (for exploratory auto-approval) |
| approved_by_id | UUID | NULLABLE | persona_id of approving governor, or NULL for human/self |
| assigned_to | UUID | FK agent_personas, NULLABLE | Persona assigned to execute |
| acceptance_criteria | TEXT | NULLABLE | Machine-evaluable success conditions |
| knowledge_graph_anchor | JSONB | DEFAULT '[]' | Array of KG node_ids this objective relates to (provenance link) |
| compute_budget_allocated | NUMERIC(10,2) | DEFAULT 0 | Credits allocated for this objective's execution |
| output_type | VARCHAR(50) | NULLABLE | Expected: analysis, report, tool, hypothesis, validation, dataset, synthesis, intelligence |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| completed_at | TIMESTAMPTZ | NULLABLE | Completion timestamp |
| escalated_at | TIMESTAMPTZ | NULLABLE | When escalated to human (circuit breaker) |
| escalation_reason | TEXT | NULLABLE | Why escalated |

#### Entity: objective_decomposition

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| decomposition_id | UUID | PK, auto-generated | Unique decomposition identifier |
| parent_objective_id | UUID | FK objectives, NOT NULL | The objective being decomposed |
| child_objective_id | UUID | FK objectives, NOT NULL | The resulting sub-objective |
| decomposition_rationale | TEXT | NOT NULL | Originator's reasoning for this sub-task |
| dependency_type | VARCHAR(20) | NOT NULL | One of: sequential, parallel, conditional |
| depends_on | JSONB | DEFAULT '[]' | Array of child_objective_ids that must complete first |
| execution_order | INTEGER | DEFAULT 0 | Ordering hint for sequential dependencies |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

#### Entity: knowledge_graph_nodes

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| node_id | UUID | PK, auto-generated | Unique node identifier |
| node_type | VARCHAR(50) | NOT NULL | One of: concept, finding, hypothesis, contradiction, entity, mechanism, policy, argument, evidence |
| label | VARCHAR(500) | NOT NULL | Human-readable node label |
| properties | JSONB | DEFAULT '{}' | Flexible domain-specific metadata |
| confidence_score | NUMERIC(4,3) | DEFAULT 0.500 | 0.000-1.000, updated by peer review and Red Team challenges |
| discovered_by_objective_id | UUID | FK objectives | Provenance: which objective produced this |
| discovered_by_instance_id | UUID | FK agent_instances | Provenance: which agent instance produced this |
| validation_count | INTEGER | DEFAULT 0 | How many independent peer reviews support this |
| challenge_count | INTEGER | DEFAULT 0 | How many Red Team attacks it has survived |
| challenge_failures | INTEGER | DEFAULT 0 | How many Red Team attacks succeeded against this |
| status | VARCHAR(20) | DEFAULT 'proposed' | One of: proposed, validated, contested, refuted, retracted |
| first_seen | TIMESTAMPTZ | DEFAULT NOW() | When first added |
| last_validated | TIMESTAMPTZ | NULLABLE | Most recent successful validation |

#### Entity: knowledge_graph_edges

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| edge_id | UUID | PK, auto-generated | Unique edge identifier |
| source_node_id | UUID | FK kg_nodes, NOT NULL | Source node |
| target_node_id | UUID | FK kg_nodes, NOT NULL | Target node |
| relationship_type | VARCHAR(100) | NOT NULL | E.g.: supports, contradicts, causes, correlates, enables, prevents, part_of, derives_from |
| weight | NUMERIC(5,3) | DEFAULT 0.500 | Edge strength (0.000-1.000) |
| confidence_score | NUMERIC(4,3) | DEFAULT 0.500 | Independent confidence for this edge |
| evidence_ids | JSONB | DEFAULT '[]' | Array of finding IDs supporting this edge |
| discovered_by_objective_id | UUID | FK objectives | Provenance |
| challenged_by_objective_ids | JSONB | DEFAULT '[]' | Objectives that challenged this edge |
| status | VARCHAR(20) | DEFAULT 'proposed' | One of: proposed, validated, contested, refuted |
| properties | JSONB | DEFAULT '{}' | Flexible metadata |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

#### Entity: findings

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| finding_id | UUID | PK, auto-generated | Unique finding identifier |
| objective_id | UUID | FK objectives, NOT NULL | Which objective produced this |
| instance_id | UUID | FK agent_instances, NOT NULL | Which agent instance produced this |
| finding_type | VARCHAR(50) | NOT NULL | One of: research, analysis, synthesis, intelligence, review, challenge, diagnosis, consolidation, infiltration_test |
| title | VARCHAR(500) | NOT NULL | Finding title |
| content | TEXT | NOT NULL | Full markdown content |
| structured_data | JSONB | NULLABLE | Optional structured extraction (entities, relationships, metrics) |
| status | VARCHAR(20) | DEFAULT 'pending_review' | One of: pending_review, in_review, validated, rejected, revised, escalated |
| review_round | INTEGER | DEFAULT 0 | Current review iteration (max 2 before circuit breaker) |
| impact_level | VARCHAR(20) | DEFAULT 'routine' | Inherited from objective |
| kg_nodes_created | JSONB | DEFAULT '[]' | Array of node_ids created from this finding |
| kg_edges_created | JSONB | DEFAULT '[]' | Array of edge_ids created from this finding |
| is_infiltration | BOOLEAN | DEFAULT FALSE | Internal flag: TRUE if this is an Infiltrator test (invisible to reviewers) |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

#### Entity: peer_reviews

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| review_id | UUID | PK, auto-generated | Unique review identifier |
| finding_id | UUID | FK findings, NOT NULL | Finding being reviewed |
| reviewer_persona_id | UUID | FK agent_personas, NOT NULL | Who reviewed |
| reviewer_instance_id | UUID | FK agent_instances, NOT NULL | Specific instance that performed review |
| methodology_critique | TEXT | NOT NULL | Assessment of methodology |
| evidence_evaluation | TEXT | NOT NULL | Assessment of evidence quality |
| novelty_assessment | TEXT | NOT NULL | Assessment of novelty/contribution |
| confidence_rating | NUMERIC(4,3) | NOT NULL | Reviewer's confidence in the finding (0.000-1.000) |
| verdict | VARCHAR(20) | NOT NULL | One of: approve, reject, revise |
| revision_feedback | TEXT | NULLABLE | Specific feedback for revision (if verdict=revise or reject) |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Review timestamp |

#### Entity: economy_ledger

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| transaction_id | UUID | PK, auto-generated | Unique transaction identifier |
| from_persona_id | UUID | FK agent_personas, NULLABLE | Source (NULL for system minting) |
| to_persona_id | UUID | FK agent_personas, NULLABLE | Destination (NULL for rent decay sink) |
| amount | NUMERIC(12,2) | NOT NULL | Credit amount (positive) |
| transaction_type | VARCHAR(50) | NOT NULL | One of: mint, task_payment, bounty_claim, peer_review_fee, red_team_bounty, novelty_bonus, rent_payment, evolution_cost, governance_fee |
| reference_objective_id | UUID | FK objectives, NULLABLE | Associated objective |
| reference_finding_id | UUID | FK findings, NULLABLE | Associated finding |
| memo | TEXT | NULLABLE | Human-readable transaction description |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Transaction timestamp |

#### Entity: governance_proposals

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| proposal_id | UUID | PK, auto-generated | Unique proposal identifier |
| proposed_by_persona_id | UUID | FK agent_personas, NOT NULL | Who proposed |
| proposal_type | VARCHAR(50) | NOT NULL | One of: rule_change, resource_reallocation, persona_activation, persona_deprecation, priority_shift, new_role_class |
| title | VARCHAR(500) | NOT NULL | Proposal title |
| description | TEXT | NOT NULL | Full proposal description |
| rationale | TEXT | NOT NULL | Why this change is needed |
| target_persona_id | UUID | FK agent_personas, NULLABLE | For persona_activation/deprecation proposals |
| status | VARCHAR(20) | DEFAULT 'proposed' | One of: proposed, voting, approved, rejected, implemented |
| voting_deadline | TIMESTAMPTZ | NULLABLE | When voting closes |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Proposal timestamp |
| resolved_at | TIMESTAMPTZ | NULLABLE | When resolved |

#### Entity: governance_votes

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| vote_id | UUID | PK, auto-generated | Unique vote identifier |
| proposal_id | UUID | FK governance_proposals, NOT NULL | Which proposal |
| voter_persona_id | UUID | FK agent_personas, NOT NULL | Who voted |
| vote | VARCHAR(10) | NOT NULL | One of: approve, reject, abstain |
| reasoning | TEXT | NOT NULL | Why this vote |
| voter_reputation_weight | NUMERIC(5,3) | NOT NULL | Voter's reputation at time of vote (snapshot) |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Vote timestamp |

#### Entity: messages (Inter-Agent Communication Queue)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| message_id | UUID | PK, auto-generated | Unique message identifier |
| from_instance_id | UUID | FK agent_instances, NULLABLE | Sending instance (NULL for system messages) |
| to_instance_id | UUID | FK agent_instances, NULLABLE | Target instance (NULL for broadcast) |
| to_role_class | VARCHAR(50) | NULLABLE | Broadcast target role class |
| message_type | VARCHAR(50) | NOT NULL | One of: request, response, critique, proposal, alert, finding_ready, review_request, challenge, diagnosis |
| payload | JSONB | NOT NULL | Message content |
| priority | INTEGER | DEFAULT 5 | 1-10 |
| status | VARCHAR(20) | DEFAULT 'pending' | One of: pending, delivered, processed, expired |
| expires_at | TIMESTAMPTZ | NULLABLE | Message expiration |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

#### Entity: institutional_memory

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| memory_id | UUID | PK, auto-generated | Unique memory identifier |
| memory_type | VARCHAR(50) | NOT NULL | One of: lesson_learned, failed_approach, successful_pattern, diagnostic, policy |
| title | VARCHAR(500) | NOT NULL | Short description |
| content | TEXT | NOT NULL | Full memory content |
| source_objective_id | UUID | FK objectives, NULLABLE | Where this lesson came from |
| source_instance_id | UUID | FK agent_instances, NULLABLE | Which agent learned this |
| relevance_tags | JSONB | DEFAULT '[]' | Array of topic tags for retrieval |
| retrieval_count | INTEGER | DEFAULT 0 | How often this memory has been injected into agent context |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

#### Entity: tool_registry

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| tool_id | UUID | PK, auto-generated | Unique tool identifier |
| tool_name | VARCHAR(255) | NOT NULL, UNIQUE | Tool name |
| tool_type | VARCHAR(20) | NOT NULL | One of: builtin, forged, external |
| description | TEXT | NOT NULL | What the tool does |
| input_schema | JSONB | NOT NULL | JSON Schema for tool input |
| output_schema | JSONB | NOT NULL | JSON Schema for tool output |
| implementation | TEXT | NULLABLE | For forged tools: Python function source code |
| created_by_persona_id | UUID | FK agent_personas, NULLABLE | NULL for builtins |
| created_by_objective_id | UUID | FK objectives, NULLABLE | Provenance |
| usage_count | INTEGER | DEFAULT 0 | Times used |
| success_rate | NUMERIC(4,3) | DEFAULT 1.000 | Success rate (0.000-1.000) |
| status | VARCHAR(20) | DEFAULT 'active' | One of: active, testing, deprecated |
| required_permissions | JSONB | DEFAULT '[]' | Permission tags needed to use this tool |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

#### Entity: agent_telemetry

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| telemetry_id | UUID | PK, auto-generated | Unique telemetry identifier |
| instance_id | UUID | FK agent_instances, NOT NULL | Which instance |
| persona_id | UUID | FK agent_personas, NOT NULL | Which persona (denormalized for query performance) |
| objective_id | UUID | FK objectives, NOT NULL | Which objective (denormalized) |
| api_call_timestamp | TIMESTAMPTZ | DEFAULT NOW() | When the API call was made |
| prompt_hash | VARCHAR(64) | NOT NULL | SHA-256 of the input prompt (for deduplication analysis) |
| tokens_input | INTEGER | NOT NULL | Input tokens |
| tokens_thinking | INTEGER | NOT NULL | Thinking tokens (Kimi K2.5 specific) |
| tokens_output | INTEGER | NOT NULL | Output tokens |
| cost_input_usd | NUMERIC(8,6) | NOT NULL | Input cost at $0.60/M tokens |
| cost_output_usd | NUMERIC(8,6) | NOT NULL | Output cost at $2.50/M tokens |
| cost_total_usd | NUMERIC(8,6) | NOT NULL | Total cost for this call |
| latency_ms | INTEGER | NOT NULL | End-to-end latency |
| http_status | INTEGER | NOT NULL | HTTP response status code |
| success | BOOLEAN | NOT NULL | Whether the call produced usable output |
| error_category | VARCHAR(50) | NULLABLE | If failed: timeout, rate_limit, parse_error, incoherent, api_error |
| model_id | VARCHAR(100) | NOT NULL | Model identifier used (e.g., 'kimi-k2.5') |

#### Relationships

```
agent_personas --[parent_of]--> agent_personas (evolutionary lineage)
agent_personas --[instantiated_as]--> agent_instances
agent_instances --[works_on]--> objectives
objectives --[decomposes_into]--> objectives (via objective_decomposition)
objectives --[anchored_to]--> knowledge_graph_nodes
agent_instances --[produces]--> findings
findings --[reviewed_by]--> peer_reviews
findings --[creates]--> knowledge_graph_nodes
findings --[creates]--> knowledge_graph_edges
knowledge_graph_nodes --[connected_by]--> knowledge_graph_edges
economy_ledger --[debits/credits]--> agent_personas
governance_proposals --[voted_on_by]--> governance_votes
agent_instances --[tracked_by]--> agent_telemetry
agent_instances --[communicates_via]--> messages
```

### 3.2 Data Flow Diagram

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Human CLI   │────▶│    objectives     │────▶│   Originator     │
│  (Jonathan)  │     │     table         │     │    Engine        │
└──────────────┘     └──────────────────┘     └──────────────────┘
                                                      │
                           ┌──────────────────────────┤
                           ▼                          ▼
                  ┌─────────────────┐     ┌──────────────────────┐
                  │ objective_       │     │   agent_personas      │
                  │ decomposition    │     │   (select best-fit)   │
                  └─────────────────┘     └──────────────────────┘
                                                      │
                                                      ▼
                                          ┌──────────────────────┐
                                          │  Kimi K2.5 API       │
                                          │  (Moonshot)          │
                                          └──────────────────────┘
                                                      │
                                    ┌─────────────────┤──────────────────┐
                                    ▼                 ▼                  ▼
                          ┌────────────────┐ ┌──────────────┐ ┌─────────────────┐
                          │   findings     │ │  telemetry   │ │ agent_instances  │
                          │   table        │ │  table       │ │  (status update) │
                          └────────────────┘ └──────────────┘ └─────────────────┘
                                    │
                          ┌─────────┤──────────────┐
                          ▼                        ▼
                  ┌────────────────┐     ┌──────────────────┐
                  │  peer_reviews  │     │  Red Team        │
                  │  (adaptive)    │     │  Challenges      │
                  └────────────────┘     └──────────────────┘
                          │                        │
                          ▼                        ▼
                  ┌──────────────────────────────────────────┐
                  │        Knowledge Graph                    │
                  │   (nodes + edges + confidence scores)     │
                  └──────────────────────────────────────────┘
                          │                        │
                          ▼                        ▼
                  ┌────────────────┐     ┌──────────────────┐
                  │  economy_      │     │  Observatory     │
                  │  ledger        │     │  Dashboard       │
                  └────────────────┘     └──────────────────┘
```

### 3.3 Data Sources & Sinks

| Source/Sink | Type | Format | Volume | Frequency |
|-------------|------|--------|--------|-----------|
| Kimi K2.5 API | External API | JSON (OpenAI-compatible) | ~2-3 MB per thinking-mode response | Per agent instance (up to 3 concurrent) |
| PubMed E-utilities | External API | XML/JSON | ~10-50 KB per query | Per Scout sweep (configurable interval) |
| ClinicalTrials.gov | External API | JSON | ~5-20 KB per query | Per Scout sweep |
| bioRxiv/medRxiv | External API/RSS | XML/JSON | ~5-20 KB per query | Per Scout sweep |
| USPTO PatentsView | External API | JSON | ~10-50 KB per query | Per Scout sweep |
| Google Patents | External API/Web | JSON/HTML | ~10-50 KB per query | Per Scout sweep |
| PostgreSQL | Local Database | SQL/JSONB | Growing — starts empty, scales with civilization activity | Continuous |
| Observatory WebSocket | Internal | JSON events | ~1-5 KB per event | Real-time on every state change |

### 3.4 Validation Rules

| Field/Entity | Rule | Error Response |
|--------------|------|----------------|
| objectives.priority | Must be 1-10 integer | Reject with "Priority must be between 1 and 10" |
| objectives.objective_type | Must be one of: strategic, tactical, exploratory | Reject with valid options list |
| agent_personas.autonomy_level | Must be 1-5 integer | Reject with range error |
| knowledge_graph_nodes.confidence_score | Must be 0.000-1.000 | Clamp to range bounds |
| economy_ledger.amount | Must be positive | Reject — all transactions are positive amounts with directional from/to |
| objective_decomposition DAG | Must be acyclic (no circular dependencies) | Reject with cycle details |
| agent_instances.retry_count | Max 1 before debugger escalation | Trigger debugger agent |
| findings.review_round | Max 2 before human escalation | Trigger circuit breaker |
| KG node labels | Fuzzy deduplication check before creation | Prompt agent to reference existing node |

---

## 4. Integration Points

### 4.1 External Systems

#### Integration: Moonshot AI (Kimi K2.5 API)

- **Type:** REST API (OpenAI-compatible)
- **Direction:** Outbound
- **Authentication:** Bearer token (API key in environment variable `MOONSHOT_API_KEY`)
- **Endpoint:** `https://api.moonshot.ai/v1/chat/completions`
- **Data Contract:**
  ```json
  {
    "model": "kimi-k2.5",
    "messages": [
      {"role": "system", "content": "<interpolated persona system prompt>"},
      {"role": "user", "content": "<objective + KG context + institutional memory>"}
    ],
    "temperature": 1.0,
    "top_p": 0.95,
    "max_tokens": 8192
  }
  ```
  Response includes `choices[0].message.content` (output) and `choices[0].message.reasoning_content` (thinking trace).
  Usage includes `prompt_tokens`, `completion_tokens`, and potentially `reasoning_tokens`.
- **Error Handling:** Retry with exponential backoff (1s, 2s, 4s) for 429/500/503. Timeout at 300s. Log all failures to telemetry.

#### Integration: PubMed E-utilities API

- **Type:** REST API
- **Direction:** Inbound (data acquisition)
- **Authentication:** API key recommended (higher rate limits)
- **Endpoint:** `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
- **Error Handling:** Respect rate limits (3 req/sec without key, 10/sec with). Retry on transient failures. Log in telemetry.

#### Integration: ClinicalTrials.gov API

- **Type:** REST API
- **Direction:** Inbound (data acquisition)
- **Authentication:** None required
- **Endpoint:** `https://clinicaltrials.gov/api/v2/`
- **Error Handling:** Standard retry with backoff.

#### Integration: bioRxiv/medRxiv

- **Type:** REST API
- **Direction:** Inbound (data acquisition)
- **Authentication:** None required
- **Endpoint:** `https://api.biorxiv.org/` and `https://api.medrxiv.org/`
- **Error Handling:** Standard retry with backoff.

#### Integration: USPTO PatentsView API

- **Type:** REST API
- **Direction:** Inbound (data acquisition)
- **Authentication:** API key
- **Endpoint:** `https://api.patentsview.org/`
- **Error Handling:** Standard retry with backoff.

#### Integration: Google Patents

- **Type:** BigQuery public dataset or web scraping
- **Direction:** Inbound (data acquisition)
- **Authentication:** Google Cloud credentials if using BigQuery, none for public search
- **Error Handling:** Rate limiting, standard retry.

### 4.2 Internal Dependencies

| Dependency | Purpose | Criticality |
|------------|---------|-------------|
| PostgreSQL 16+ | All data persistence, event triggers, JSONB operations | Critical — system cannot function without it |
| Python 3.12+ | Runtime for all three backend processes | Critical |
| Node.js 20+ / React 18+ | Observatory dashboard frontend | High — system functions without it but loses monitoring |
| sentence-transformers | Generating specialization_vector embeddings for persona-task matching | High — fallback to keyword matching if unavailable |
| httpx | Async HTTP client for all external API calls | Critical |
| asyncio | Concurrency runtime for agent engine | Critical |

---

## 5. Non-Functional Requirements

### 5.1 Performance

| Metric | Requirement | Measurement |
|--------|-------------|-------------|
| Objective pickup latency | Originator picks up new objective within 5 seconds of DB insertion | Timestamp diff: objectives.created_at vs first agent_instances.started_at |
| Agent instance execution | 30-300 seconds per Kimi K2.5 thinking-mode call | agent_telemetry.latency_ms |
| Dashboard refresh | Real-time (WebSocket push within 1 second of state change) | Client-side event timestamp |
| Concurrent API calls | Max 3 simultaneous Kimi K2.5 calls | Semaphore enforcement in engine |
| KG query performance | Node/edge lookups < 100ms for up to 100K nodes | PostgreSQL EXPLAIN ANALYZE |

### 5.2 Security

- **Authentication:** API keys stored in environment variables. No hardcoded secrets.
- **Authorization:** Single operator (Jonathan). No RBAC needed for PoC.
- **Data Protection:** None required — no PHI, local-only deployment. Standard PostgreSQL connection (no SSL needed for localhost).
- **Audit Requirements:** Full audit trail via agent_telemetry, economy_ledger, governance_proposals/votes, and findings tables. All state changes are timestamped and attributed.

### 5.3 Compliance

| Framework | Requirements | Implementation Notes |
|-----------|--------------|---------------------|
| N/A for PoC | No PHI, no patient data, no external data egress | KG starts empty, no regulated data involved |

### 5.4 Reliability

- **Availability Target:** Best-effort for local development tool. System should recover gracefully from crashes.
- **Recovery Strategy:** All state in PostgreSQL. Any process can crash and restart without data loss. Running agent instances fail gracefully — their status is updated to 'failed' and the Originator retries on next cycle.
- **Backup Strategy:** Standard PostgreSQL pg_dump. Recommended daily for active research campaigns.

### 5.5 Scalability

- **Current Scale:** 1 operator, 10-50 active personas, hundreds of KG nodes, dozens of objectives
- **Growth Projection:** KG could grow to 100K+ nodes in sustained research campaigns. Agent population self-regulates via economy.
- **Scaling Strategy:** Vertical — the GX10 with 128GB RAM is more than sufficient. PostgreSQL indexes on frequently queried columns. No horizontal scaling needed for PoC.

---

## 6. Technical Specifications

### 6.1 Technology Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| Language (Backend) | Python 3.12+ | Ecosystem fit for LLM integration, async support, scientific computing |
| Language (Frontend) | TypeScript + React 18 | Interactive dashboard with real-time updates |
| CLI Framework | Typer | Lightweight, type-hint-driven, good DX |
| API Framework | FastAPI | Native async, WebSocket support, auto-generated OpenAPI docs |
| Agent Engine | asyncio + httpx | Clean async HTTP to Moonshot API, semaphore-controlled concurrency |
| Database | PostgreSQL 16+ with JSONB | Single backing store for all data, proven with Jonathan's GKG pipeline |
| DB Access | SQLAlchemy Core + asyncpg + Alembic | Query builder without ORM overhead, async performance, versioned migrations |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2 or similar, 384-dim) | Specialization vector generation for persona-task matching |
| Frontend Build | Vite | Fast dev server, clean production builds |
| Frontend Charts | Recharts or D3.js | KG visualization, lineage trees, economy charts |
| WebSocket | FastAPI WebSocket + React useWebSocket | Real-time observatory updates |

### 6.2 Architecture Pattern

- **Pattern:** Three separate processes sharing a common core library, integrated via PostgreSQL as event bus
- **Rationale:** Maximum isolation — any component can crash, restart, or be updated independently. The database is the single source of truth and integration point. No in-memory state is required to survive restarts. Event-driven triggers in PostgreSQL (or polling with `LISTEN/NOTIFY`) decouple the engine from the API server.

### 6.3 Project Structure

```
nexus/
├── nexus-core/                    # Shared Python library
│   ├── __init__.py
│   ├── config.py                  # Runtime configuration (env vars, defaults)
│   ├── database.py                # SQLAlchemy Core engine, session factory, async setup
│   ├── models/                    # SQLAlchemy Core table definitions
│   │   ├── __init__.py
│   │   ├── personas.py
│   │   ├── instances.py
│   │   ├── objectives.py
│   │   ├── decomposition.py
│   │   ├── knowledge_graph.py
│   │   ├── findings.py
│   │   ├── peer_reviews.py
│   │   ├── economy.py
│   │   ├── governance.py
│   │   ├── messages.py
│   │   ├── institutional_memory.py
│   │   ├── tool_registry.py
│   │   └── telemetry.py
│   ├── llm/                       # LLM client abstraction
│   │   ├── __init__.py
│   │   ├── client.py              # Async Kimi K2.5 API client (OpenAI-compatible)
│   │   ├── prompt_builder.py      # Persona template interpolation
│   │   └── response_parser.py     # Output parsing, structured extraction
│   ├── economy/                   # Economy engine
│   │   ├── __init__.py
│   │   ├── ledger.py              # Credit minting, transfers, rent decay
│   │   ├── fitness.py             # Market-based fitness calculation
│   │   └── diversity.py           # Novelty bonus, role class minimums
│   ├── evolution/                 # Evolutionary engine
│   │   ├── __init__.py
│   │   ├── mutator.py             # Persona mutation (prompt, tools, strategy)
│   │   ├── evaluator.py           # Candidate evaluation
│   │   └── pruner.py              # Deprecation logic with diversity constraints
│   ├── knowledge/                 # Knowledge graph operations
│   │   ├── __init__.py
│   │   ├── graph_ops.py           # CRUD, dedup, path traversal
│   │   ├── confidence.py          # Confidence propagation engine
│   │   └── query.py               # Structured KG queries for agent context injection
│   ├── review/                    # Peer review + Red Team
│   │   ├── __init__.py
│   │   ├── peer_review.py         # Adaptive review orchestration
│   │   ├── red_team.py            # Challenge filing, bounty logic
│   │   └── infiltrator.py         # Infiltration test injection
│   ├── governance/                # Governance engine
│   │   ├── __init__.py
│   │   ├── proposals.py           # Proposal creation, lifecycle
│   │   └── voting.py              # Reputation-weighted voting
│   ├── scouts/                    # External data source clients
│   │   ├── __init__.py
│   │   ├── pubmed.py
│   │   ├── clinicaltrials.py
│   │   ├── biorxiv.py
│   │   ├── patents_uspto.py
│   │   └── patents_google.py
│   └── utils/                     # Shared utilities
│       ├── __init__.py
│       ├── embeddings.py          # Sentence-transformer wrapper for specialization vectors
│       ├── cost.py                # Cost calculation (Moonshot pricing)
│       └── logging.py             # Structured logging setup
│
├── nexus-engine/                  # Agent orchestration daemon
│   ├── __init__.py
│   ├── main.py                    # Async event loop, process entry point
│   ├── originator.py              # Originator agent control loop
│   ├── decomposer.py              # Objective decomposition (DAG construction)
│   ├── dispatcher.py              # Agent instance spawning (semaphore-controlled)
│   ├── integrator.py              # Result collection, KG updates, dependency triggering
│   ├── dream_cycle.py             # Offline knowledge consolidation
│   └── scheduler.py               # Periodic tasks (scout sweeps, rent decay, evolution)
│
├── nexus-cli/                     # Typer CLI
│   ├── __init__.py
│   ├── main.py                    # Typer app with all commands
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── submit.py
│   │   ├── status.py
│   │   ├── agents.py
│   │   ├── objectives.py
│   │   ├── kg.py
│   │   ├── economy.py
│   │   ├── evolve.py
│   │   ├── dream.py
│   │   ├── scout.py
│   │   ├── cost.py
│   │   └── config.py
│   └── formatters.py              # Rich table formatting for terminal output
│
├── nexus-dashboard/               # React observatory
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── hooks/
│   │   │   └── useWebSocket.ts
│   │   ├── components/
│   │   │   ├── AgentPopulation.tsx     # Hero view: persona table with fitness
│   │   │   ├── EvolutionaryLineage.tsx # Tree visualization
│   │   │   ├── ObjectiveDAG.tsx        # Task decomposition graph
│   │   │   ├── KnowledgeGraph.tsx      # Force-directed KG visualization
│   │   │   ├── EconomyPanel.tsx        # Credit circulation, Gini coefficient
│   │   │   └── CostReport.tsx          # CCWAP-style cost analytics
│   │   ├── api/
│   │   │   └── client.ts              # REST + WebSocket client
│   │   └── types/
│   │       └── index.ts               # TypeScript interfaces matching backend models
│   └── public/
│
├── nexus-api/                     # FastAPI dashboard backend
│   ├── __init__.py
│   ├── main.py                    # FastAPI app with CORS, WebSocket
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── agents.py              # GET /agents, GET /agents/{id}
│   │   ├── objectives.py          # GET /objectives, GET /objectives/{id}/dag
│   │   ├── knowledge_graph.py     # GET /kg/nodes, GET /kg/edges, GET /kg/stats
│   │   ├── economy.py             # GET /economy/summary, GET /economy/ledger
│   │   ├── telemetry.py           # GET /telemetry/cost, GET /telemetry/performance
│   │   └── evolution.py           # GET /evolution/lineage
│   ├── websocket.py               # WebSocket manager for real-time updates
│   └── schemas.py                 # Pydantic response schemas
│
├── migrations/                    # Alembic migrations
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── seed/                          # Seed data
│   ├── personas.json              # Initial persona configurations (10-15 seed personas)
│   └── tools.json                 # Built-in tool definitions
│
├── tests/                         # Test suite
│   ├── conftest.py
│   ├── test_originator.py
│   ├── test_decomposer.py
│   ├── test_dispatcher.py
│   ├── test_economy.py
│   ├── test_evolution.py
│   ├── test_peer_review.py
│   ├── test_red_team.py
│   ├── test_knowledge_graph.py
│   ├── test_governance.py
│   └── test_telemetry.py
│
├── pyproject.toml                 # Python project config (dependencies, build)
├── .env.example                   # Environment variable template
├── README.md                      # Setup and architecture overview
└── docker-compose.yml             # Optional: PostgreSQL service for local dev
```

### 6.4 Seed Personas (Initial Population)

The following 13 personas are seeded at system initialization:

| Persona Name | Role Class | Reasoning Strategy | Autonomy Level | Description |
|-------------|------------|-------------------|----------------|-------------|
| Genesis Originator | originator | tree-of-thought | 5 | The stem cell — decomposes objectives, recruits/creates agents, manages lifecycle |
| Deep Researcher Alpha | researcher | hypothesis-driven | 3 | Primary research agent — hypothesis formation, evidence gathering, analysis |
| Lateral Researcher Beta | researcher | debate-with-self | 3 | Alternative research approach — dialectical reasoning, considers opposing viewpoints |
| Systems Synthesizer | synthesizer | chain-of-thought | 3 | Combines findings across sub-objectives into coherent narratives |
| Methodological Critic | critic | adversarial | 3 | Evaluates research methodology and logical rigor during peer review |
| Evidence Critic | critic | analytical | 3 | Evaluates evidence quality and sufficiency during peer review |
| Sentinel Red Team | red_team | adversarial | 4 | Actively attacks validated findings to find flaws |
| Shadow Infiltrator | infiltrator | chain-of-thought | 4 | Generates plausible-but-wrong findings to test peer review quality |
| Chief Governor | governor | analytical | 4 | Evaluates governance proposals and persona activation requests |
| Nightwatch Consolidator | consolidator | tree-of-thought | 3 | Dream Cycle agent — identifies cross-cutting patterns during consolidation |
| Scout Vanguard | scout | chain-of-thought | 4 | Monitors external sources (PubMed, patents, etc.) for relevant intelligence |
| Diagnostic Debugger | debugger | analytical | 3 | Diagnoses agent failures — analyzes failed prompts, identifies root causes |
| Tool Smith | tool_forger | chain-of-thought | 2 | Creates new tools when capability gaps are identified (Governor approval required) |

---

## 7. Testing Requirements

### 7.1 Test Scenarios

#### Scenario: End-to-End Objective Lifecycle

- **Type:** Integration
- **Preconditions:** Database initialized with seed personas, Originator engine running, Kimi K2.5 API accessible
- **Steps:**
  1. Submit strategic objective via CLI: "How do we solve unemployment caused by AI"
  2. Verify Originator picks up objective and decomposes into sub-objective DAG
  3. Verify agent instances spawn for leaf sub-objectives with correct persona configs
  4. Verify Kimi K2.5 API calls succeed with thinking mode enabled
  5. Verify findings written to database with correct provenance
  6. Verify peer review triggered with adaptive reviewer count
  7. Verify validated findings committed to KG with correct confidence scores
  8. Verify economy credits minted and distributed correctly
  9. Verify dependent sub-objectives triggered on predecessor completion
  10. Verify final synthesis produced when all sub-objectives complete
- **Expected Result:** KG populated with interconnected findings, economy differentiated, telemetry complete
- **Priority:** Critical

#### Scenario: Agent Failure and Debugger Recovery

- **Type:** Integration
- **Preconditions:** Active agent instance, simulated API failure
- **Steps:**
  1. Agent instance fails (simulated timeout or malformed response)
  2. Verify retry fires once with same persona
  3. Simulate second failure
  4. Verify debugger agent spawns with failure context
  5. Verify debugger diagnosis written to institutional_memory
- **Expected Result:** Failure diagnosed, institutional memory updated, objective re-queued or escalated
- **Priority:** High

#### Scenario: Evolutionary Cycle

- **Type:** Integration
- **Preconditions:** Multiple completed objectives, personas with varying credit balances
- **Steps:**
  1. Complete an objective
  2. Verify rent decay applied to all active personas
  3. Verify top-performing persona identified and mutation generated
  4. Verify candidate persona created with parent lineage
  5. Verify candidate evaluated on validation task
  6. Verify role class minimums prevent over-pruning
- **Expected Result:** Population evolved — new candidate activated or deprecated, underperformers flagged
- **Priority:** High

#### Scenario: Peer Review Circuit Breaker

- **Type:** Integration
- **Preconditions:** Finding that will fail review
- **Steps:**
  1. Finding submitted for peer review
  2. Reviewers reject with feedback
  3. Finding revised and resubmitted
  4. Reviewers reject again
  5. Verify circuit breaker fires — objective escalated to human
- **Expected Result:** Objective status = 'escalated', no further API calls, visible in CLI `nexus status`
- **Priority:** High

#### Scenario: Budget Governor

- **Type:** Unit
- **Preconditions:** Configurable budget threshold
- **Steps:**
  1. Set budget floor to $5.00
  2. Simulate cumulative spend approaching $33.25 (i.e., $38.25 - $5.00)
  3. Verify warning logged at threshold
  4. Simulate spend reaching $37.25 ($1.00 remaining)
  5. Verify Originator auto-pauses
- **Expected Result:** System safely stops before exhausting budget
- **Priority:** Critical

### 7.2 Test Coverage Requirements

| Category | Coverage Target | Notes |
|----------|-----------------|-------|
| Unit Tests | 80%+ on nexus-core | Focus on economy calculations, KG operations, confidence propagation, prompt building |
| Integration Tests | Key workflows | Objective lifecycle, peer review pipeline, evolutionary cycle, failure recovery |
| E2E Tests | 1 critical path | The acceptance test: full objective submission through KG population |

### 7.3 Test Data Requirements

- Seed personas loaded from `seed/personas.json`
- Mock Kimi K2.5 API responses for unit tests (httpx mock transport)
- Test PostgreSQL database (separate from production, created/destroyed per test run)
- Synthetic objectives for integration testing

---

## 8. Deployment & Operations

### 8.1 Deployment Target

- **Environment:** Local — ASUS Ascent GX10 (128GB RAM, NVIDIA Blackwell GPU, 18 workers)
- **Infrastructure:** Native Python processes + PostgreSQL (no containers required, docker-compose.yml provided as optional convenience for PostgreSQL)
- **Orchestration:** None required — three processes managed via systemd, screen/tmux, or simple process manager

### 8.2 Environment Configuration

| Environment | Purpose | Config Notes |
|-------------|---------|--------------|
| Development | Build and test | Local PostgreSQL, test API key, mock mode available |
| Production (Local) | Active research campaigns | Local PostgreSQL, real Moonshot API key, full telemetry |

### 8.3 Startup Sequence

1. PostgreSQL running (local or docker)
2. Run Alembic migrations: `alembic upgrade head`
3. Seed initial data: `nexus seed` (loads personas.json and tools.json)
4. Start engine: `nexus-engine` (Originator daemon)
5. Start API: `nexus-api` (FastAPI server for dashboard)
6. Open dashboard: `http://localhost:8000`
7. Submit first objective: `nexus submit "How do we solve unemployment caused by AI" --priority 10 --type strategic`

### 8.4 Monitoring & Observability

| Aspect | Tool/Approach | Alerts |
|--------|---------------|--------|
| Structured Logging | Python `structlog` with JSON output | All agent lifecycle events, API calls, errors |
| Token Tracking | `agent_telemetry` table with per-call breakdown | Running totals visible in CLI (`nexus cost`) and dashboard |
| Latency Metrics | `agent_telemetry.latency_ms` | Dashboard performance panel |
| Cost Reporting | CCWAP-style: cumulative spend, per-agent, per-objective, cost-per-finding | Budget warning at configurable threshold, auto-pause at floor |
| Economy Health | Gini coefficient, circulation rate, rent-to-mint ratio | Dashboard economy panel flags degenerate equilibria |
| System Health | Process heartbeats, DB connection status | Dashboard header shows component status |

---

## 9. Documentation Requirements

### 9.1 Required Documentation

| Document | Audience | Contents |
|----------|----------|----------|
| This Requirements Document | Downstream coding agents (Claude Code) | Complete system specification — sufficient for implementation with zero clarification |

README and additional documentation to be commissioned separately upon project completion.

---

## 10. Constraints & Risks

### 10.1 Known Constraints

| Constraint | Impact | Mitigation |
|------------|--------|------------|
| Moonshot API budget ($38.25 initial) | Limits total agent runs to ~15 deep thinking-mode executions | Aggressive prompt efficiency, budget governor with auto-pause, willingness to top up on demonstrated value |
| Kimi K2.5 thinking mode latency (30-300s per call) | Limits throughput even with 3-concurrent semaphore | Event-driven architecture means system doesn't block — other work proceeds while calls are in-flight |
| 3-concurrent API call limit | Caps parallelism | DAG scheduling prioritizes critical path dependencies to maximize useful parallelism |
| Local-only deployment | No cloud scaling, no multi-user access | GX10 has 128GB RAM — more than sufficient for PoC scale |
| Single operator (Jonathan) | No concurrent objective submission, no delegated administration | CLI is synchronous, dashboard is read-only for observers |

### 10.2 Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Agent outputs are incoherent / low-quality (civilization produces garbage) | Medium | High | Three-layer quality filter: adaptive peer review → Red Team challenge → circuit breaker to human. Institutional memory prevents repeated failures. Debugger agent diagnoses root causes. |
| Economy/evolution creates degenerate equilibria (all agents converge to same strategy) | Medium | High | Role class minimums (min 2 per class), novelty bonus for dissimilar findings, Gini coefficient monitoring, Governor proposals can adjust economy parameters |
| Moonshot API instability or rate limiting | Low-Medium | Medium | Exponential backoff with jitter, graceful degradation (engine pauses and resumes), clean LLM client abstraction allows provider swap if needed |
| Scope too large for single build cycle | Low | Medium | No deadline constraint. Modular architecture allows layer-by-layer construction and testing. Each layer is independently valuable. |
| KG confidence propagation creates cascading collapses | Low | Medium | Propagation dampening: each hop reduces confidence impact by configurable decay factor (e.g., 0.7x per hop). Governor can freeze propagation if instability detected. |
| Evolutionary engine produces degenerate mutations (worse prompts than parents) | Medium | Low | Candidates must pass validation objective before activation. Failed candidates are deprecated without affecting the parent population. |

### 10.3 Assumptions

| Assumption | If False |
|------------|----------|
| Kimi K2.5 API is OpenAI-compatible and accessible from US (Parker, CO) | Switch to OpenRouter or Together.ai as Kimi K2.5 providers (same model, different endpoint) |
| $38.25 is sufficient for meaningful PoC (15+ deep reasoning runs) | Top up credits or switch to Instant mode (non-thinking) for routine tasks |
| PostgreSQL 16+ available locally or installable on GX10 | Use Docker for PostgreSQL only |
| sentence-transformers can run locally on GX10 for embedding generation | Use Kimi K2.5 API for embedding generation (more expensive) or precompute and cache |
| Kimi K2.5 thinking mode produces structured, parseable output when instructed | Add robust parsing fallbacks in response_parser.py; worst case, switch to Instant mode with explicit CoT prompting |

---

## 11. Success Criteria

### 11.1 Acceptance Test

Submit the strategic objective **"How do we solve unemployment caused by AI"** via CLI. The civilization must:

- [ ] Originator decomposes the objective into a multi-branch DAG with at least 3 distinct sub-objectives
- [ ] At least 3 different persona types are activated across sub-objectives (e.g., researcher, synthesizer, critic)
- [ ] Agent instances execute via Kimi K2.5 API in thinking mode with full telemetry captured
- [ ] Findings produced and written to the findings table with markdown content
- [ ] Adaptive peer review triggers (correct number of reviewers based on impact level)
- [ ] At least one finding is validated and committed to the KG with provenance chains
- [ ] Red Team agent files at least one challenge against a validated finding
- [ ] Economy credits minted, distributed, and rent decay applied — at least two personas have meaningfully different credit balances
- [ ] At least one evolutionary evaluation occurs (mutation or pruning candidate identified)
- [ ] Observatory dashboard displays live agent population with fitness scores
- [ ] Evolutionary lineage tree shows at least one parent→child relationship
- [ ] Cost report accurately reflects all Moonshot API spending to the cent
- [ ] The final synthesis is a coherent, multi-perspective markdown document that addresses the original question with identifiable contributions from multiple agents

### 11.2 Definition of Done

- [ ] All acceptance test criteria pass in a single end-to-end run
- [ ] Unit test coverage ≥ 80% on nexus-core
- [ ] Integration tests pass for: objective lifecycle, peer review, evolution, failure recovery, budget governor
- [ ] Requirements document complete (this document)
- [ ] System runs on GX10 without manual intervention from objective submission to synthesis output
- [ ] Cost report reconciles with actual Moonshot API dashboard billing

### 11.3 Out of Scope (Explicit)

- HIPAA compliance, PHI handling, or encrypted data at rest
- Multi-user authentication or role-based access control
- Cloud deployment, horizontal scaling, or container orchestration
- Bootstrapping KG from existing GKG data (empty-start by design)
- Real-time voice/audio interfaces
- Integration with Snowflake or existing BioInfo AI data warehouse
- Mobile application
- Automated PDF report generation (plain markdown only)
- Model fine-tuning or local model hosting
- Provider-swapping abstraction (clean client interface for future migration, but only Moonshot implemented in v1)

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| Originator | The persistent orchestration agent that decomposes objectives, recruits/creates personas, and manages civilization lifecycle. Analogous to a CEO + compiler + stem cell. |
| Persona | A database-driven agent blueprint (system prompt, tools, reasoning strategy). Not a running process — a configuration that gets instantiated. |
| Instance | A running execution of a persona against a specific objective. Created by the Originator, executed via Kimi K2.5 API call. |
| Objective | A unit of work in the civilization's mission. Can be strategic (human-submitted), tactical (Governor-approved), or exploratory (agent-self-approved). |
| Decomposition DAG | A directed acyclic graph of sub-objectives derived from a parent objective, with dependency edges. |
| Knowledge Graph (KG) | The civilization's collective intelligence — a PostgreSQL-backed graph of nodes and edges with confidence scores and full provenance. |
| Fitness | An agent persona's accumulated credit balance in the market economy. Higher fitness = more resources = greater survival probability. |
| Rent Decay | Periodic credit deduction from all active personas, creating "produce or die" metabolic pressure. |
| Dream Cycle | Offline knowledge consolidation where a Consolidator agent reviews recent KG additions to find cross-cutting patterns. |
| Circuit Breaker | Safety mechanism: after two failed peer reviews, an objective escalates to human rather than burning more API credits. |
| Infiltrator | A specialized agent that injects plausible-but-wrong findings to stress-test the peer review system. |
| Role Class Minimum | Diversity constraint: the evolutionary engine cannot prune below N active personas per role class. |
| Novelty Bonus | Credit multiplier for agents whose findings introduce dissimilar KG content, preventing convergent evolution. |
| Institutional Memory | Civilization-level lessons learned, stored persistently and injected into agent context to prevent repeated mistakes. |

## Appendix B: Reference Materials

| Resource | Link/Location | Purpose |
|----------|---------------|---------|
| Kimi K2.5 API Documentation | https://platform.moonshot.ai/docs/guide/kimi-k2-5-quickstart | API reference, tool calling, thinking mode |
| Kimi K2.5 GitHub | https://github.com/MoonshotAI/Kimi-K2.5 | Model details, deployment guide, usage examples |
| Moonshot API Pricing | https://platform.moonshot.ai | $0.60/M input tokens, $2.50/M output tokens |
| PubMed E-utilities | https://www.ncbi.nlm.nih.gov/books/NBK25501/ | API reference for Scout agents |
| ClinicalTrials.gov API | https://clinicaltrials.gov/data-api/api | API reference for Scout agents |
| bioRxiv API | https://api.biorxiv.org/ | API reference for Scout agents |
| USPTO PatentsView API | https://patentsview.org/apis | API reference for Scout agents |
| Self-Evolving AI Agents Survey | https://arxiv.org/abs/2508.07407 | Academic context for evolutionary architecture |
| Generative Agents (Park et al.) | Stanford + Google DeepMind | Foundational reference for agent societies |

---

**Document Approval**

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Stakeholder | Jonathan | March 16, 2026 | ☐ Pending Approval |
| BSA | Claude | March 16, 2026 | ☑ Generated |
