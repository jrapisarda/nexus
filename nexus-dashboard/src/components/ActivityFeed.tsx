/** Live activity timeline for the Observatory dashboard. */

import { useQuery } from "@tanstack/react-query";
import { fetchActivity } from "../api/client";
import { useDashboardStore } from "../store";
import type { ActivityEntry } from "../types";

const ACTIVITY_WINDOW_MINUTES = 15;

const severityColor: Record<string, string> = {
  info: "#38bdf8",
  success: "#10b981",
  warning: "#f59e0b",
  error: "#ef4444",
};

export default function ActivityFeed() {
  const wsConnected = useDashboardStore((s) => s.wsConnected);

  const { data, isLoading, error } = useQuery({
    queryKey: ["activity", ACTIVITY_WINDOW_MINUTES],
    queryFn: () => fetchActivity(40, ACTIVITY_WINDOW_MINUTES),
    refetchInterval: wsConnected ? 15_000 : 4_000,
  });

  if (isLoading) {
    return (
      <div style={{ color: "#64748b" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Live Activity
        </h2>
        Loading...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ color: "#ef4444" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Live Activity
        </h2>
        Error: {String(error)}
      </div>
    );
  }

  const entries = data?.entries ?? [];
  const activeCount = data?.active_instance_count ?? 0;
  const windowMinutes = data?.window_minutes ?? ACTIVITY_WINDOW_MINUTES;

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
          <h2 style={{ fontSize: 16, fontWeight: 600 }}>Live Activity</h2>
          <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>
            Last {windowMinutes} minutes of system events and in-flight work.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <MetricPill
            label="Active instances"
            value={String(activeCount)}
            color={activeCount > 0 ? "#10b981" : "#64748b"}
          />
          <MetricPill
            label="Feed"
            value={wsConnected ? "Live" : "Polling"}
            color={wsConnected ? "#38bdf8" : "#f59e0b"}
          />
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: 12,
          alignItems: "start",
          flex: 1,
          overflowY: "auto",
          paddingRight: 4,
        }}
      >
        {entries.map((entry) => (
          <ActivityCard key={entry.event_id} entry={entry} />
        ))}

        {entries.length === 0 && (
          <div
            style={{
              color: "#64748b",
              textAlign: "center",
              padding: "48px 0",
              gridColumn: "1 / -1",
            }}
          >
            No activity in the last {windowMinutes} minutes.
          </div>
        )}
      </div>
    </>
  );
}

function ActivityCard({ entry }: { entry: ActivityEntry }) {
  const accent = severityColor[entry.severity] ?? "#38bdf8";
  const reviewMetrics = getReviewMetrics(entry);

  return (
    <article
      style={{
        background: "linear-gradient(180deg, #0f172a 0%, #111827 100%)",
        border: `1px solid ${accent}33`,
        borderLeft: `4px solid ${accent}`,
        borderRadius: 10,
        padding: 14,
        minHeight: 112,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 12,
          marginBottom: 8,
        }}
      >
        <div>
          <div style={{ fontSize: 11, color: accent, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            {entry.event_type.replace(/_/g, " ")}
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, marginTop: 2 }}>
            {entry.title}
          </div>
        </div>
        <div style={{ fontSize: 11, color: "#94a3b8", whiteSpace: "nowrap" }}>
          {formatRelativeTime(entry.created_at)}
        </div>
      </div>

      <div style={{ fontSize: 13, color: "#cbd5e1", lineHeight: 1.5 }}>
        {entry.summary}
      </div>

      {reviewMetrics.length > 0 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            marginTop: 10,
          }}
        >
          {reviewMetrics.map((metric) => (
            <span
              key={metric.label}
              style={{
                border: "1px solid #334155",
                background: "#0b1220",
                borderRadius: 999,
                padding: "4px 8px",
                fontSize: 11,
                color: "#cbd5e1",
              }}
            >
              <span style={{ color: "#94a3b8" }}>{metric.label}:</span> {metric.value}
            </span>
          ))}
        </div>
      )}

      {typeof entry.payload.reason === "string" && (
        <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 10 }}>
          Reason: {entry.payload.reason}
        </div>
      )}
    </article>
  );
}

function MetricPill({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div
      style={{
        border: `1px solid ${color}55`,
        background: "#0f172a",
        borderRadius: 999,
        padding: "6px 10px",
        minWidth: 110,
      }}
    >
      <div style={{ fontSize: 10, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, color }}>
        {value}
      </div>
    </div>
  );
}

function formatRelativeTime(timestamp: string) {
  const deltaMs = Date.now() - new Date(timestamp).getTime();
  const deltaSeconds = Math.max(Math.floor(deltaMs / 1000), 0);

  if (deltaSeconds < 60) return `${deltaSeconds}s ago`;

  const deltaMinutes = Math.floor(deltaSeconds / 60);
  if (deltaMinutes < 60) return `${deltaMinutes}m ago`;

  const deltaHours = Math.floor(deltaMinutes / 60);
  if (deltaHours < 24) return `${deltaHours}h ago`;

  const deltaDays = Math.floor(deltaHours / 24);
  return `${deltaDays}d ago`;
}

function getReviewMetrics(entry: ActivityEntry) {
  if (entry.event_type !== "finding_reviewed") {
    return [];
  }

  const metrics: Array<{ label: string; value: string }> = [];
  const reviewerCount = entry.payload.reviewer_count ?? entry.payload.review_count;
  const approvalCount = entry.payload.approval_count;
  const supportCount = entry.payload.support_count;
  const confidence = entry.payload.mean_review_confidence ?? entry.payload.consensus_score;
  const impactLevel = entry.payload.impact_level;
  const requiredConsensus = entry.payload.required_consensus;
  const verdictBreakdown = entry.payload.verdict_breakdown;

  if (typeof supportCount === "number" && typeof reviewerCount === "number") {
    metrics.push({ label: "Support", value: `${supportCount}/${reviewerCount}` });
  }

  if (typeof approvalCount === "number" && typeof reviewerCount === "number") {
    metrics.push({ label: "Votes", value: `${approvalCount}/${reviewerCount} approve` });
  }

  if (typeof confidence === "number") {
    metrics.push({ label: "Mean confidence", value: confidence.toFixed(3) });
  }

  if (typeof impactLevel === "string") {
    metrics.push({ label: "Impact", value: impactLevel });
  }

  if (typeof requiredConsensus === "string") {
    metrics.push({ label: "Rule", value: requiredConsensus });
  }

  if (verdictBreakdown && typeof verdictBreakdown === "object") {
    const parts = Object.entries(verdictBreakdown as Record<string, unknown>)
      .filter(([, value]) => typeof value === "number")
      .map(([key, value]) => `${key} ${value}`);
    if (parts.length > 0) {
      metrics.push({ label: "Breakdown", value: parts.join(", ") });
    }
  }

  return metrics;
}
