/** Objective DAG visualization using ReactFlow. */

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
} from "reactflow";
import "reactflow/dist/style.css";

import { fetchObjectives, fetchObjectiveDAG } from "../api/client";
import { useDashboardStore } from "../store";

export default function ObjectiveDAG() {
  const selectedObjectiveId = useDashboardStore(
    (s) => s.selectedObjectiveId,
  );
  const setSelectedObjectiveId = useDashboardStore(
    (s) => s.setSelectedObjectiveId,
  );

  // Fetch all objectives to find root objectives.
  const objectivesQuery = useQuery({
    queryKey: ["objectives"],
    queryFn: () => fetchObjectives(),
  });

  // Find root objectives (those without parents).
  const rootObjectives = useMemo(() => {
    const objs = objectivesQuery.data?.objectives ?? [];
    return objs.filter((o) => !o.parent_objective_id);
  }, [objectivesQuery.data]);

  // Default to the first root objective.
  const activeRootId = selectedObjectiveId ?? rootObjectives[0]?.objective_id ?? null;

  // Fetch DAG for the selected/default root.
  const dagQuery = useQuery({
    queryKey: ["objective-dag", activeRootId],
    queryFn: () => fetchObjectiveDAG(activeRootId!),
    enabled: !!activeRootId,
  });

  const flowNodes: Node[] = useMemo(
    () =>
      (dagQuery.data?.nodes ?? []).map((n) => ({
        id: n.id,
        position: n.position,
        data: {
          label: (
            <div style={{ fontSize: 11, textAlign: "center" }}>
              <div style={{ fontWeight: 600 }}>{n.data.label}</div>
              <div
                style={{
                  marginTop: 2,
                  fontSize: 9,
                  color: n.data.color,
                  fontWeight: 500,
                }}
              >
                {n.data.status}
              </div>
            </div>
          ),
        },
        style: {
          background: "#0f172a",
          border: `2px solid ${n.data.color}`,
          borderRadius: 6,
          padding: 8,
          color: "#e2e8f0",
          maxWidth: 200,
        },
      })),
    [dagQuery.data],
  );

  const flowEdges: Edge[] = useMemo(
    () =>
      (dagQuery.data?.edges ?? []).map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label ?? undefined,
        animated: e.animated ?? false,
        style: { stroke: "#475569" },
        labelStyle: { fill: "#94a3b8", fontSize: 10 },
      })),
    [dagQuery.data],
  );

  const isLoading = objectivesQuery.isLoading || dagQuery.isLoading;
  const isError = objectivesQuery.error || dagQuery.error;

  if (isLoading)
    return (
      <div style={{ color: "#64748b" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Objective DAG
        </h2>
        Loading...
      </div>
    );

  if (isError)
    return (
      <div style={{ color: "#ef4444" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Objective DAG
        </h2>
        Error: {String(objectivesQuery.error || dagQuery.error)}
      </div>
    );

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <h2 style={{ fontSize: 16, fontWeight: 600 }}>Objective DAG</h2>
        {rootObjectives.length > 1 && (
          <select
            value={activeRootId ?? ""}
            onChange={(e) => setSelectedObjectiveId(e.target.value || null)}
            style={{
              background: "#0f172a",
              color: "#e2e8f0",
              border: "1px solid #334155",
              borderRadius: 4,
              padding: "2px 8px",
              fontSize: 12,
            }}
          >
            {rootObjectives.map((o) => (
              <option key={o.objective_id} value={o.objective_id}>
                {o.title.slice(0, 40)}
              </option>
            ))}
          </select>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 300 }}>
        {flowNodes.length > 0 ? (
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#1e293b" gap={16} />
            <Controls
              style={{ background: "#1e293b", borderRadius: 4 }}
            />
            <MiniMap
              nodeColor={() => "#3b82f6"}
              style={{ background: "#0f172a" }}
            />
          </ReactFlow>
        ) : (
          <div style={{ color: "#64748b", textAlign: "center", paddingTop: 40 }}>
            No objectives found.
          </div>
        )}
      </div>
    </>
  );
}
