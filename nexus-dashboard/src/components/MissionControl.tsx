import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchObservatoryOverview } from "../api/client";
import { ErrorPlaceholder, LoadingPlaceholder } from "./AgentPopulation";
import SubmitObjectiveModal from "./SubmitObjectiveModal";

const metricPalette = [
  "#38bdf8",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#22c55e",
];

export default function MissionControl() {
  const [showSubmit, setShowSubmit] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["observatory-overview"],
    queryFn: fetchObservatoryOverview,
  });

  if (isLoading) return <LoadingPlaceholder label="Mission Control" />;
  if (error) return <ErrorPlaceholder label="Mission Control" error={error} />;

  const overview = data!;
  const budgetColor =
    overview.budget_utilization_pct >= 90
      ? "#ef4444"
      : overview.budget_utilization_pct >= 75
        ? "#f59e0b"
        : "#10b981";

  const topMetrics = [
    { label: "Active Objectives", value: overview.active_objectives, color: metricPalette[0] },
    { label: "Running Instances", value: overview.running_instances, color: metricPalette[1] },
    { label: "Pending Reviews", value: overview.pending_reviews, color: metricPalette[2] },
    { label: "Escalations", value: overview.escalated_objectives, color: metricPalette[3] },
  ];

  const bottomMetrics = [
    { label: "Validated 24h", value: overview.findings_validated_24h, color: metricPalette[4] },
    { label: "Objectives Closed", value: overview.objectives_completed_24h, color: metricPalette[5] },
    { label: "Review Confidence", value: overview.mean_review_confidence_24h.toFixed(3), color: "#e2e8f0" },
    { label: "Success Rate", value: `${(overview.success_rate_24h * 100).toFixed(1)}%`, color: "#cbd5e1" },
    { label: "Calls 24h", value: overview.total_calls_24h, color: "#94a3b8" },
    { label: "Active Personas", value: overview.active_personas, color: "#60a5fa" },
  ];

  return (
    <>
      <SubmitObjectiveModal open={showSubmit} onClose={() => setShowSubmit(false)} />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 16,
          marginBottom: 16,
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "#38bdf8" }}>
              Mission Control
            </div>
            <button
              onClick={() => setShowSubmit(true)}
              style={{
                background: "#0f172a",
                border: "1px solid #38bdf8",
                borderRadius: 8,
                padding: "4px 14px",
                color: "#38bdf8",
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              + Submit Objective
            </button>
          </div>
          <h2 style={{ fontSize: 24, fontWeight: 700, marginTop: 6 }}>
            Autonomous research state at a glance
          </h2>
          <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 6 }}>
            Live throughput, review health, and budget posture for the last operating day.
          </div>
        </div>
        <div
          style={{
            minWidth: 220,
            background: "linear-gradient(180deg, #0f172a 0%, #111827 100%)",
            border: "1px solid #334155",
            borderRadius: 14,
            padding: 14,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#94a3b8" }}>
            <span>Budget used</span>
            <span>{overview.budget_utilization_pct.toFixed(1)}%</span>
          </div>
          <div
            style={{
              height: 12,
              background: "#020617",
              borderRadius: 999,
              overflow: "hidden",
              marginTop: 8,
            }}
          >
            <div
              style={{
                width: `${Math.min(overview.budget_utilization_pct, 100)}%`,
                height: "100%",
                background: `linear-gradient(90deg, ${budgetColor} 0%, #f8fafc 130%)`,
              }}
            />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, fontSize: 12 }}>
            <span style={{ color: "#cbd5e1" }}>${overview.total_spend_usd.toFixed(4)} spent</span>
            <span style={{ color: "#94a3b8" }}>${overview.budget_remaining_usd.toFixed(4)} left</span>
          </div>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
          gap: 12,
          marginBottom: 14,
        }}
      >
        {topMetrics.map((metric) => (
          <MetricCard key={metric.label} label={metric.label} value={String(metric.value)} color={metric.color} strong />
        ))}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 10,
        }}
      >
        {bottomMetrics.map((metric) => (
          <MetricCard key={metric.label} label={metric.label} value={String(metric.value)} color={metric.color} />
        ))}
      </div>
    </>
  );
}

function MetricCard({
  label,
  value,
  color,
  strong = false,
}: {
  label: string;
  value: string;
  color: string;
  strong?: boolean;
}) {
  return (
    <div
      style={{
        background: "linear-gradient(180deg, #111827 0%, #0f172a 100%)",
        border: `1px solid ${color}30`,
        borderRadius: 14,
        padding: strong ? 14 : 12,
        minHeight: strong ? 92 : 80,
      }}
    >
      <div style={{ fontSize: 11, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        {label}
      </div>
      <div style={{ fontSize: strong ? 28 : 20, fontWeight: 700, color, marginTop: 10 }}>
        {value}
      </div>
    </div>
  );
}
