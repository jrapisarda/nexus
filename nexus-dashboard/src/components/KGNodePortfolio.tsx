import { useQuery } from "@tanstack/react-query";
import { fetchKGNodeMarket, fetchNetWorth } from "../api/client";
import { ErrorPlaceholder, LoadingPlaceholder } from "./AgentPopulation";

const pnlColor = (pnl: number | null) =>
  pnl === null ? "#64748b" : pnl >= 0 ? "#10b981" : "#ef4444";

function formatCredits(v: number | null | undefined): string {
  if (v === null || v === undefined) return "-";
  return v.toFixed(2);
}

export default function KGNodePortfolio() {
  const nodesQuery = useQuery({
    queryKey: ["kg-node-market", true],
    queryFn: () => fetchKGNodeMarket(true, 100),
    refetchInterval: 15000,
  });

  const netWorthQuery = useQuery({
    queryKey: ["net-worth"],
    queryFn: fetchNetWorth,
    refetchInterval: 15000,
  });

  if (nodesQuery.isLoading) return <LoadingPlaceholder label="KG Node Portfolio" />;
  if (nodesQuery.error) return <ErrorPlaceholder label="KG Node Portfolio" error={nodesQuery.error} />;

  const ownedNodes: any[] = nodesQuery.data ?? [];
  const netWorth: any[] = netWorthQuery.data ?? [];

  // Group nodes by owner
  const byOwner: Record<string, { name: string; role: string; nodes: any[] }> = {};
  for (const node of ownedNodes) {
    if (!node.owner_persona_id) continue;
    if (!byOwner[node.owner_persona_id]) {
      byOwner[node.owner_persona_id] = {
        name: node.owner_name || "Unknown",
        role: node.owner_role || "",
        nodes: [],
      };
    }
    byOwner[node.owner_persona_id].nodes.push(node);
  }

  // Summary stats
  const totalOwned = ownedNodes.length;
  const totalValue = ownedNodes.reduce((s: number, n: any) => s + (n.current_value || 0), 0);
  const totalPnL = ownedNodes.reduce((s: number, n: any) => s + (n.unrealized_pnl || 0), 0);

  // Top net worth agents
  const topNetWorth = netWorth.filter((a: any) => a.node_value > 0).slice(0, 8);

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600 }}>KG Node Ownership</h2>
        <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
          Agents own knowledge graph nodes as real estate. Value from edge quality, centrality, and traversal yield.
        </div>
      </div>

      {/* Summary metrics */}
      <div style={{ display: "flex", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
        <MetricChip label="Nodes Owned" value={String(totalOwned)} color="#38bdf8" />
        <MetricChip label="Total Value" value={`${totalValue.toFixed(1)} cr`} color="#8b5cf6" />
        <MetricChip
          label="Unrealized P&L"
          value={`${totalPnL >= 0 ? "+" : ""}${totalPnL.toFixed(1)} cr`}
          color={totalPnL >= 0 ? "#10b981" : "#ef4444"}
        />
      </div>

      {totalOwned === 0 ? (
        <div style={{ textAlign: "center", color: "#475569", fontSize: 13, padding: "24px 0" }}>
          No agents own KG nodes yet. Agents will purchase high-centrality nodes autonomously during market cycles.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {Object.entries(byOwner).map(([pid, { name, role, nodes }]) => {
            const ownerValue = nodes.reduce((s: number, n: any) => s + (n.current_value || 0), 0);
            const ownerPnL = nodes.reduce((s: number, n: any) => s + (n.unrealized_pnl || 0), 0);
            const nwEntry = netWorth.find((a: any) => a.persona_id === pid);

            return (
              <div
                key={pid}
                style={{
                  background: "#0f172a",
                  borderRadius: 10,
                  border: "1px solid #1e293b",
                  padding: "10px 14px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <div>
                    <span style={{ fontWeight: 600, color: "#e2e8f0", fontSize: 13 }}>{name}</span>
                    <span style={{ color: "#64748b", fontSize: 11, marginLeft: 8 }}>{role}</span>
                  </div>
                  <div style={{ display: "flex", gap: 12, fontSize: 11 }}>
                    <span style={{ color: "#8b5cf6" }}>{nodes.length} node{nodes.length > 1 ? "s" : ""}</span>
                    <span style={{ color: "#94a3b8" }}>{ownerValue.toFixed(1)} cr</span>
                    <span style={{ color: pnlColor(ownerPnL), fontWeight: 600 }}>
                      {ownerPnL >= 0 ? "+" : ""}{ownerPnL.toFixed(1)}
                    </span>
                    {nwEntry && (
                      <span style={{ color: "#475569" }}>NW: {nwEntry.net_worth.toFixed(0)} cr</span>
                    )}
                  </div>
                </div>

                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {nodes.map((node: any) => (
                    <div
                      key={node.node_id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "3px 8px",
                        borderRadius: 6,
                        background: "#111827",
                        border: "1px solid #1e293b",
                        fontSize: 10,
                      }}
                    >
                      <span style={{
                        width: 6, height: 6, borderRadius: "50%",
                        background: node.confidence > 0.7 ? "#10b981" : node.confidence > 0.4 ? "#f59e0b" : "#ef4444",
                      }} />
                      <span style={{ color: "#e2e8f0", fontWeight: 500, maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {node.label}
                      </span>
                      <span style={{ color: "#64748b" }}>{node.node_type}</span>
                      <span style={{ color: "#8b5cf6" }}>{formatCredits(node.current_value)}</span>
                      <span style={{ color: pnlColor(node.unrealized_pnl), fontWeight: 600 }}>
                        {node.unrealized_pnl !== null ? (node.unrealized_pnl >= 0 ? "+" : "") + node.unrealized_pnl.toFixed(1) : ""}
                      </span>
                      {node.traversals > 0 && (
                        <span style={{ color: "#38bdf8" }}>{node.traversals} trav</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Net worth leaderboard (agents with node holdings) */}
      {topNetWorth.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Net Worth (agents with node holdings)
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 6 }}>
            {topNetWorth.map((a: any) => (
              <div
                key={a.persona_id}
                style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "4px 8px", borderRadius: 6,
                  background: "#111827", border: "1px solid #1e293b", fontSize: 11,
                }}
              >
                <span style={{ color: "#e2e8f0", fontWeight: 500 }}>{a.name.split(" ").slice(0, 2).join(" ")}</span>
                <div style={{ display: "flex", gap: 8 }}>
                  <span style={{ color: "#f59e0b" }}>{a.node_value.toFixed(0)} node</span>
                  <span style={{ color: "#38bdf8", fontWeight: 600 }}>{a.net_worth.toFixed(0)} cr</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function MetricChip({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 8, background: color + "15", border: `1px solid ${color}33` }}>
      <span style={{ fontSize: 11, color: "#94a3b8" }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 700, color }}>{value}</span>
    </div>
  );
}
