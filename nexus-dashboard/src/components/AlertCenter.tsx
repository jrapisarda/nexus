import { useQuery } from "@tanstack/react-query";
import { fetchObservatoryAlerts } from "../api/client";
import { ErrorPlaceholder, LoadingPlaceholder } from "./AgentPopulation";

const severityColors: Record<string, string> = {
  critical: "#ef4444",
  warning: "#f59e0b",
  info: "#38bdf8",
};

export default function AlertCenter() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["observatory-alerts"],
    queryFn: () => fetchObservatoryAlerts(8),
  });

  if (isLoading) return <LoadingPlaceholder label="Alert Center" />;
  if (error) return <ErrorPlaceholder label="Alert Center" error={error} />;

  const alerts = data?.alerts ?? [];

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 600 }}>Alert Center</h2>
          <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
            Derived operational alerts for budget pressure, stalled work, and review bottlenecks.
          </div>
        </div>
        <div style={{ fontSize: 12, color: "#cbd5e1" }}>
          {alerts.length === 0 ? "Quiet system" : `${alerts.length} active alerts`}
        </div>
      </div>

      {alerts.length === 0 ? (
        <div
          style={{
            border: "1px solid #334155",
            borderRadius: 12,
            padding: 18,
            color: "#94a3b8",
            background: "#0f172a",
          }}
        >
          No derived alerts right now. The system is operating inside the current thresholds.
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: 12,
          }}
        >
          {alerts.map((alert) => {
            const color = severityColors[alert.severity] ?? "#38bdf8";
            return (
              <article
                key={alert.alert_id}
                style={{
                  background: "linear-gradient(180deg, #111827 0%, #0b1220 100%)",
                  border: `1px solid ${color}35`,
                  borderLeft: `4px solid ${color}`,
                  borderRadius: 12,
                  padding: 14,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 12,
                    marginBottom: 8,
                  }}
                >
                  <span
                    style={{
                      color,
                      textTransform: "uppercase",
                      fontSize: 10,
                      letterSpacing: "0.08em",
                      fontWeight: 700,
                    }}
                  >
                    {alert.severity}
                  </span>
                  <span style={{ fontSize: 11, color: "#94a3b8" }}>
                    {formatRelativeTime(alert.detected_at)}
                  </span>
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                  {alert.title}
                </div>
                <div style={{ fontSize: 13, color: "#cbd5e1", lineHeight: 1.5 }}>
                  {alert.summary}
                </div>
                {typeof alert.metric_value === "number" && alert.metric_label && (
                  <div
                    style={{
                      marginTop: 12,
                      display: "inline-flex",
                      gap: 6,
                      borderRadius: 999,
                      background: "#020617",
                      border: "1px solid #334155",
                      padding: "4px 9px",
                      fontSize: 11,
                    }}
                  >
                    <span style={{ color: "#94a3b8" }}>{alert.metric_label}</span>
                    <span style={{ color: "#e2e8f0", fontWeight: 600 }}>{formatMetric(alert.metric_value)}</span>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </>
  );
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

function formatMetric(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}
