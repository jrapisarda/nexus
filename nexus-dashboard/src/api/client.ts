/** REST API client for the NEXUS Observatory. */

import type {
  PersonaListResponse,
  Persona,
  ObjectiveListResponse,
  ObjectiveDAGResponse,
  Objective,
  FileUploadResponse,
  ObjectiveCreateRequest,
  KGNode,
  KGEdge,
  KGStats,
  KGWorkbenchOverview,
  KGObjectiveSearchResult,
  KGSubgraphResponse,
  KGNodeDetail,
  KGPathResponse,
  KGEvidenceRecord,
  KGChangeFeedResponse,
  KGFindingSearchResult,
  EconomySummary,
  LedgerEntry,
  MarketActivityResponse,
  MarketInstrument,
  MarketOverview,
  MarketplaceListing,
  OrderBook,
  Position,
  SecuritiesOverview,
  ServiceContract,
  TelemetryCost,
  TelemetryPerformance,
  Trade,
  EvolutionLineageResponse,
  ActivityFeedResponse,
  ObservatoryOverview,
  AlertFeedResponse,
  ReviewIntel,
  PersonaWorkloadResponse,
  ObjectiveRadarResponse,
  ReportArtifactListResponse,
  ReportFile,
  CivilizationOverview,
  CivilizationCapabilityResponse,
  CivilizationChallengeListResponse,
  ScoutSourceHealthListResponse,
  EvolutionHealth,
  BreakerStatusResponse,
} from "../types";

const BASE = "";  // proxy handles /api -> backend

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ── Pipeline ─────────────────────────────────────────────────────────────

export function fetchPipelineStatus(): Promise<any> {
  return get<any>("/api/pipeline/status");
}

// ── KG Node Ownership ────────────────────────────────────────────────────

export function fetchKGNodeMarket(ownedOnly?: boolean, limit?: number): Promise<any[]> {
  const params = new URLSearchParams();
  if (ownedOnly) params.set("owned_only", "true");
  if (limit) params.set("limit", String(limit));
  const qs = params.toString();
  return get<any[]>(`/api/marketplace/kg-nodes${qs ? "?" + qs : ""}`);
}

export function fetchKGNodePortfolio(personaId: string): Promise<any[]> {
  return get<any[]>(`/api/marketplace/kg-nodes/portfolio/${personaId}`);
}

export function fetchNetWorth(): Promise<any[]> {
  return get<any[]>("/api/economy/net-worth");
}

// ── Agents ───────────────────────────────────────────────────────────────

export function fetchAgents(status?: string): Promise<PersonaListResponse> {
  const params = status ? `?status=${status}` : "";
  return get<PersonaListResponse>(`/api/agents${params}`);
}

export function fetchAgent(personaId: string): Promise<Persona> {
  return get<Persona>(`/api/agents/${personaId}`);
}

// ── Objectives ───────────────────────────────────────────────────────────

export function fetchObjectives(
  status?: string,
  limit = 200,
): Promise<ObjectiveListResponse> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("limit", String(limit));
  return get<ObjectiveListResponse>(`/api/objectives?${params}`);
}

export function fetchObjectiveDAG(
  objectiveId: string,
): Promise<ObjectiveDAGResponse> {
  return get<ObjectiveDAGResponse>(`/api/objectives/${objectiveId}/dag`);
}

export async function uploadFile(file: File): Promise<FileUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch("/api/files", { method: "POST", body: formData });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Upload failed (${res.status}): ${detail}`);
  }
  return res.json() as Promise<FileUploadResponse>;
}

export async function submitObjective(
  req: ObjectiveCreateRequest,
): Promise<Objective> {
  const res = await fetch("/api/objectives", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Submit failed (${res.status}): ${detail}`);
  }
  return res.json() as Promise<Objective>;
}

// ── Knowledge Graph ──────────────────────────────────────────────────────

export function fetchKGNodes(
  nodeType?: string,
  status?: string,
  limit = 500,
): Promise<KGNode[]> {
  const params = new URLSearchParams();
  if (nodeType) params.set("node_type", nodeType);
  if (status) params.set("status", status);
  params.set("limit", String(limit));
  return get<KGNode[]>(`/api/kg/nodes?${params}`);
}

export function fetchKGEdges(limit = 2000): Promise<KGEdge[]> {
  return get<KGEdge[]>(`/api/kg/edges?limit=${limit}`);
}

export function fetchKGStats(): Promise<KGStats> {
  return get<KGStats>("/api/kg/stats");
}

export function searchKGNodes(q: string, limit = 10): Promise<KGNode[]> {
  return get<KGNode[]>(`/api/kg/search?q=${encodeURIComponent(q)}&limit=${limit}`);
}

export function fetchKGObjectiveSearch(q: string, limit = 8): Promise<KGObjectiveSearchResult[]> {
  return get<KGObjectiveSearchResult[]>(`/api/kg/objectives/search?q=${encodeURIComponent(q)}&limit=${limit}`);
}

export function fetchKGFindingSearch(
  q: string,
  limit = 8,
  objectiveId?: string | null,
): Promise<KGFindingSearchResult[]> {
  const search = new URLSearchParams({ q, limit: String(limit) });
  if (objectiveId) search.set("objective_id", objectiveId);
  return get<KGFindingSearchResult[]>(`/api/kg/findings/search?${search.toString()}`);
}

export function fetchKGOverview(windowHours = 24): Promise<KGWorkbenchOverview> {
  return get<KGWorkbenchOverview>(`/api/kg/overview?window_hours=${windowHours}`);
}

export function fetchKGSubgraph(params: {
  nodeId?: string | null;
  objectiveId?: string | null;
  findingId?: string | null;
  depth?: number;
  status?: string | null;
  nodeTypes?: string[];
  relationshipTypes?: string[];
}): Promise<KGSubgraphResponse> {
  const search = new URLSearchParams();
  if (params.nodeId) search.set("node_id", params.nodeId);
  if (params.objectiveId) search.set("objective_id", params.objectiveId);
  if (params.findingId) search.set("finding_id", params.findingId);
  if (params.depth) search.set("depth", String(params.depth));
  if (params.status) search.set("status", params.status);
  for (const nodeType of params.nodeTypes ?? []) search.append("node_types", nodeType);
  for (const relType of params.relationshipTypes ?? []) search.append("relationship_types", relType);
  return get<KGSubgraphResponse>(`/api/kg/subgraph?${search}`);
}

export function fetchKGNodeDetail(nodeId: string): Promise<KGNodeDetail> {
  return get<KGNodeDetail>(`/api/kg/nodes/${nodeId}`);
}

export function fetchKGPath(
  startNodeId: string,
  endNodeId: string,
  maxDepth = 4,
): Promise<KGPathResponse> {
  return get<KGPathResponse>(
    `/api/kg/path?start_node_id=${encodeURIComponent(startNodeId)}&end_node_id=${encodeURIComponent(endNodeId)}&max_depth=${maxDepth}`,
  );
}

export function fetchKGEvidence(params: {
  nodeId?: string | null;
  edgeId?: string | null;
  objectiveId?: string | null;
  findingId?: string | null;
}): Promise<KGEvidenceRecord> {
  const search = new URLSearchParams();
  if (params.nodeId) search.set("node_id", params.nodeId);
  if (params.edgeId) search.set("edge_id", params.edgeId);
  if (params.objectiveId) search.set("objective_id", params.objectiveId);
  if (params.findingId) search.set("finding_id", params.findingId);
  return get<KGEvidenceRecord>(`/api/kg/evidence?${search}`);
}

export function fetchKGChanges(windowHours = 24): Promise<KGChangeFeedResponse> {
  return get<KGChangeFeedResponse>(`/api/kg/changes?window_hours=${windowHours}`);
}

export function fetchQuestionReports(objectiveId: string): Promise<ReportArtifactListResponse> {
  return get<ReportArtifactListResponse>(`/api/reports/questions/${objectiveId}`);
}

export function fetchReportFile(reportSlug: string): Promise<ReportFile> {
  return get<ReportFile>(`/api/reports/files/${reportSlug}`);
}

// ── Economy ──────────────────────────────────────────────────────────────

export function fetchEconomySummary(): Promise<EconomySummary> {
  return get<EconomySummary>("/api/economy/summary");
}

export function fetchLedger(limit = 100): Promise<LedgerEntry[]> {
  return get<LedgerEntry[]>(`/api/economy/ledger?limit=${limit}`);
}

export function fetchMarketplaceOverview(): Promise<MarketOverview> {
  return get<MarketOverview>("/api/marketplace/overview");
}

export function fetchMarketplaceListings(limit = 50): Promise<MarketplaceListing[]> {
  return get<MarketplaceListing[]>(`/api/marketplace/listings?limit=${limit}`);
}

export function fetchMarketplaceContracts(limit = 50): Promise<ServiceContract[]> {
  return get<ServiceContract[]>(`/api/marketplace/contracts?limit=${limit}`);
}

export function fetchMarketplaceActivity(limit = 50): Promise<MarketActivityResponse> {
  return get<MarketActivityResponse>(`/api/marketplace/activity?limit=${limit}`);
}

export function fetchSecuritiesOverview(): Promise<SecuritiesOverview> {
  return get<SecuritiesOverview>("/api/securities/overview");
}

export function fetchSecuritiesInstruments(limit = 50): Promise<MarketInstrument[]> {
  return get<MarketInstrument[]>(`/api/securities/instruments?limit=${limit}`);
}

export function fetchOrderBook(instrumentId?: string | null): Promise<OrderBook> {
  const params = instrumentId ? `?instrument_id=${instrumentId}` : "";
  return get<OrderBook>(`/api/securities/order-book${params}`);
}

export function fetchTrades(limit = 50): Promise<Trade[]> {
  return get<Trade[]>(`/api/securities/trades?limit=${limit}`);
}

export function fetchPositions(limit = 50): Promise<Position[]> {
  return get<Position[]>(`/api/securities/positions?limit=${limit}`);
}

// ── Telemetry ────────────────────────────────────────────────────────────

export function fetchTelemetryCost(): Promise<TelemetryCost> {
  return get<TelemetryCost>("/api/telemetry/cost");
}

export function fetchTelemetryPerformance(): Promise<TelemetryPerformance> {
  return get<TelemetryPerformance>("/api/telemetry/performance");
}

// ── Evolution ────────────────────────────────────────────────────────────

export function fetchEvolutionLineage(): Promise<EvolutionLineageResponse> {
  return get<EvolutionLineageResponse>("/api/evolution/lineage");
}

export function fetchObservatoryOverview(): Promise<ObservatoryOverview> {
  return get<ObservatoryOverview>("/api/observatory/overview");
}

export function fetchObservatoryAlerts(limit = 8): Promise<AlertFeedResponse> {
  return get<AlertFeedResponse>(`/api/observatory/alerts?limit=${limit}`);
}

export function fetchReviewIntel(): Promise<ReviewIntel> {
  return get<ReviewIntel>("/api/observatory/reviews");
}

export function fetchWorkload(limit = 10, windowHours = 24): Promise<PersonaWorkloadResponse> {
  return get<PersonaWorkloadResponse>(
    `/api/observatory/workload?limit=${limit}&window_hours=${windowHours}`,
  );
}

export function fetchObjectiveRadar(limit = 6): Promise<ObjectiveRadarResponse> {
  return get<ObjectiveRadarResponse>(`/api/observatory/objectives?limit=${limit}`);
}

export function fetchCivilizationOverview(): Promise<CivilizationOverview> {
  return get<CivilizationOverview>("/api/civilization/overview");
}

export function fetchCivilizationCapabilities(limit = 18): Promise<CivilizationCapabilityResponse> {
  return get<CivilizationCapabilityResponse>(`/api/civilization/capabilities?limit=${limit}`);
}

export function fetchCivilizationChallenges(limit = 20): Promise<CivilizationChallengeListResponse> {
  return get<CivilizationChallengeListResponse>(`/api/civilization/challenges?limit=${limit}`);
}

export function fetchScoutHealth(): Promise<ScoutSourceHealthListResponse> {
  return get<ScoutSourceHealthListResponse>("/api/civilization/scout-health");
}

export function fetchEvolutionHealth(): Promise<EvolutionHealth> {
  return get<EvolutionHealth>("/api/civilization/evolution");
}

export function fetchBreakerStatus(limit = 20): Promise<BreakerStatusResponse> {
  return get<BreakerStatusResponse>(`/api/civilization/breakers?limit=${limit}`);
}

export function fetchActivity(limit = 40, windowMinutes = 15): Promise<ActivityFeedResponse> {
  return get<ActivityFeedResponse>(`/api/activity?limit=${limit}&window_minutes=${windowMinutes}`);
}
