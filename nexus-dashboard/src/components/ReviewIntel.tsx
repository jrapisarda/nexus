import { useQuery } from "@tanstack/react-query";
import { fetchReviewIntel } from "../api/client";
import { ErrorPlaceholder, LoadingPlaceholder } from "./AgentPopulation";

const verdictColors: Record<string, string> = {
  approved: "#10b981",
  rejected: "#f59e0b",
  escalated: "#ef4444",
  approve: "#10b981",
  revise: "#38bdf8",
  reject: "#f59e0b",
};

export default function ReviewIntel() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["review-intel"],
    queryFn: fetchReviewIntel,
  });

  if (isLoading) return <LoadingPlaceholder label="Review Intel" />;
  if (error) return <ErrorPlaceholder label="Review Intel" error={error} />;

  const intel = data!;
  const queueDepth =
    (intel.finding_status_counts.pending_review ?? 0)
    + (intel.finding_status_counts.revision_requested ?? 0);

  const metricCards = [
    { label: "Approval rate", value: `${(intel.approval_rate_24h * 100).toFixed(0)}%`, color: "#10b981" },
    { label: "Mean confidence", value: intel.mean_review_confidence_24h.toFixed(3), color: "#38bdf8" },
    { label: "Queue depth", value: String(queueDepth), color: "#f59e0b" },
    { label: "High-impact pending", value: String(intel.high_impact_pending_count), color: "#ef4444" },
  ];

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600 }}>Review Intel</h2>
        <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
          Outcome quality, queue pressure, and the latest peer-review decisions.
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: 10,
          marginBottom: 14,
        }}
      >
        {metricCards.map((metric) => (
          <div
            key={metric.label}
            style={{
              borderRadius: 12,
              background: "#0f172a",
              border: `1px solid ${metric.color}25`,
              padding: 12,
            }}
          >
            <div style={{ fontSize: 11, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              {metric.label}
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, color: metric.color, marginTop: 8 }}>
              {metric.value}
            </div>
          </div>
        ))}
      </div>

      <Section label="Outcome mix">
        <ChipRow items={intel.outcome_counts} />
      </Section>

      <Section label="Reviewer verdict mix">
        <ChipRow items={intel.reviewer_verdict_counts} />
      </Section>

      <Section label="Recent outcomes">
        <div style={{ display: "grid", gap: 10 }}>
          {intel.recent_outcomes.map((outcome) => {
            const verdictColor = verdictColors[outcome.verdict] ?? "#94a3b8";
            return (
              <div
                key={`${outcome.finding_id}-${outcome.reviewed_at}`}
                style={{
                  border: "1px solid #334155",
                  background: "#0f172a",
                  borderRadius: 12,
                  padding: 12,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 12,
                    marginBottom: 6,
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 600 }}>
                    {outcome.title}
                  </div>
                  <span style={{ color: verdictColor, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                    {outcome.verdict}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: "#94a3b8", lineHeight: 1.5 }}>
                  {outcome.impact_level} • support {outcome.support_count}/{outcome.reviewer_count} • confidence {outcome.mean_confidence.toFixed(3)}
                </div>
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 6 }}>
                  round {outcome.review_round} • {formatRelativeTime(outcome.reviewed_at)}
                </div>
              </div>
            );
          })}
          {intel.recent_outcomes.length === 0 && (
            <div style={{ color: "#64748b", fontSize: 13 }}>No review outcomes recorded in the last 24 hours.</div>
          )}
        </div>
      </Section>
    </>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.08em" }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function ChipRow({ items }: { items: Record<string, number> }) {
  const entries = Object.entries(items);
  if (entries.length === 0) {
    return <div style={{ color: "#64748b", fontSize: 13 }}>No data yet.</div>;
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {entries.map(([key, value]) => (
        <div
          key={key}
          style={{
            borderRadius: 999,
            border: `1px solid ${(verdictColors[key] ?? "#334155")}55`,
            padding: "5px 10px",
            background: "#0b1220",
            fontSize: 12,
          }}
        >
          <span style={{ color: "#94a3b8", marginRight: 6 }}>{key}</span>
          <span style={{ color: verdictColors[key] ?? "#e2e8f0", fontWeight: 600 }}>{value}</span>
        </div>
      ))}
    </div>
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
