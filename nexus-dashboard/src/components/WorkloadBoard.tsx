import { useQuery } from "@tanstack/react-query";
import { fetchWorkload } from "../api/client";
import { ErrorPlaceholder, LoadingPlaceholder } from "./AgentPopulation";

const roleColors: Record<string, string> = {
  researcher: "#38bdf8",
  scout: "#10b981",
  synthesizer: "#8b5cf6",
  analyst: "#f59e0b",
  critic: "#ef4444",
};

export default function WorkloadBoard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["workload-board"],
    queryFn: () => fetchWorkload(10, 24),
  });

  if (isLoading) return <LoadingPlaceholder label="Workload Board" />;
  if (error) return <ErrorPlaceholder label="Workload Board" error={error} />;

  const workload = data!;

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600 }}>Workload Board</h2>
        <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
          Who is carrying current load, how fast they are moving, and what they cost.
        </div>
      </div>

      <div style={{ display: "grid", gap: 10 }}>
        {workload.items.map((item) => {
          const roleColor = roleColors[item.role_class] ?? "#94a3b8";
          return (
            <article
              key={item.persona_id}
              style={{
                borderRadius: 12,
                border: "1px solid #334155",
                background: "linear-gradient(180deg, #0f172a 0%, #111827 100%)",
                padding: 12,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  alignItems: "flex-start",
                }}
              >
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>{item.persona_name}</div>
                  <div style={{ fontSize: 12, color: roleColor, marginTop: 3 }}>
                    {item.role_class}
                  </div>
                </div>
                <div
                  style={{
                    borderRadius: 999,
                    background: "#020617",
                    border: "1px solid #334155",
                    padding: "4px 8px",
                    fontSize: 11,
                    color: "#cbd5e1",
                  }}
                >
                  {item.running_instances} running • {item.pending_instances} pending
                </div>
              </div>

              {item.current_assignment && (
                <div style={{ fontSize: 12, color: "#cbd5e1", marginTop: 8 }}>
                  {item.current_assignment}
                  <span style={{ color: "#64748b" }}>
                    {" "}({item.current_assignment_status ?? "idle"})
                  </span>
                </div>
              )}

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
                  gap: 8,
                  marginTop: 10,
                }}
              >
                <MiniMetric label="Done 24h" value={String(item.completed_24h)} />
                <MiniMetric label="Failed 24h" value={String(item.failed_24h)} />
                <MiniMetric label="Avg latency" value={`${Math.round(item.avg_latency_ms_24h)}ms`} />
                <MiniMetric label="Spend 24h" value={`$${item.spend_24h.toFixed(4)}`} />
              </div>

              <div style={{ marginTop: 10 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 11,
                    color: "#94a3b8",
                    marginBottom: 4,
                  }}
                >
                  <span>Success rate</span>
                  <span>{(item.success_rate_24h * 100).toFixed(0)}%</span>
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
                      width: `${Math.min(item.success_rate_24h * 100, 100)}%`,
                      height: "100%",
                      background: `linear-gradient(90deg, ${roleColor} 0%, #f8fafc 160%)`,
                    }}
                  />
                </div>
              </div>
            </article>
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
