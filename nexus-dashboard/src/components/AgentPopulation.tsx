/** Agent Population hero table -- shows all personas with fitness/balance/status. */

import { useQuery } from "@tanstack/react-query";
import { fetchAgents } from "../api/client";
import type { Persona } from "../types";

const statusColor: Record<string, string> = {
  active: "#10b981",
  deprecated: "#6b7280",
};

const assignmentStatusColor: Record<string, string> = {
  running: "#38bdf8",
  pending: "#f59e0b",
  completed: "#10b981",
};

const roleColor: Record<string, string> = {
  scout: "#3b82f6",
  analyst: "#8b5cf6",
  critic: "#f59e0b",
  integrator: "#10b981",
  red_team: "#ef4444",
};

export default function AgentPopulation() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents"],
    queryFn: () => fetchAgents(),
  });

  if (isLoading) return <LoadingPlaceholder label="Agent Population" />;
  if (error) return <ErrorPlaceholder label="Agent Population" error={error} />;

  const personas = data?.personas ?? [];

  return (
    <>
      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
        Agent Population ({personas.length})
      </h2>
      <div style={{ overflowX: "auto", flex: 1 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #334155", textAlign: "left" }}>
              <th style={thStyle}>Name</th>
              <th style={thStyle}>Role</th>
              <th style={thStyle}>Gen</th>
              <th style={thStyle}>Balance</th>
              <th style={thStyle}>Reputation</th>
              <th style={thStyle}>Capability</th>
              <th style={thStyle}>Status</th>
              <th style={thStyle}>Assignment</th>
            </tr>
          </thead>
          <tbody>
            {personas.map((p: Persona) => (
              <tr key={p.persona_id} style={{ borderBottom: "1px solid #1e293b" }}>
                <td style={tdStyle}>{p.persona_name}</td>
                <td style={tdStyle}>
                  <span
                    style={{
                      color: roleColor[p.role_class] ?? "#94a3b8",
                      fontWeight: 500,
                    }}
                  >
                    {p.role_class}
                  </span>
                </td>
                <td style={tdStyle}>{p.generation}</td>
                <td style={tdStyle}>{p.credit_balance.toFixed(2)}</td>
                <td style={tdStyle}>{p.reputation_score.toFixed(3)}</td>
                <td style={tdStyle}>{strongestCapability(p.capability_scores)}</td>
                <td style={tdStyle}>
                  <span
                    style={{
                      color: statusColor[p.status] ?? "#94a3b8",
                      fontWeight: 500,
                    }}
                  >
                    {p.status}
                    {p.probation_until ? " • probation" : ""}
                  </span>
                </td>
                <td style={tdStyle}>
                  {p.current_assignment ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <span title={p.current_assignment}>
                        {truncate(p.current_assignment, 56)}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          color: assignmentStatusColor[p.current_assignment_status ?? ""] ?? "#94a3b8",
                        }}
                      >
                        {humanizeAssignment(p.current_assignment_status)}
                        {p.current_assignment_started_at
                          ? ` • ${formatRelativeTime(p.current_assignment_started_at)}`
                          : ""}
                      </span>
                    </div>
                  ) : (
                <span style={{ color: "#64748b" }}>Idle</span>
                  )}
                </td>
              </tr>
            ))}
            {personas.length === 0 && (
              <tr>
                <td colSpan={8} style={{ ...tdStyle, textAlign: "center", color: "#64748b" }}>
                  No agents found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ── shared styles & helpers ──────────────────────────────────────────────

const thStyle: React.CSSProperties = {
  padding: "8px 12px",
  fontWeight: 600,
  color: "#94a3b8",
  whiteSpace: "nowrap",
};

const tdStyle: React.CSSProperties = {
  padding: "6px 12px",
  whiteSpace: "nowrap",
};

function LoadingPlaceholder({ label }: { label: string }) {
  return (
    <div style={{ color: "#64748b" }}>
      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{label}</h2>
      Loading...
    </div>
  );
}

function ErrorPlaceholder({ label, error }: { label: string; error: unknown }) {
  return (
    <div style={{ color: "#ef4444" }}>
      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{label}</h2>
      Error: {String(error)}
    </div>
  );
}

function truncate(value: string, maxLength: number) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 3)}...`;
}

function strongestCapability(capabilities?: Record<string, number> | null) {
  if (!capabilities) return "n/a";
  const entry = Object.entries(capabilities).sort((a, b) => b[1] - a[1])[0];
  return entry ? `${entry[0]} ${entry[1].toFixed(2)}` : "n/a";
}

function humanizeAssignment(status?: string | null) {
  if (!status) return "idle";
  return status.replace("_", " ");
}

function formatRelativeTime(timestamp: string) {
  const deltaMs = Date.now() - new Date(timestamp).getTime();
  const deltaSeconds = Math.max(Math.floor(deltaMs / 1000), 0);

  if (deltaSeconds < 60) return `${deltaSeconds}s ago`;

  const deltaMinutes = Math.floor(deltaSeconds / 60);
  if (deltaMinutes < 60) return `${deltaMinutes}m ago`;

  const deltaHours = Math.floor(deltaMinutes / 60);
  if (deltaHours < 24) return `${deltaHours}h ago`;

  return `${Math.floor(deltaHours / 24)}d ago`;
}

export { LoadingPlaceholder, ErrorPlaceholder };
