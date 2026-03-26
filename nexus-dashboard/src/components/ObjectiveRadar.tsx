import { useQuery } from "@tanstack/react-query";
import { fetchObjectiveRadar } from "../api/client";
import { useDashboardStore } from "../store";
import { ErrorPlaceholder, LoadingPlaceholder } from "./AgentPopulation";

const statusColors: Record<string, string> = {
  proposed: "#64748b",
  approved: "#38bdf8",
  active: "#38bdf8",
  in_progress: "#38bdf8",
  revision_requested: "#f59e0b",
  completed: "#10b981",
  escalated: "#ef4444",
  failed: "#ef4444",
};

export default function ObjectiveRadar() {
  const selectedObjectiveId = useDashboardStore((s) => s.selectedObjectiveId);
  const setSelectedObjectiveId = useDashboardStore((s) => s.setSelectedObjectiveId);
  const { data, isLoading, error } = useQuery({
    queryKey: ["objective-radar"],
    queryFn: () => fetchObjectiveRadar(6),
  });

  if (isLoading) return <LoadingPlaceholder label="Objective Radar" />;
  if (error) return <ErrorPlaceholder label="Objective Radar" error={error} />;

  const items = data?.items ?? [];

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
          <h2 style={{ fontSize: 16, fontWeight: 600 }}>Objective Radar</h2>
          <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
            Root objectives ranked by attention score. Click a card to focus the DAG below.
          </div>
        </div>
        <div style={{ fontSize: 12, color: "#94a3b8" }}>
          {items.length} objectives in focus
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 12,
        }}
      >
        {items.map((item) => {
          const active = selectedObjectiveId === item.objective_id;
          const color = statusColors[item.status] ?? "#94a3b8";
          return (
            <button
              key={item.objective_id}
              type="button"
              onClick={() => setSelectedObjectiveId(item.objective_id)}
              style={{
                textAlign: "left",
                background: active
                  ? "linear-gradient(180deg, #172554 0%, #0f172a 100%)"
                  : "linear-gradient(180deg, #111827 0%, #0b1220 100%)",
                border: `1px solid ${active ? "#60a5fa" : "#334155"}`,
                borderRadius: 14,
                padding: 14,
                color: "inherit",
                cursor: "pointer",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  alignItems: "flex-start",
                  marginBottom: 10,
                }}
              >
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.4 }}>
                    {item.title}
                  </div>
                  <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
                    priority {item.priority} • {item.objective_type}
                  </div>
                </div>
                <span
                  style={{
                    fontSize: 10,
                    color,
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                    fontWeight: 700,
                  }}
                >
                  {item.status}
                </span>
              </div>

              <div style={{ marginBottom: 10 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 11,
                    color: "#94a3b8",
                    marginBottom: 4,
                  }}
                >
                  <span>Subtree progress</span>
                  <span>{item.progress_pct.toFixed(1)}%</span>
                </div>
                <div
                  style={{
                    height: 8,
                    borderRadius: 999,
                    background: "#020617",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${Math.min(item.progress_pct, 100)}%`,
                      height: "100%",
                      background: `linear-gradient(90deg, ${color} 0%, #f8fafc 180%)`,
                    }}
                  />
                </div>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                  gap: 8,
                }}
              >
                <MiniMetric label="Active instances" value={String(item.active_instances)} />
                <MiniMetric label="Pending reviews" value={String(item.pending_reviews)} />
                <MiniMetric label="Validated findings" value={String(item.validated_findings)} />
                <MiniMetric label="Spend" value={`$${item.total_cost_usd.toFixed(4)}`} />
              </div>

              <div style={{ marginTop: 10, fontSize: 11, color: "#64748b" }}>
                age {formatAge(item.age_minutes)} • last activity {formatRelativeTime(item.last_activity_at)} • score {item.attention_score.toFixed(1)}
              </div>
            </button>
          );
        })}
      </div>
    </>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        background: "#020617",
        borderRadius: 10,
        border: "1px solid #1e293b",
        padding: "8px 9px",
      }}
    >
      <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

function formatAge(ageMinutes: number) {
  if (ageMinutes < 60) return `${ageMinutes}m`;
  if (ageMinutes < 1440) return `${Math.floor(ageMinutes / 60)}h`;
  return `${Math.floor(ageMinutes / 1440)}d`;
}

function formatRelativeTime(timestamp: string) {
  const deltaMs = Date.now() - new Date(timestamp).getTime();
  const deltaMinutes = Math.max(Math.floor(deltaMs / 60000), 0);
  if (deltaMinutes < 1) return "just now";
  if (deltaMinutes < 60) return `${deltaMinutes}m ago`;
  const deltaHours = Math.floor(deltaMinutes / 60);
  if (deltaHours < 24) return `${deltaHours}h ago`;
  return `${Math.floor(deltaHours / 24)}d ago`;
}
