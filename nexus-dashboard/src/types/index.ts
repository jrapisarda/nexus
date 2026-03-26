/** TypeScript interfaces matching the NEXUS Pydantic API schemas. */

export interface Persona {
  persona_id: string;
  persona_name: string;
  role_class: string;
  system_prompt_template?: string | null;
  tool_permissions?: unknown[] | null;
  reasoning_strategy?: string | null;
  model_config_json?: Record<string, unknown> | null;
  autonomy_level?: number | null;
  parent_persona_id?: string | null;
  sponsor_persona_id?: string | null;
  generation: number;
  credit_balance: number;
  reputation_score: number;
  compute_budget: number;
  status: string;
  probation_until?: string | null;
  capability_scores?: Record<string, number> | null;
  current_assignment?: string | null;
  current_assignment_status?: string | null;
  current_assignment_started_at?: string | null;
  current_assignment_reason?: string | null;
  mutation_diff?: Record<string, unknown> | null;
  created_at: string;
  deprecated_at?: string | null;
  deprecation_reason?: string | null;
}

export interface PersonaListResponse {
  personas: Persona[];
  count: number;
}

export interface Objective {
  objective_id: string;
  parent_objective_id?: string | null;
  title: string;
  description: string;
  objective_type: string;
  impact_level?: string | null;
  priority: number;
  status: string;
  proposed_by_type: string;
  proposed_by_id?: string | null;
  approved_by_type?: string | null;
  approved_by_id?: string | null;
  assigned_to?: string | null;
  acceptance_criteria?: string | null;
  knowledge_graph_anchor?: unknown[] | null;
  compute_budget_allocated?: number | null;
  output_type?: string | null;
  file_attachment_ids?: string[] | null;
  created_at: string;
  completed_at?: string | null;
  escalated_at?: string | null;
  escalation_reason?: string | null;
}

// ── File Uploads ──────────────────────────────────────────────────────

export interface FileUploadResponse {
  attachment_id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  upload_status: string;
  created_at: string;
}

export interface ObjectiveCreateRequest {
  title: string;
  description: string;
  objective_type: string;
  priority: number;
  attachment_ids: string[];
}

export interface ObjectiveListResponse {
  objectives: Objective[];
  count: number;
}

export interface DAGNode {
  id: string;
  data: {
    label: string;
    status: string;
    type: string;
    priority: number;
    color: string;
  };
  position: { x: number; y: number };
  type?: string;
}

export interface DAGEdge {
  id: string;
  source: string;
  target: string;
  label?: string | null;
  animated?: boolean;
}

export interface ObjectiveDAGResponse {
  nodes: DAGNode[];
  edges: DAGEdge[];
}

export interface KGNode {
  node_id: string;
  node_type: string;
  label: string;
  properties?: Record<string, unknown> | null;
  confidence_score: number;
  discovered_by_objective_id?: string | null;
  discovered_by_instance_id?: string | null;
  validation_count: number;
  challenge_count: number;
  challenge_failures: number;
  status: string;
  first_seen: string;
  last_validated?: string | null;
}

export interface KGEdge {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: string;
  weight: number;
  confidence_score: number;
  evidence_ids?: unknown[] | null;
  discovered_by_objective_id?: string | null;
  challenged_by_objective_ids?: unknown[] | null;
  status: string;
  properties?: Record<string, unknown> | null;
  created_at: string;
}

export interface KGStats {
  node_count: number;
  edge_count: number;
  avg_confidence: number;
  validated_count: number;
  proposed_count: number;
  contested_count: number;
  node_type_counts: Record<string, number>;
  relationship_type_counts: Record<string, number>;
}

export interface CitationRecord {
  title: string;
  source_type: string;
  source_name: string;
  url: string;
  doi: string;
  published_date: string;
  authors: string[];
  supporting_snippet: string;
  source_finding_id?: string | null;
  derived: boolean;
}

export interface KGWorkbenchObjectiveTouch {
  objective_id: string;
  title: string;
  status: string;
  node_count: number;
  edge_count: number;
}

export interface KGObjectiveSearchResult {
  objective_id: string;
  title: string;
  status: string;
  objective_type: string;
  impact_level?: string | null;
}

export interface KGFindingSearchResult {
  finding_id: string;
  title: string;
  objective_id: string;
  objective_title: string;
  status: string;
  impact_level: string;
}

export interface KGWorkbenchOverview {
  node_count: number;
  edge_count: number;
  avg_confidence: number;
  challenged_node_count: number;
  challenged_edge_count: number;
  recent_change_count: number;
  report_linked_node_count: number;
  report_linked_edge_count: number;
  top_objectives: KGWorkbenchObjectiveTouch[];
}

export interface ReportArtifactSummary {
  title: string;
  slug: string;
  artifact_type: string;
  objective_id: string;
  finding_id?: string | null;
  version: string;
  updated_at: string;
  size_bytes: number;
}

export interface ReportArtifactListResponse {
  items: ReportArtifactSummary[];
  count: number;
}

export interface ReportFile {
  slug: string;
  title: string;
  artifact_type: string;
  updated_at: string;
  size_bytes: number;
  content: string;
}

export interface KGEvidenceFinding {
  finding_id: string;
  objective_id: string;
  objective_title: string;
  title: string;
  finding_type: string;
  status: string;
  impact_level: string;
  review_round: number;
  created_at: string;
  kg_node_refs: string[];
  kg_edge_refs: string[];
  citations: CitationRecord[];
}

export interface LinkedObjective {
  objective_id: string;
  title: string;
  status: string;
  objective_type: string;
  impact_level?: string | null;
}

export interface KGChangeItem {
  event_id: string;
  event_type: string;
  entity_id?: string | null;
  entity_type?: string | null;
  title: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface KGChangeFeedResponse {
  items: KGChangeItem[];
  count: number;
  window_hours: number;
}

export interface KGNodeDetail {
  node: KGNode;
  adjacent_edges: KGEdge[];
  linked_findings: KGEvidenceFinding[];
  linked_objectives: LinkedObjective[];
  linked_reports: ReportArtifactSummary[];
  linked_citations: CitationRecord[];
  relationship_groups: Record<string, string[]>;
  timeline: KGChangeItem[];
}

export interface KGSubgraphResponse {
  center_node_id?: string | null;
  scope_label?: string | null;
  nodes: KGNode[];
  edges: KGEdge[];
}

export interface KGPathStep {
  node_id: string;
  label: string;
  node_type: string;
  confidence: number;
  depth: number;
  edge_type?: string | null;
  edge_weight?: number | null;
  supporting_finding_ids: string[];
}

export interface KGPathResponse {
  start_node_id: string;
  end_node_id: string;
  found: boolean;
  steps: KGPathStep[];
  evidence: KGEvidenceFinding[];
}

export interface KGEvidenceRecord {
  query_type: string;
  findings: KGEvidenceFinding[];
  reports: ReportArtifactSummary[];
  citations: CitationRecord[];
  linked_objectives: LinkedObjective[];
  challenged_count: number;
}

export interface EconomySummary {
  total_personas: number;
  total_credits_minted: number;
  total_rent_collected: number;
  net_credits_in_system: number;
  gini_coefficient: number;
  top_balance: number;
  bottom_balance: number;
  mean_balance: number;
}

export interface LedgerEntry {
  transaction_id: string;
  from_persona_id?: string | null;
  to_persona_id?: string | null;
  amount: number;
  transaction_type: string;
  reference_objective_id?: string | null;
  reference_finding_id?: string | null;
  memo?: string | null;
  created_at: string;
}

export interface MarketOverview {
  active_listings: number;
  pending_contracts: number;
  fulfilled_contracts_24h: number;
  total_listing_value: number;
  category_breakdown: Record<string, number>;
  top_seller_ids: string[];
  top_buyer_ids: string[];
}

export interface MarketplaceListing {
  listing_id: string;
  listing_kind: string;
  price: number;
  quantity_available: number;
  status: string;
  description: string;
  metadata: Record<string, unknown>;
  created_at: string;
  seller_persona_id: string;
  seller_name: string;
  seller_role_class: string;
  template_code: string;
  template_title: string;
}

export interface ServiceContract {
  contract_id: string;
  status: string;
  agreed_price: number;
  quantity: number;
  created_at: string;
  fulfilled_at?: string | null;
  refunded_at?: string | null;
  target_objective_id?: string | null;
  target_finding_id?: string | null;
  service_objective_id?: string | null;
  fulfillment_summary?: string | null;
  template_code: string;
  template_title: string;
  buyer_persona_id: string;
  buyer_name: string;
  seller_persona_id: string;
  seller_name: string;
}

export interface MarketActivityItem {
  event_id: string;
  event_type: string;
  entity_id?: string | null;
  entity_type?: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface MarketActivityResponse {
  items: MarketActivityItem[];
  count: number;
}

export interface SecuritiesOverview {
  instrument_count: number;
  open_order_count: number;
  trade_volume: number;
  halted_count: number;
  settlement_backlog: number;
}

export interface MarketInstrument {
  instrument_id: string;
  symbol: string;
  name: string;
  family: string;
  risk_tier: string;
  halted: boolean;
  settlement_status: string;
  settlement_value?: number | null;
  last_trade_price: number;
  mark_price: number;
  expiry_at?: string | null;
  settlement_at?: string | null;
  metadata: Record<string, unknown>;
  underlying_objective_id?: string | null;
  underlying_finding_id?: string | null;
  underlying_persona_id?: string | null;
}

export interface OrderBookLevel {
  order_id: string;
  price: number;
  remaining_quantity: number;
  persona_name: string;
}

export interface OrderBook {
  instrument_id?: string | null;
  instrument_symbol?: string | null;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
}

export interface Trade {
  trade_id: string;
  instrument_id: string;
  instrument_symbol: string;
  price: number;
  quantity: number;
  notional: number;
  created_at: string;
  buyer_name: string;
  seller_name: string;
}

export interface Position {
  position_id: string;
  instrument_id: string;
  instrument_symbol: string;
  persona_id: string;
  persona_name: string;
  role_class: string;
  net_quantity: number;
  average_entry_price: number;
  realized_pnl: number;
  market_value: number;
  updated_at: string;
}

export interface TelemetryCost {
  total_spend_usd: number;
  per_agent: Array<{
    persona_id: string;
    persona_name: string;
    total_cost: number;
    call_count: number;
  }>;
  per_objective: Array<{
    objective_id: string;
    objective_title: string;
    total_cost: number;
    call_count: number;
  }>;
  budget_ceiling_usd: number;
  budget_remaining_usd: number;
}

export interface TelemetryPerformance {
  total_calls: number;
  success_rate: number;
  avg_latency_ms: number;
  error_breakdown: Record<string, number>;
}

export interface LineageNode {
  persona_id: string;
  persona_name: string;
  role_class: string;
  generation: number;
  status: string;
  parent_persona_id?: string | null;
  credit_balance: number;
}

export interface EvolutionLineageResponse {
  nodes: LineageNode[];
}

export interface ObservatoryOverview {
  active_personas: number;
  active_objectives: number;
  running_instances: number;
  pending_reviews: number;
  escalated_objectives: number;
  objectives_completed_24h: number;
  findings_validated_24h: number;
  mean_review_confidence_24h: number;
  total_spend_usd: number;
  budget_remaining_usd: number;
  budget_utilization_pct: number;
  success_rate_24h: number;
  total_calls_24h: number;
}

export interface AlertItem {
  alert_id: string;
  severity: string;
  category: string;
  title: string;
  summary: string;
  metric_label?: string | null;
  metric_value?: number | null;
  entity_id?: string | null;
  entity_type?: string | null;
  detected_at: string;
}

export interface AlertFeedResponse {
  alerts: AlertItem[];
  count: number;
}

export interface ReviewOutcomeSummary {
  finding_id: string;
  title: string;
  status: string;
  impact_level: string;
  review_round: number;
  mean_confidence: number;
  approval_count: number;
  support_count: number;
  reviewer_count: number;
  verdict: string;
  reviewed_at: string;
}

export interface ReviewIntel {
  total_reviews_24h: number;
  finding_outcomes_24h: number;
  mean_review_confidence_24h: number;
  approval_rate_24h: number;
  outcome_counts: Record<string, number>;
  reviewer_verdict_counts: Record<string, number>;
  finding_status_counts: Record<string, number>;
  high_impact_pending_count: number;
  recent_outcomes: ReviewOutcomeSummary[];
}

export interface PersonaWorkloadItem {
  persona_id: string;
  persona_name: string;
  role_class: string;
  status: string;
  current_assignment?: string | null;
  current_assignment_status?: string | null;
  running_instances: number;
  pending_instances: number;
  completed_24h: number;
  failed_24h: number;
  avg_latency_ms_24h: number;
  success_rate_24h: number;
  spend_24h: number;
}

export interface PersonaWorkloadResponse {
  items: PersonaWorkloadItem[];
  count: number;
  window_hours: number;
}

export interface ObjectiveRadarItem {
  objective_id: string;
  title: string;
  status: string;
  objective_type: string;
  impact_level?: string | null;
  priority: number;
  active_instances: number;
  completed_instances: number;
  findings_total: number;
  validated_findings: number;
  pending_reviews: number;
  subtree_objective_count: number;
  subtree_completed_count: number;
  progress_pct: number;
  total_cost_usd: number;
  age_minutes: number;
  last_activity_at: string;
  attention_score: number;
}

export interface ObjectiveRadarResponse {
  items: ObjectiveRadarItem[];
  count: number;
}

export interface CivilizationOverview {
  wealth_gini: number;
  top_balance_share: number;
  role_concentration: number;
  pending_challenges: number;
  pending_holdbacks: number;
  slow_science_objectives: number;
  degraded_scout_sources: number;
  open_breaker_incidents: number;
}

export interface CivilizationCapabilityPersona {
  persona_id: string;
  persona_name: string;
  role_class: string;
  reputation_score: number;
  credit_balance: number;
  capability_scores: Record<string, number>;
}

export interface CivilizationCapabilityResponse {
  items: CivilizationCapabilityPersona[];
  count: number;
}

export interface CivilizationChallenge {
  challenge_id: string;
  finding_id: string;
  finding_title: string;
  challenger_persona_id: string;
  challenger_name: string;
  flaw_type?: string | null;
  severity?: string | null;
  status: string;
  summary?: string | null;
  opened_at: string;
  resolution_due_at?: string | null;
  resolved_at?: string | null;
}

export interface CivilizationChallengeListResponse {
  items: CivilizationChallenge[];
  count: number;
}

export interface ScoutSourceHealth {
  source_name: string;
  health_status: string;
  consecutive_failures: number;
  total_runs: number;
  total_successes: number;
  findings_ingested: number;
  objectives_proposed: number;
  last_run_at?: string | null;
  last_success_at?: string | null;
}

export interface ScoutSourceHealthListResponse {
  items: ScoutSourceHealth[];
  count: number;
}

export interface EvolutionHealth {
  snapshot_id?: string | null;
  concentration_score: number;
  role_diversity_score: number;
  novelty_score: number;
  stagnation_score: number;
  explorer_pressure_score: number;
  exploration_pulse_triggered: boolean;
  created_at?: string | null;
  metrics_json: Record<string, unknown>;
}

export interface BreakerRule {
  rule_id: string;
  rule_code: string;
  description: string;
  mode: string;
  threshold_value: number;
  window_minutes: number;
  action_type: string;
  enabled: boolean;
  shadow_only: boolean;
}

export interface BreakerIncident {
  incident_id: string;
  rule_code: string;
  mode: string;
  severity: string;
  status: string;
  observed_value: number;
  threshold_value: number;
  payload: Record<string, unknown>;
  created_at: string;
  resolved_at?: string | null;
}

export interface BreakerStatusResponse {
  rules: BreakerRule[];
  incidents: BreakerIncident[];
  open_count: number;
}

export interface ActivityEntry {
  event_id: string;
  event_type: string;
  entity_id?: string | null;
  entity_type?: string | null;
  title: string;
  summary: string;
  severity: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ActivityFeedResponse {
  entries: ActivityEntry[];
  count: number;
  active_instance_count: number;
  window_minutes: number;
}

export interface EventMessage {
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
}
