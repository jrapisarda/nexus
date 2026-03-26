/** Full Knowledge Graph workbench tab for epistemic exploration. */

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import ForceGraph2D from "react-force-graph-2d";
import {
  fetchKGEvidence,
  fetchKGChanges,
  fetchKGFindingSearch,
  fetchKGNodeDetail,
  fetchKGObjectiveSearch,
  fetchKGOverview,
  fetchKGPath,
  fetchKGSubgraph,
  fetchQuestionReports,
  fetchReportFile,
  searchKGNodes,
} from "../api/client";
import { useDashboardStore } from "../store";
import type {
  KGChangeItem,
  KGEdge,
  KGFindingSearchResult,
  KGNode,
  KGObjectiveSearchResult,
  ReportArtifactSummary,
} from "../types";

type DrawerTab = "details" | "evidence" | "path" | "reports" | "timeline";

type FilterPreset = {
  name: string;
  objectiveId: string;
  findingId: string;
  status: string;
  nodeType: string;
  relationshipType: string;
  depth: number;
  challengedOnly: boolean;
  acceptedOnly: boolean;
  recentChangesOnly: boolean;
  focusMode: boolean;
};

type ConnectedNeighbor = {
  nodeId: string;
  label: string;
  nodeType: string;
  status: string;
  relationshipTypes: string[];
};

type AutocompleteOption = {
  id: string;
  label: string;
  meta: string;
};

const PRESET_STORAGE_KEY = "nexus.kg.workbench.presets";

export default function KnowledgeGraphWorkbench() {
  const graphRef = useRef<any>(null);
  const canvasHostRef = useRef<HTMLDivElement | null>(null);
  const selectedObjectiveId = useDashboardStore((s) => s.selectedObjectiveId);
  const [isCompact, setIsCompact] = useState(() => window.innerWidth < 1180);
  const [canvasWidth, setCanvasWidth] = useState(0);

  const [searchText, setSearchText] = useState("");
  const deferredSearch = useDeferredValue(searchText);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [focusHistory, setFocusHistory] = useState<Array<string | null>>([]);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [pathStartNodeId, setPathStartNodeId] = useState<string | null>(null);
  const [pathEndNodeId, setPathEndNodeId] = useState<string | null>(null);
  const [selectedReportSlug, setSelectedReportSlug] = useState<string | null>(null);
  const [activeDrawerTab, setActiveDrawerTab] = useState<DrawerTab>("details");
  const [objectiveId, setObjectiveId] = useState("");
  const [objectiveSearchText, setObjectiveSearchText] = useState("");
  const [findingId, setFindingId] = useState("");
  const [findingSearchText, setFindingSearchText] = useState("");
  const [status, setStatus] = useState("");
  const [nodeType, setNodeType] = useState("");
  const [relationshipType, setRelationshipType] = useState("");
  const [depth, setDepth] = useState(2);
  const [challengedOnly, setChallengedOnly] = useState(false);
  const [acceptedOnly, setAcceptedOnly] = useState(false);
  const [recentChangesOnly, setRecentChangesOnly] = useState(false);
  const [focusMode, setFocusMode] = useState(true);
  const [savedPresets, setSavedPresets] = useState<FilterPreset[]>([]);
  const deferredObjectiveSearch = useDeferredValue(objectiveSearchText);
  const deferredFindingSearch = useDeferredValue(findingSearchText);

  useEffect(() => {
    if (selectedObjectiveId && !objectiveId) {
      setObjectiveId(selectedObjectiveId);
    }
  }, [selectedObjectiveId, objectiveId]);

  useEffect(() => {
    const onResize = () => setIsCompact(window.innerWidth < 1180);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(PRESET_STORAGE_KEY);
      if (raw) {
        setSavedPresets(JSON.parse(raw) as FilterPreset[]);
      }
    } catch {
      setSavedPresets([]);
    }
  }, []);

  useEffect(() => {
    if (!canvasHostRef.current) return;
    const element = canvasHostRef.current;
    const updateCanvasWidth = () => {
      const nextWidth = Math.max(Math.floor(element.clientWidth - 28), 320);
      setCanvasWidth((current) => (current === nextWidth ? current : nextWidth));
    };
    updateCanvasWidth();
    const observer = new ResizeObserver(updateCanvasWidth);
    observer.observe(element);
    return () => observer.disconnect();
  }, [isCompact]);

  const overviewQuery = useQuery({
    queryKey: ["kg-workbench-overview", 24],
    queryFn: () => fetchKGOverview(24),
    refetchInterval: 20_000,
  });

  const searchQuery = useQuery({
    queryKey: ["kg-search", deferredSearch],
    queryFn: () => searchKGNodes(deferredSearch, 12),
    enabled: deferredSearch.trim().length >= 1,
  });

  const objectiveScopeQuery = useQuery({
    queryKey: ["kg-objective-scope-search", deferredObjectiveSearch],
    queryFn: () => fetchKGObjectiveSearch(deferredObjectiveSearch, 8),
    enabled: deferredObjectiveSearch.trim().length >= 1,
  });

  const findingScopeQuery = useQuery({
    queryKey: ["kg-finding-scope-search", deferredFindingSearch, objectiveId],
    queryFn: () => fetchKGFindingSearch(deferredFindingSearch, 8, objectiveId || null),
    enabled: deferredFindingSearch.trim().length >= 1,
  });

  const subgraphQuery = useQuery({
    queryKey: [
      "kg-subgraph",
      focusedNodeId,
      objectiveId,
      findingId,
      depth,
      status,
      nodeType,
      relationshipType,
    ],
    queryFn: () =>
      fetchKGSubgraph({
        nodeId: focusedNodeId,
        objectiveId: objectiveId || null,
        findingId: findingId || null,
        depth,
        status: status || null,
        nodeTypes: nodeType ? [nodeType] : [],
        relationshipTypes: relationshipType ? [relationshipType] : [],
      }),
  });

  const nodeDetailQuery = useQuery({
    queryKey: ["kg-node-detail", selectedNodeId],
    queryFn: () => fetchKGNodeDetail(selectedNodeId as string),
    enabled: !!selectedNodeId,
  });

  const evidenceQuery = useQuery({
    queryKey: ["kg-evidence", selectedNodeId, selectedEdgeId, objectiveId, findingId],
    queryFn: () =>
      fetchKGEvidence(
        selectedEdgeId
          ? { edgeId: selectedEdgeId }
          : selectedNodeId
            ? { nodeId: selectedNodeId }
            : findingId
              ? { findingId }
              : objectiveId
                ? { objectiveId }
                : {},
      ),
    enabled: !!selectedNodeId || !!selectedEdgeId || !!objectiveId || !!findingId,
  });

  const pathQuery = useQuery({
    queryKey: ["kg-path", pathStartNodeId, pathEndNodeId],
    queryFn: () => fetchKGPath(pathStartNodeId as string, pathEndNodeId as string, 4),
    enabled: !!pathStartNodeId && !!pathEndNodeId,
  });

  const changesQuery = useQuery({
    queryKey: ["kg-changes", 24],
    queryFn: () => fetchKGChanges(24),
    refetchInterval: 15_000,
  });

  const questionReportsQuery = useQuery({
    queryKey: ["question-reports", objectiveId],
    queryFn: () => fetchQuestionReports(objectiveId),
    enabled: !!objectiveId,
  });

  const reportFileQuery = useQuery({
    queryKey: ["report-file", selectedReportSlug],
    queryFn: () => fetchReportFile(selectedReportSlug as string),
    enabled: !!selectedReportSlug,
  });

  const changedNodeIds = useMemo(
    () =>
      new Set(
        (changesQuery.data?.items ?? [])
          .filter((item) => item.entity_type === "kg_node" && item.entity_id)
          .map((item) => item.entity_id as string),
      ),
    [changesQuery.data],
  );

  const nodeTypeOptions = useMemo(
    () => Array.from(new Set((subgraphQuery.data?.nodes ?? []).map((node) => node.node_type))).sort(),
    [subgraphQuery.data],
  );
  const relationshipOptions = useMemo(
    () => Array.from(new Set((subgraphQuery.data?.edges ?? []).map((edge) => edge.relationship_type))).sort(),
    [subgraphQuery.data],
  );

  const objectiveScopeOptions = useMemo<AutocompleteOption[]>(
    () =>
      (objectiveScopeQuery.data ?? []).map((item: KGObjectiveSearchResult) => ({
        id: item.objective_id,
        label: item.title,
        meta: `${item.objective_type} • ${item.status}${item.impact_level ? ` • ${item.impact_level}` : ""}`,
      })),
    [objectiveScopeQuery.data],
  );

  const findingScopeOptions = useMemo<AutocompleteOption[]>(
    () =>
      (findingScopeQuery.data ?? []).map((item: KGFindingSearchResult) => ({
        id: item.finding_id,
        label: item.title,
        meta: `${item.objective_title} • ${item.status} • ${item.impact_level}`,
      })),
    [findingScopeQuery.data],
  );

  const graphData = useMemo(() => {
    const allNodes = subgraphQuery.data?.nodes ?? [];
    const allEdges = subgraphQuery.data?.edges ?? [];
    const pathNodeIds = new Set(pathQuery.data?.steps.map((step) => step.node_id) ?? []);
    const filterNodes = allNodes.filter((node) => {
      if (challengedOnly && node.challenge_count === 0 && node.status !== "contested") return false;
      if (acceptedOnly && node.status === "retracted") return false;
      if (recentChangesOnly && changedNodeIds.size > 0 && !changedNodeIds.has(node.node_id)) return false;
      return true;
    });
    const allowedIds = new Set(filterNodes.map((node) => node.node_id));
    const filterEdges = allEdges.filter((edge) => {
      if (!allowedIds.has(edge.source_node_id) || !allowedIds.has(edge.target_node_id)) return false;
      if (challengedOnly && edge.status !== "contested" && edge.status !== "refuted") return false;
      if (acceptedOnly && edge.status === "refuted") return false;
      return true;
    });
    return {
      nodes: filterNodes.map((node) => ({
        ...node,
        id: node.node_id,
        label: node.label,
        nodeType: node.node_type,
        isSelected: node.node_id === selectedNodeId,
        isPath: pathNodeIds.has(node.node_id),
      })),
      links: filterEdges.map((edge) => ({
        ...edge,
        source: edge.source_node_id,
        target: edge.target_node_id,
        id: edge.edge_id,
        isSelected: edge.edge_id === selectedEdgeId,
      })),
    };
  }, [subgraphQuery.data, selectedNodeId, selectedEdgeId, challengedOnly, acceptedOnly, recentChangesOnly, changedNodeIds, pathQuery.data]);

  const availableReports = useMemo(() => {
    if (questionReportsQuery.data?.items?.length) return questionReportsQuery.data.items;
    if (nodeDetailQuery.data?.linked_reports?.length) return nodeDetailQuery.data.linked_reports;
    return evidenceQuery.data?.reports ?? [];
  }, [questionReportsQuery.data, nodeDetailQuery.data, evidenceQuery.data]);

  const visibleNeighborNodes = useMemo(() => {
    if (!selectedNodeId) return [] as ConnectedNeighbor[];
    const nodesById = new Map(graphData.nodes.map((node) => [node.node_id, node]));
    const neighbors = new Map<string, ConnectedNeighbor>();
    for (const edge of graphData.links) {
      const sourceId = String(edge.source);
      const targetId = String(edge.target);
      if (sourceId !== selectedNodeId && targetId !== selectedNodeId) continue;
      const neighborId = sourceId === selectedNodeId ? targetId : sourceId;
      const neighborNode = nodesById.get(neighborId);
      if (!neighborNode) continue;
      const current = neighbors.get(neighborId);
      if (current) {
        if (!current.relationshipTypes.includes(edge.relationship_type)) {
          current.relationshipTypes.push(edge.relationship_type);
        }
        continue;
      }
      neighbors.set(neighborId, {
        nodeId: neighborId,
        label: neighborNode.label,
        nodeType: neighborNode.node_type,
        status: neighborNode.status,
        relationshipTypes: [edge.relationship_type],
      });
    }
    return Array.from(neighbors.values()).sort((left, right) => left.label.localeCompare(right.label));
  }, [graphData.links, graphData.nodes, selectedNodeId]);

  const focusNode = (nodeId: string) => {
    if (focusedNodeId && focusedNodeId !== nodeId) {
      setFocusHistory((current) => [...current, focusedNodeId]);
    }
    setFocusedNodeId(nodeId);
    setSelectedNodeId(nodeId);
    setSelectedEdgeId(null);
    setSelectedReportSlug(null);
    setActiveDrawerTab("details");
  };

  const handleGoBackFocus = () => {
    if (!focusHistory.length) return;
    const previousFocus = focusHistory[focusHistory.length - 1] ?? null;
    setFocusHistory((current) => current.slice(0, -1));
    setFocusedNodeId(previousFocus);
    setSelectedNodeId(previousFocus);
    setSelectedEdgeId(null);
    setActiveDrawerTab("details");
  };

  const handleClearFocus = () => {
    setFocusHistory([]);
    setFocusedNodeId(null);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setActiveDrawerTab("details");
  };

  const handleSetPathStart = (nodeId: string) => {
    setPathStartNodeId(nodeId);
    setActiveDrawerTab("path");
  };

  const handleSetPathEnd = (nodeId: string) => {
    setPathEndNodeId(nodeId);
    setActiveDrawerTab("path");
  };

  useEffect(() => {
    if (!focusedNodeId || !graphRef.current) return;
    const node = graphData.nodes.find((item) => item.id === selectedNodeId) as
      | ({ x?: number; y?: number } & (typeof graphData.nodes)[number])
      | undefined;
    const timer = window.setTimeout(() => {
      if (graphData.nodes.length > 1 && typeof graphRef.current?.zoomToFit === "function") {
        graphRef.current.zoomToFit(700, 96);
        return;
      }
      if (node && typeof node.x === "number" && typeof node.y === "number") {
        graphRef.current.centerAt(node.x, node.y, 700);
        graphRef.current.zoom(1.8, 700);
      }
    }, 80);
    return () => window.clearTimeout(timer);
  }, [focusedNodeId, selectedNodeId, graphData.nodes, graphData.links]);

  return (
    <div
      style={{
        display: isCompact ? "grid" : "flex",
        gridTemplateColumns: isCompact ? "1fr" : undefined,
        gap: 16,
        width: "100%",
        minHeight: "calc(100vh - 180px)",
        alignItems: "stretch",
        overflowX: "hidden",
      }}
    >
      <aside style={{ ...railStyle, flex: isCompact ? undefined : "0 0 280px", width: isCompact ? "100%" : 280 }}>
        <WorkbenchHeader overview={overviewQuery.data} />
        <SearchPanelV2
          searchText={searchText}
          setSearchText={setSearchText}
          results={searchQuery.data ?? []}
          isLoading={searchQuery.isFetching}
          onSelectNode={(nodeId) => {
            const selected = (searchQuery.data ?? []).find((node) => node.node_id === nodeId);
            if (selected) setSearchText(selected.label);
            focusNode(nodeId);
          }}
        />
        <FilterPanelV2
          objectiveId={objectiveId}
          setObjectiveId={setObjectiveId}
          objectiveSearchText={objectiveSearchText}
          setObjectiveSearchText={setObjectiveSearchText}
          objectiveOptions={objectiveScopeOptions}
          findingId={findingId}
          setFindingId={setFindingId}
          findingSearchText={findingSearchText}
          setFindingSearchText={setFindingSearchText}
          findingOptions={findingScopeOptions}
          status={status}
          setStatus={setStatus}
          nodeType={nodeType}
          setNodeType={setNodeType}
          relationshipType={relationshipType}
          setRelationshipType={setRelationshipType}
          depth={depth}
          setDepth={setDepth}
          challengedOnly={challengedOnly}
          setChallengedOnly={setChallengedOnly}
          acceptedOnly={acceptedOnly}
          setAcceptedOnly={setAcceptedOnly}
          recentChangesOnly={recentChangesOnly}
          setRecentChangesOnly={setRecentChangesOnly}
          focusMode={focusMode}
          setFocusMode={setFocusMode}
          nodeTypeOptions={nodeTypeOptions}
          relationshipOptions={relationshipOptions}
          savedPresets={savedPresets}
          onSavePreset={() => {
            const name = window.prompt("Preset name");
            if (!name) return;
            const preset: FilterPreset = { name, objectiveId, findingId, status, nodeType, relationshipType, depth, challengedOnly, acceptedOnly, recentChangesOnly, focusMode };
            const next = [preset, ...savedPresets].slice(0, 8);
            setSavedPresets(next);
            window.localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(next));
          }}
          onApplyPreset={(preset) => {
            setObjectiveId(preset.objectiveId);
            setFindingId(preset.findingId);
            setObjectiveSearchText("");
            setFindingSearchText("");
            setStatus(preset.status);
            setNodeType(preset.nodeType);
            setRelationshipType(preset.relationshipType);
            setDepth(preset.depth);
            setChallengedOnly(preset.challengedOnly);
            setAcceptedOnly(preset.acceptedOnly);
            setRecentChangesOnly(preset.recentChangesOnly);
            setFocusMode(preset.focusMode);
          }}
          onSelectObjective={(option) => {
            setObjectiveId(option.id);
            setObjectiveSearchText(option.label);
            setFindingId("");
            setFindingSearchText("");
          }}
          onSelectFinding={(option) => {
            setFindingId(option.id);
            setFindingSearchText(option.label);
            setObjectiveId("");
            setObjectiveSearchText("");
          }}
        />
      </aside>

      <section ref={canvasHostRef} style={{ ...canvasStyle, flex: isCompact ? undefined : "1 1 0%", width: isCompact ? "100%" : undefined }}>
        <CanvasToolbar
          selectedNodeLabel={nodeDetailQuery.data?.node.label ?? null}
          focusedNodeLabel={
            focusedNodeId
              ? graphData.nodes.find((node) => node.node_id === focusedNodeId)?.label ?? nodeDetailQuery.data?.node.label ?? null
              : null
          }
          scopeLabel={subgraphQuery.data?.scope_label ?? null}
          visibleNodeCount={graphData.nodes.length}
          visibleEdgeCount={graphData.links.length}
          neighborCount={visibleNeighborNodes.length}
          canGoBack={focusHistory.length > 0}
          canClearFocus={!!focusedNodeId}
          pathStartNodeId={pathStartNodeId}
          pathEndNodeId={pathEndNodeId}
          onGoBack={handleGoBackFocus}
          onClearFocus={handleClearFocus}
          onSetPathStart={() => selectedNodeId && handleSetPathStart(selectedNodeId)}
          onSetPathEnd={() => selectedNodeId && handleSetPathEnd(selectedNodeId)}
          onClearPath={() => {
            setPathStartNodeId(null);
            setPathEndNodeId(null);
          }}
        />
        <GraphCanvas
          graphRef={graphRef}
          width={canvasWidth}
          nodes={graphData.nodes}
          links={graphData.links}
          focusMode={focusMode}
          selectedNodeId={selectedNodeId}
          selectedEdgeId={selectedEdgeId}
          pathNodeIds={new Set(pathQuery.data?.steps.map((step) => step.node_id) ?? [])}
          onNodeClick={(nodeId) => {
            focusNode(nodeId);
          }}
          onEdgeClick={(edgeId) => {
            setSelectedEdgeId(edgeId);
            setActiveDrawerTab("evidence");
          }}
        />
      </section>

      <aside style={{ ...drawerStyle, flex: isCompact ? undefined : "0 0 380px", width: isCompact ? "100%" : 380, maxWidth: isCompact ? undefined : 380 }}>
        <DrawerTabs activeTab={activeDrawerTab} setActiveTab={setActiveDrawerTab} />
        {activeDrawerTab === "details" && (
          nodeDetailQuery.isError ? (
            <ErrorDrawer
              message={formatQueryError(nodeDetailQuery.error, "Failed to load node details.")}
            />
          ) : (
            <DetailsPanel
              detail={nodeDetailQuery.data}
              neighbors={visibleNeighborNodes}
              pathStartNodeId={pathStartNodeId}
              pathEndNodeId={pathEndNodeId}
              onFocusNeighbor={focusNode}
              onSetPathStart={handleSetPathStart}
              onSetPathEnd={handleSetPathEnd}
              onOpenReport={(slug) => {
                setSelectedReportSlug(slug);
                setActiveDrawerTab("reports");
              }}
            />
          )
        )}
        {activeDrawerTab === "evidence" && (
          evidenceQuery.isError ? (
            <ErrorDrawer
              message={formatQueryError(evidenceQuery.error, "Failed to load evidence for this scope.")}
            />
          ) : (
            <EvidencePanel
              evidence={evidenceQuery.data}
              onOpenReport={(slug) => {
                setSelectedReportSlug(slug);
                setActiveDrawerTab("reports");
              }}
            />
          )
        )}
        {activeDrawerTab === "path" && <PathPanel path={pathQuery.data} />}
        {activeDrawerTab === "reports" && (
          reportFileQuery.isError ? (
            <ErrorDrawer
              message={formatQueryError(reportFileQuery.error, "Failed to load the selected report artifact.")}
            />
          ) : (
            <ReportsPanel
              reports={availableReports}
              selectedReportSlug={selectedReportSlug}
              reportContent={reportFileQuery.data?.content ?? ""}
              onOpenReport={(slug) => setSelectedReportSlug(slug)}
            />
          )
        )}
        {activeDrawerTab === "timeline" && <TimelinePanel items={nodeDetailQuery.data?.timeline ?? changesQuery.data?.items ?? []} />}
      </aside>
    </div>
  );
}

function WorkbenchHeader({ overview }: { overview?: Awaited<ReturnType<typeof fetchKGOverview>> }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, color: "#38bdf8", letterSpacing: "0.08em", textTransform: "uppercase" }}>
        Knowledge Graph Workbench
      </div>
      <div style={{ fontSize: 14, fontWeight: 700, marginTop: 4 }}>Claim → relationship → evidence → report</div>
      {overview && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8, marginTop: 10 }}>
          <MiniMetric label="Nodes" value={overview.node_count.toLocaleString()} accent="#3b82f6" />
          <MiniMetric label="Edges" value={overview.edge_count.toLocaleString()} accent="#8b5cf6" />
          <MiniMetric label="Challenged" value={overview.challenged_node_count.toLocaleString()} accent="#f59e0b" />
          <MiniMetric label="Recent Changes" value={overview.recent_change_count.toLocaleString()} accent="#10b981" />
        </div>
      )}
    </div>
  );
}

function SearchPanel({
  searchText,
  setSearchText,
  results,
  isLoading,
  onSelectNode,
}: {
  searchText: string;
  setSearchText: (value: string) => void;
  results: KGNode[];
  isLoading: boolean;
  onSelectNode: (nodeId: string) => void;
}) {
  return (
    <section style={sectionStyle}>
      <div style={sectionTitleStyle}>Search</div>
      <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search claims, entities, concepts…" style={inputStyle} />
      <div style={{ display: "grid", gap: 6, marginTop: 10, maxHeight: 180, overflowY: "auto" }}>
        {results.map((node) => (
          <button key={node.node_id} type="button" onClick={() => onSelectNode(node.node_id)} style={resultButtonStyle}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{node.label}</div>
            <div style={{ fontSize: 10, color: "#94a3b8" }}>{node.node_type} • {node.status}</div>
          </button>
        ))}
        {searchText.trim().length >= 2 && results.length === 0 && (
          <div style={{ fontSize: 11, color: "#64748b" }}>No nodes matched.</div>
        )}
      </div>
    </section>
  );
}

function FilterPanel(props: {
  objectiveId: string;
  setObjectiveId: (value: string) => void;
  findingId: string;
  setFindingId: (value: string) => void;
  status: string;
  setStatus: (value: string) => void;
  nodeType: string;
  setNodeType: (value: string) => void;
  relationshipType: string;
  setRelationshipType: (value: string) => void;
  depth: number;
  setDepth: (value: number) => void;
  challengedOnly: boolean;
  setChallengedOnly: (value: boolean) => void;
  acceptedOnly: boolean;
  setAcceptedOnly: (value: boolean) => void;
  recentChangesOnly: boolean;
  setRecentChangesOnly: (value: boolean) => void;
  focusMode: boolean;
  setFocusMode: (value: boolean) => void;
  nodeTypeOptions: string[];
  relationshipOptions: string[];
  savedPresets: FilterPreset[];
  onSavePreset: () => void;
  onApplyPreset: (preset: FilterPreset) => void;
}) {
  return (
    <section style={sectionStyle}>
      <div style={sectionTitleStyle}>Scope And Filters</div>
      <input value={props.objectiveId} onChange={(event) => props.setObjectiveId(event.target.value)} placeholder="Objective scope UUID" style={inputStyle} />
      <input value={props.findingId} onChange={(event) => props.setFindingId(event.target.value)} placeholder="Finding scope UUID" style={inputStyle} />
      <select value={props.status} onChange={(event) => props.setStatus(event.target.value)} style={inputStyle}>
        <option value="">All statuses</option>
        <option value="validated">Validated</option>
        <option value="proposed">Proposed</option>
        <option value="contested">Contested</option>
        <option value="retracted">Retracted</option>
      </select>
      <select value={props.nodeType} onChange={(event) => props.setNodeType(event.target.value)} style={inputStyle}>
        <option value="">All node types</option>
        {props.nodeTypeOptions.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <select value={props.relationshipType} onChange={(event) => props.setRelationshipType(event.target.value)} style={inputStyle}>
        <option value="">All relationships</option>
        {props.relationshipOptions.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <label style={toggleStyle}><span>Depth</span><input type="range" min={1} max={4} value={props.depth} onChange={(event) => props.setDepth(Number(event.target.value))} /><span>{props.depth}</span></label>
      <Toggle label="Challenged only" checked={props.challengedOnly} onChange={props.setChallengedOnly} />
      <Toggle label="Accepted only" checked={props.acceptedOnly} onChange={props.setAcceptedOnly} />
      <Toggle label="Recent-changes lens" checked={props.recentChangesOnly} onChange={props.setRecentChangesOnly} />
      <Toggle label="Focus mode" checked={props.focusMode} onChange={props.setFocusMode} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
        <div style={{ fontSize: 11, color: "#94a3b8" }}>Saved filters</div>
        <button type="button" onClick={props.onSavePreset} style={smallButtonStyle}>Save current view</button>
      </div>
      <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
        {props.savedPresets.map((preset) => (
          <button key={preset.name} type="button" onClick={() => props.onApplyPreset(preset)} style={resultButtonStyle}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{preset.name}</div>
            <div style={{ fontSize: 10, color: "#94a3b8" }}>
              depth {preset.depth} • {preset.challengedOnly ? "challenged" : "all"} • {preset.focusMode ? "focus" : "atlas"}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

function SearchPanelV2({
  searchText,
  setSearchText,
  results,
  isLoading,
  onSelectNode,
}: {
  searchText: string;
  setSearchText: (value: string) => void;
  results: KGNode[];
  isLoading: boolean;
  onSelectNode: (nodeId: string) => void;
}) {
  return (
    <section style={sectionStyle}>
      <div style={sectionTitleStyle}>Search</div>
      <input
        value={searchText}
        onChange={(event) => setSearchText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && results[0]) {
            event.preventDefault();
            onSelectNode(results[0].node_id);
          }
        }}
        placeholder="Type a node label like Red Queen or Claude Code..."
        style={inputStyle}
      />
      <div style={{ display: "grid", gap: 6, marginTop: 10, maxHeight: 180, overflowY: "auto" }}>
        {results.map((node) => (
          <button key={node.node_id} type="button" onClick={() => onSelectNode(node.node_id)} style={resultButtonStyle}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{node.label}</div>
            <div style={{ fontSize: 10, color: "#94a3b8" }}>{node.node_type} • {node.status}</div>
          </button>
        ))}
        {isLoading && searchText.trim().length >= 1 && (
          <div style={{ fontSize: 11, color: "#64748b" }}>Searching labels...</div>
        )}
        {!isLoading && searchText.trim().length >= 1 && results.length === 0 && (
          <div style={{ fontSize: 11, color: "#64748b" }}>No nodes matched.</div>
        )}
      </div>
    </section>
  );
}

function FilterPanelV2(props: {
  objectiveId: string;
  setObjectiveId: (value: string) => void;
  objectiveSearchText: string;
  setObjectiveSearchText: (value: string) => void;
  objectiveOptions: AutocompleteOption[];
  findingId: string;
  setFindingId: (value: string) => void;
  findingSearchText: string;
  setFindingSearchText: (value: string) => void;
  findingOptions: AutocompleteOption[];
  status: string;
  setStatus: (value: string) => void;
  nodeType: string;
  setNodeType: (value: string) => void;
  relationshipType: string;
  setRelationshipType: (value: string) => void;
  depth: number;
  setDepth: (value: number) => void;
  challengedOnly: boolean;
  setChallengedOnly: (value: boolean) => void;
  acceptedOnly: boolean;
  setAcceptedOnly: (value: boolean) => void;
  recentChangesOnly: boolean;
  setRecentChangesOnly: (value: boolean) => void;
  focusMode: boolean;
  setFocusMode: (value: boolean) => void;
  nodeTypeOptions: string[];
  relationshipOptions: string[];
  savedPresets: FilterPreset[];
  onSavePreset: () => void;
  onApplyPreset: (preset: FilterPreset) => void;
  onSelectObjective: (option: AutocompleteOption) => void;
  onSelectFinding: (option: AutocompleteOption) => void;
}) {
  return (
    <section style={sectionStyle}>
      <div style={sectionTitleStyle}>Scope And Filters</div>
      <AutocompleteField
        label="Objective scope"
        value={props.objectiveSearchText}
        onChange={(next) => {
          props.setObjectiveSearchText(next);
          if (!next.trim()) props.setObjectiveId("");
        }}
        options={props.objectiveOptions}
        onSelect={props.onSelectObjective}
        placeholder="Type an objective title..."
        selectedId={props.objectiveId}
        emptyMessage="No objectives matched."
      />
      <AutocompleteField
        label="Finding scope"
        value={props.findingSearchText}
        onChange={(next) => {
          props.setFindingSearchText(next);
          if (!next.trim()) props.setFindingId("");
        }}
        options={props.findingOptions}
        onSelect={props.onSelectFinding}
        placeholder="Type a finding title..."
        selectedId={props.findingId}
        emptyMessage="No findings matched."
      />
      <select value={props.status} onChange={(event) => props.setStatus(event.target.value)} style={inputStyle}>
        <option value="">All statuses</option>
        <option value="validated">Validated</option>
        <option value="proposed">Proposed</option>
        <option value="contested">Contested</option>
        <option value="retracted">Retracted</option>
      </select>
      <select value={props.nodeType} onChange={(event) => props.setNodeType(event.target.value)} style={inputStyle}>
        <option value="">All node types</option>
        {props.nodeTypeOptions.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <select value={props.relationshipType} onChange={(event) => props.setRelationshipType(event.target.value)} style={inputStyle}>
        <option value="">All relationships</option>
        {props.relationshipOptions.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <label style={toggleStyle}><span>Depth</span><input type="range" min={1} max={4} value={props.depth} onChange={(event) => props.setDepth(Number(event.target.value))} /><span>{props.depth}</span></label>
      <Toggle label="Challenged only" checked={props.challengedOnly} onChange={props.setChallengedOnly} />
      <Toggle label="Accepted only" checked={props.acceptedOnly} onChange={props.setAcceptedOnly} />
      <Toggle label="Recent-changes lens" checked={props.recentChangesOnly} onChange={props.setRecentChangesOnly} />
      <Toggle label="Focus mode" checked={props.focusMode} onChange={props.setFocusMode} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
        <div style={{ fontSize: 11, color: "#94a3b8" }}>Saved filters</div>
        <button type="button" onClick={props.onSavePreset} style={smallButtonStyle}>Save current view</button>
      </div>
      <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
        {props.savedPresets.map((preset) => (
          <button key={preset.name} type="button" onClick={() => props.onApplyPreset(preset)} style={resultButtonStyle}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{preset.name}</div>
            <div style={{ fontSize: 10, color: "#94a3b8" }}>
              depth {preset.depth} • {preset.challengedOnly ? "challenged" : "all"} • {preset.focusMode ? "focus" : "atlas"}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

function AutocompleteField(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: AutocompleteOption[];
  onSelect: (option: AutocompleteOption) => void;
  placeholder: string;
  selectedId: string;
  emptyMessage: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const showResults = isOpen && props.value.trim().length >= 1;

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10, color: "#94a3b8", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {props.label}
      </div>
      <input
        value={props.value}
        onChange={(event) => {
          props.onChange(event.target.value);
          setIsOpen(true);
        }}
        onFocus={() => setIsOpen(true)}
        onBlur={() => window.setTimeout(() => setIsOpen(false), 120)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && props.options[0]) {
            event.preventDefault();
            props.onSelect(props.options[0]);
            setIsOpen(false);
          }
        }}
        placeholder={props.placeholder}
        style={inputStyle}
      />
      {props.selectedId && (
        <div style={{ fontSize: 10, color: "#64748b", marginTop: -2, marginBottom: 6 }}>
          Selected scope: {props.selectedId}
        </div>
      )}
      {showResults && (
        <div style={{ display: "grid", gap: 6, maxHeight: 160, overflowY: "auto" }}>
          {props.options.map((option) => (
            <button
              key={option.id}
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                props.onSelect(option);
                setIsOpen(false);
              }}
              style={resultButtonStyle}
            >
              <div style={{ fontSize: 12, fontWeight: 600 }}>{option.label}</div>
              <div style={{ fontSize: 10, color: "#94a3b8" }}>{option.meta}</div>
            </button>
          ))}
          {props.options.length === 0 && (
            <div style={{ fontSize: 11, color: "#64748b" }}>{props.emptyMessage}</div>
          )}
        </div>
      )}
    </div>
  );
}

function CanvasToolbar(props: {
  selectedNodeLabel: string | null;
  focusedNodeLabel: string | null;
  scopeLabel: string | null;
  visibleNodeCount: number;
  visibleEdgeCount: number;
  neighborCount: number;
  canGoBack: boolean;
  canClearFocus: boolean;
  pathStartNodeId: string | null;
  pathEndNodeId: string | null;
  onGoBack: () => void;
  onClearFocus: () => void;
  onSetPathStart: () => void;
  onSetPathEnd: () => void;
  onClearPath: () => void;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
      <div>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{props.focusedNodeLabel ?? props.selectedNodeLabel ?? "Graph canvas"}</div>
        <div style={{ fontSize: 11, color: "#94a3b8" }}>
          {props.canClearFocus ? "Focused neighborhood" : "Current scope"} • {props.scopeLabel ?? "global"} • {props.visibleNodeCount} nodes • {props.visibleEdgeCount} edges • {props.neighborCount} visible neighbors
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" onClick={props.onGoBack} disabled={!props.canGoBack} style={props.canGoBack ? smallButtonStyle : disabledButtonStyle}>Back</button>
        <button type="button" onClick={props.onClearFocus} disabled={!props.canClearFocus} style={props.canClearFocus ? ghostButtonStyle : disabledButtonStyle}>Exit node focus</button>
        <button type="button" onClick={props.onSetPathStart} style={smallButtonStyle}>Set path start</button>
        <button type="button" onClick={props.onSetPathEnd} style={smallButtonStyle}>Set path end</button>
        <button type="button" onClick={props.onClearPath} style={ghostButtonStyle}>Clear path</button>
        <span style={{ fontSize: 11, color: "#94a3b8" }}>
          {props.pathStartNodeId ? "Start locked" : "No start"} • {props.pathEndNodeId ? "End locked" : "No end"}
        </span>
      </div>
    </div>
  );
}

function GraphCanvas(props: {
  graphRef: React.RefObject<any>;
  width: number;
  nodes: Array<KGNode & { id: string; nodeType: string; isSelected: boolean; isPath: boolean }>;
  links: Array<KGEdge & { id: string; source: string; target: string; isSelected: boolean }>;
  focusMode: boolean;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  pathNodeIds: Set<string>;
  onNodeClick: (nodeId: string) => void;
  onEdgeClick: (edgeId: string) => void;
}) {
  return props.nodes.length === 0 ? (
    <div style={{ color: "#64748b", display: "grid", placeItems: "center", minHeight: 620 }}>No graph nodes match the current scope.</div>
  ) : (
    <ForceGraph2D
      ref={props.graphRef}
      graphData={{ nodes: props.nodes, links: props.links }}
      backgroundColor="#0f172a"
      width={props.width || undefined}
      height={640}
      nodeCanvasObject={(node: any, ctx, globalScale) => {
        const radius = node.isSelected ? 7 : node.isPath ? 6 : Math.max(node.confidence_score * 8, 3);
        const alpha = props.focusMode && props.selectedNodeId && !node.isSelected && !node.isPath ? 0.18 : 0.9;
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
        ctx.fillStyle = node.status === "contested" || node.challenge_count > 0 ? "#f59e0b" : colorForNodeType(node.nodeType);
        ctx.fill();
        ctx.globalAlpha = 1;
        if (globalScale > 1.4) {
          ctx.font = `${11 / globalScale}px sans-serif`;
          ctx.fillStyle = "#e2e8f0";
          ctx.textAlign = "center";
          ctx.fillText(node.label.slice(0, 26), node.x, node.y + radius + 8 / globalScale);
        }
      }}
      linkCanvasObject={(link: any, ctx) => {
        const alpha = props.focusMode && props.selectedNodeId && !link.isSelected && !props.pathNodeIds.has(String(link.source.id ?? link.source)) && !props.pathNodeIds.has(String(link.target.id ?? link.target)) ? 0.14 : 0.7;
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.moveTo(link.source.x, link.source.y);
        ctx.lineTo(link.target.x, link.target.y);
        ctx.strokeStyle = link.isSelected ? "#38bdf8" : link.status === "contested" || link.status === "refuted" ? "#f59e0b" : "#334155";
        ctx.lineWidth = link.isSelected ? 2.8 : Math.max((link.weight ?? 0.5) * 2, 0.5);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }}
      onNodeClick={(node: any) => props.onNodeClick(String(node.id))}
      onLinkClick={(link: any) => props.onEdgeClick(String(link.id))}
      warmupTicks={40}
      cooldownTicks={90}
    />
  );
}

function DrawerTabs({ activeTab, setActiveTab }: { activeTab: DrawerTab; setActiveTab: (tab: DrawerTab) => void }) {
  const tabs: DrawerTab[] = ["details", "evidence", "path", "reports", "timeline"];
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
      {tabs.map((tab) => (
        <button key={tab} type="button" onClick={() => setActiveTab(tab)} style={activeTab === tab ? activeTabStyle : inactiveTabStyle}>
          {tab}
        </button>
      ))}
    </div>
  );
}

function DetailsPanel({
  detail,
  neighbors,
  pathStartNodeId,
  pathEndNodeId,
  onFocusNeighbor,
  onSetPathStart,
  onSetPathEnd,
  onOpenReport,
}: {
  detail?: Awaited<ReturnType<typeof fetchKGNodeDetail>>;
  neighbors: ConnectedNeighbor[];
  pathStartNodeId: string | null;
  pathEndNodeId: string | null;
  onFocusNeighbor: (nodeId: string) => void;
  onSetPathStart: (nodeId: string) => void;
  onSetPathEnd: (nodeId: string) => void;
  onOpenReport: (slug: string) => void;
}) {
  if (!detail) return <EmptyDrawer message="Select a node to inspect its provenance and local inference neighborhood." />;
  return (
    <div style={drawerSectionStyle}>
      <div style={{ fontSize: 18, fontWeight: 700 }}>{detail.node.label}</div>
      <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
        {detail.node.node_type} • {detail.node.status} • confidence {detail.node.confidence_score.toFixed(3)}
      </div>
      <section style={drawerBlockStyle}>
        <div style={sectionTitleStyle}>Why NEXUS Believes This</div>
        <div style={{ fontSize: 13, color: "#cbd5e1", lineHeight: 1.6 }}>
          {detail.linked_findings.length} supporting findings, {detail.linked_citations.length} citations, and {detail.linked_reports.length} dossier artifacts point at this node.
        </div>
      </section>
      <section style={drawerBlockStyle}>
        <div style={sectionTitleStyle}>Inference Neighborhood</div>
        {Object.entries(detail.relationship_groups).map(([relation, labels]) => (
          <div key={relation} style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 12, color: "#38bdf8", textTransform: "uppercase", letterSpacing: "0.06em" }}>{relation}</div>
            <div style={{ fontSize: 13, color: "#cbd5e1" }}>{labels.join(", ") || "None"}</div>
          </div>
        ))}
      </section>
      <section style={drawerBlockStyle}>
        <div style={sectionTitleStyle}>Connected Neighbors</div>
        {neighbors.length === 0 ? (
          <div style={{ fontSize: 12, color: "#94a3b8" }}>No visible neighbors in the current graph scope.</div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {neighbors.map((neighbor) => (
              <div key={neighbor.nodeId} style={drawerCardStyle}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{neighbor.label}</div>
                <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>
                  {neighbor.nodeType} • {neighbor.status} • {neighbor.relationshipTypes.join(", ")}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                  <button type="button" onClick={() => onFocusNeighbor(neighbor.nodeId)} style={smallButtonStyle}>Open neighbor</button>
                  <button type="button" onClick={() => onSetPathStart(neighbor.nodeId)} style={smallButtonStyle}>
                    {pathStartNodeId === neighbor.nodeId ? "Path start set" : "Use as path start"}
                  </button>
                  <button type="button" onClick={() => onSetPathEnd(neighbor.nodeId)} style={ghostButtonStyle}>
                    {pathEndNodeId === neighbor.nodeId ? "Path end set" : "Use as path end"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
      <section style={drawerBlockStyle}>
        <div style={sectionTitleStyle}>Reports</div>
        <div style={{ display: "grid", gap: 6 }}>
          {detail.linked_reports.map((report) => (
            <button key={report.slug} type="button" onClick={() => onOpenReport(report.slug)} style={resultButtonStyle}>
              <div style={{ fontSize: 12, fontWeight: 600 }}>{report.title}</div>
              <div style={{ fontSize: 10, color: "#94a3b8" }}>{report.artifact_type} • {relativeTime(report.updated_at)}</div>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function EvidencePanel({ evidence, onOpenReport }: { evidence?: Awaited<ReturnType<typeof fetchKGEvidence>>; onOpenReport: (slug: string) => void }) {
  if (!evidence) return <EmptyDrawer message="Select a node or edge to inspect supporting findings, citations, and dossier files." />;
  return (
    <div style={drawerSectionStyle}>
      <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>Evidence scope: {evidence.query_type}</div>
      <div style={{ fontSize: 13, color: "#cbd5e1", marginBottom: 12 }}>
        {evidence.findings.length} findings • {evidence.citations.length} citations • {evidence.challenged_count} challenged items
      </div>
      <section style={drawerBlockStyle}>
        <div style={sectionTitleStyle}>Supporting Findings</div>
        <div style={{ display: "grid", gap: 8 }}>
          {evidence.findings.map((finding) => (
            <div key={finding.finding_id} style={drawerCardStyle}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{finding.title}</div>
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>
                {finding.objective_title} • {finding.status} • round {finding.review_round}
              </div>
            </div>
          ))}
        </div>
      </section>
      <section style={drawerBlockStyle}>
        <div style={sectionTitleStyle}>Reports</div>
        <div style={{ display: "grid", gap: 6 }}>
          {evidence.reports.map((report) => (
            <button key={report.slug} type="button" onClick={() => onOpenReport(report.slug)} style={resultButtonStyle}>
              <div style={{ fontSize: 12, fontWeight: 600 }}>{report.title}</div>
              <div style={{ fontSize: 10, color: "#94a3b8" }}>{report.artifact_type}</div>
            </button>
          ))}
        </div>
      </section>
      <section style={drawerBlockStyle}>
        <div style={sectionTitleStyle}>Citations</div>
        <div style={{ display: "grid", gap: 8 }}>
          {evidence.citations.map((citation, index) => (
            <div key={`${citation.url}-${index}`} style={drawerCardStyle}>
              <div style={{ fontSize: 12, fontWeight: 600 }}>{citation.title}</div>
              <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 4 }}>{citation.source_name || citation.source_type || "Source"}</div>
              {citation.url && <a href={citation.url} target="_blank" rel="noreferrer" style={linkStyle}>{citation.url}</a>}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function PathPanel({ path }: { path?: Awaited<ReturnType<typeof fetchKGPath>> }) {
  if (!path) return <EmptyDrawer message="Set a path start and end from selected nodes to ask how NEXUS connects them." />;
  if (!path.found) return <EmptyDrawer message="No path found between the selected nodes inside the current graph." />;
  return (
    <div style={drawerSectionStyle}>
      <div style={sectionTitleStyle}>How NEXUS Connects These Nodes</div>
      <div style={{ display: "grid", gap: 8 }}>
        {path.steps.map((step) => (
          <div key={`${step.node_id}-${step.depth}`} style={drawerCardStyle}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{step.label}</div>
            <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>
              depth {step.depth} • {step.node_type} • confidence {step.confidence.toFixed(3)}
            </div>
            {step.edge_type && (
              <div style={{ fontSize: 11, color: "#38bdf8", marginTop: 4 }}>
                via {step.edge_type} • weight {step.edge_weight?.toFixed(2)}
              </div>
            )}
          </div>
        ))}
      </div>
      <section style={drawerBlockStyle}>
        <div style={sectionTitleStyle}>Supporting Findings</div>
        <div style={{ display: "grid", gap: 8 }}>
          {path.evidence.map((finding) => (
            <div key={finding.finding_id} style={drawerCardStyle}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{finding.title}</div>
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>{finding.objective_title} • {finding.status}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function ReportsPanel({
  reports,
  selectedReportSlug,
  reportContent,
  onOpenReport,
}: {
  reports: ReportArtifactSummary[];
  selectedReportSlug: string | null;
  reportContent: string;
  onOpenReport: (slug: string) => void;
}) {
  return (
    <div style={drawerSectionStyle}>
      <div style={sectionTitleStyle}>Dossier Files</div>
      <div style={{ display: "grid", gap: 6, marginBottom: 12, minWidth: 0 }}>
        {reports.map((report) => (
          <button key={report.slug} type="button" onClick={() => onOpenReport(report.slug)} style={selectedReportSlug === report.slug ? activeResultButtonStyle : resultButtonStyle}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{report.title}</div>
            <div style={{ fontSize: 10, color: "#94a3b8" }}>{report.artifact_type} • {relativeTime(report.updated_at)}</div>
          </button>
        ))}
      </div>
      <div
        style={{
          ...drawerCardStyle,
          whiteSpace: "pre-wrap",
          fontFamily: "Consolas, monospace",
          fontSize: 11,
          lineHeight: 1.5,
          minHeight: 320,
          overflowX: "auto",
        }}
      >
        {reportContent || "Select a dossier artifact to preview it here."}
      </div>
    </div>
  );
}

function TimelinePanel({ items }: { items: KGChangeItem[] }) {
  if (!items.length) return <EmptyDrawer message="No recent KG changes for this scope." />;
  return (
    <div style={drawerSectionStyle}>
      <div style={sectionTitleStyle}>Confidence Timeline And Changes</div>
      <div style={{ display: "grid", gap: 8 }}>
        {items.map((item) => (
          <div key={item.event_id} style={drawerCardStyle}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{item.title}</div>
            <div style={{ fontSize: 11, color: "#cbd5e1", marginTop: 4 }}>{item.summary}</div>
            <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 6 }}>{relativeTime(item.created_at)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyDrawer({ message }: { message: string }) {
  return <div style={{ color: "#64748b", fontSize: 13, lineHeight: 1.7, paddingTop: 8 }}>{message}</div>;
}

function ErrorDrawer({ message }: { message: string }) {
  return (
    <div style={{ ...drawerCardStyle, border: "1px solid #7f1d1d", background: "#1f1115", color: "#fecaca" }}>
      {message}
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (next: boolean) => void }) {
  return (
    <label style={toggleStyle}>
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

function MiniMetric({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div style={{ border: `1px solid ${accent}44`, borderRadius: 10, padding: 10, background: "#0b1220" }}>
      <div style={{ fontSize: 10, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: accent, marginTop: 6 }}>{value}</div>
    </div>
  );
}

function colorForNodeType(nodeType: string) {
  return ({
    entity: "#3b82f6",
    concept: "#8b5cf6",
    finding: "#10b981",
    hypothesis: "#f59e0b",
    evidence: "#06b6d4",
    policy: "#ec4899",
    mechanism: "#f97316",
  } as Record<string, string>)[nodeType] ?? "#94a3b8";
}

function relativeTime(timestamp: string) {
  const deltaMs = Date.now() - new Date(timestamp).getTime();
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatQueryError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
}

const railStyle: React.CSSProperties = { background: "#111827", border: "1px solid #1e293b", borderRadius: 12, padding: 14, overflowY: "auto", minWidth: 0, minHeight: 0 };
const canvasStyle: React.CSSProperties = { background: "#111827", border: "1px solid #1e293b", borderRadius: 12, padding: 14, minWidth: 0, minHeight: 0, overflow: "hidden", position: "relative", isolation: "isolate" };
const drawerStyle: React.CSSProperties = { background: "#111827", border: "1px solid #1e293b", borderRadius: 12, padding: 14, overflowY: "auto", minWidth: 0, minHeight: 0, position: "relative", zIndex: 1 };
const sectionStyle: React.CSSProperties = { background: "#0f172a", border: "1px solid #1e293b", borderRadius: 10, padding: 12, marginBottom: 12 };
const sectionTitleStyle: React.CSSProperties = { fontSize: 11, color: "#38bdf8", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 };
const inputStyle: React.CSSProperties = { width: "100%", borderRadius: 8, border: "1px solid #334155", background: "#020617", color: "#e2e8f0", padding: "8px 10px", fontSize: 12, marginBottom: 8 };
const toggleStyle: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, color: "#cbd5e1", marginBottom: 8, gap: 10 };
const resultButtonStyle: React.CSSProperties = { border: "1px solid #1e293b", background: "#111827", color: "#e2e8f0", borderRadius: 8, padding: 10, textAlign: "left", cursor: "pointer", minWidth: 0, maxWidth: "100%", whiteSpace: "normal", overflowWrap: "anywhere", wordBreak: "break-word" };
const activeResultButtonStyle: React.CSSProperties = { ...resultButtonStyle, border: "1px solid #38bdf8", background: "#0f172a" };
const smallButtonStyle: React.CSSProperties = { border: "1px solid #334155", background: "#020617", color: "#e2e8f0", borderRadius: 999, padding: "6px 10px", fontSize: 11, fontWeight: 600, cursor: "pointer" };
const ghostButtonStyle: React.CSSProperties = { ...smallButtonStyle, border: "1px solid #475569", background: "#111827" };
const disabledButtonStyle: React.CSSProperties = { ...smallButtonStyle, border: "1px solid #1e293b", background: "#0f172a", color: "#475569", cursor: "not-allowed" };
const activeTabStyle: React.CSSProperties = { border: "1px solid #38bdf8", background: "#0f172a", color: "#e2e8f0", borderRadius: 999, padding: "6px 12px", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", cursor: "pointer" };
const inactiveTabStyle: React.CSSProperties = { ...activeTabStyle, border: "1px solid #334155", color: "#94a3b8" };
const drawerSectionStyle: React.CSSProperties = { display: "grid", gap: 12, minWidth: 0 };
const drawerBlockStyle: React.CSSProperties = { background: "#0f172a", border: "1px solid #1e293b", borderRadius: 10, padding: 12, minWidth: 0, maxWidth: "100%", overflowX: "hidden" };
const drawerCardStyle: React.CSSProperties = { border: "1px solid #1e293b", borderRadius: 8, padding: 10, background: "#111827", minWidth: 0, maxWidth: "100%", overflowWrap: "anywhere", wordBreak: "break-word" };
const linkStyle: React.CSSProperties = { display: "block", marginTop: 6, color: "#38bdf8", fontSize: 11, wordBreak: "break-word", overflowWrap: "anywhere" };
