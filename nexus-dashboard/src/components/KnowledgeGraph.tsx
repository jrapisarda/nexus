/** Compact KG summary card for the Observatory overview tab. */

import { useQuery } from "@tanstack/react-query";
import { fetchKGOverview } from "../api/client";

export default function KnowledgeGraph() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["kg-workbench-overview", 24],
    queryFn: () => fetchKGOverview(24),
    refetchInterval: 20_000,
  });

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 600 }}>KG Pulse</h2>
          <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>
            Research memory, contestation, and report-linked graph coverage.
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            window.location.hash = "/kg";
          }}
          style={buttonStyle}
        >
          Open Workbench
        </button>
      </div>

      {isLoading && <div style={{ color: "#64748b" }}>Loading knowledge graph pulse…</div>}
      {error && <div style={{ color: "#ef4444" }}>Error: {String(error)}</div>}

      {data && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: 10,
              marginBottom: 14,
            }}
          >
            <MetricCard label="Nodes" value={data.node_count.toLocaleString()} accent="#3b82f6" />
            <MetricCard label="Edges" value={data.edge_count.toLocaleString()} accent="#8b5cf6" />
            <MetricCard label="Challenged Nodes" value={data.challenged_node_count.toLocaleString()} accent="#f59e0b" />
            <MetricCard label="Recent Changes" value={data.recent_change_count.toLocaleString()} accent="#10b981" />
            <MetricCard label="Report-Linked Nodes" value={data.report_linked_node_count.toLocaleString()} accent="#06b6d4" />
            <MetricCard label="Avg Confidence" value={data.avg_confidence.toFixed(3)} accent="#f97316" />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 14 }}>
            <div
              style={{
                background: "#0f172a",
                border: "1px solid #1e293b",
                borderRadius: 10,
                padding: 12,
                minHeight: 200,
              }}
            >
              <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>Top Objectives Touching The Graph</div>
              <div style={{ display: "grid", gap: 8 }}>
                {data.top_objectives.map((objective) => (
                  <div
                    key={objective.objective_id}
                    style={{
                      border: "1px solid #1e293b",
                      borderRadius: 8,
                      padding: 10,
                      background: "#111827",
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{objective.title}</div>
                    <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>
                      {objective.node_count} nodes • {objective.edge_count} edges • {objective.status}
                    </div>
                  </div>
                ))}
                {data.top_objectives.length === 0 && (
                  <div style={{ color: "#64748b", fontSize: 12 }}>No report-linked objectives yet.</div>
                )}
              </div>
            </div>

            <div
              style={{
                background: "linear-gradient(180deg, #0f172a 0%, #111827 100%)",
                border: "1px solid #1e293b",
                borderRadius: 10,
                padding: 12,
              }}
            >
              <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 10 }}>Why This Matters</div>
              <div style={{ fontSize: 13, color: "#cbd5e1", lineHeight: 1.6 }}>
                The workbench tab turns the graph into an evidence browser. From there you can inspect a claim, see its
                relationships, open the linked finding report, and preview the final recommendation dossier without
                losing graph context.
              </div>
              <div style={{ marginTop: 12, display: "grid", gap: 8, fontSize: 12, color: "#cbd5e1" }}>
                <div>Report-linked edges: {data.report_linked_edge_count}</div>
                <div>Challenged edges: {data.challenged_edge_count}</div>
                <div>Recent graph volatility: {data.recent_change_count} changes / 24h</div>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function MetricCard({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div
      style={{
        border: `1px solid ${accent}44`,
        borderRadius: 10,
        padding: 12,
        background: "#0f172a",
      }}
    >
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "#94a3b8" }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color: accent, marginTop: 6 }}>{value}</div>
    </div>
  );
}

const buttonStyle: React.CSSProperties = {
  border: "1px solid #38bdf8",
  background: "linear-gradient(135deg, #0f172a 0%, #172554 100%)",
  color: "#e2e8f0",
  borderRadius: 999,
  padding: "8px 14px",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};
