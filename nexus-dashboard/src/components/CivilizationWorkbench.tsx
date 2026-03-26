import { useQuery } from "@tanstack/react-query";
import type { CSSProperties, ReactNode } from "react";

import {
  fetchBreakerStatus,
  fetchCivilizationCapabilities,
  fetchCivilizationChallenges,
  fetchCivilizationOverview,
  fetchEvolutionHealth,
  fetchScoutHealth,
} from "../api/client";
import { ErrorPlaceholder, LoadingPlaceholder } from "./AgentPopulation";

const healthColor: Record<string, string> = {
  healthy: "#10b981",
  degraded: "#f59e0b",
  critical: "#ef4444",
};

export default function CivilizationWorkbench() {
  const overview = useQuery({ queryKey: ["civilization-overview"], queryFn: fetchCivilizationOverview });
  const capabilities = useQuery({ queryKey: ["civilization-capabilities"], queryFn: () => fetchCivilizationCapabilities(12) });
  const challenges = useQuery({ queryKey: ["civilization-challenges"], queryFn: () => fetchCivilizationChallenges(8) });
  const scoutHealth = useQuery({ queryKey: ["civilization-scout-health"], queryFn: fetchScoutHealth });
  const evolution = useQuery({ queryKey: ["civilization-evolution"], queryFn: fetchEvolutionHealth });
  const breakers = useQuery({ queryKey: ["civilization-breakers"], queryFn: () => fetchBreakerStatus(10) });

  if (
    overview.isLoading ||
    capabilities.isLoading ||
    challenges.isLoading ||
    scoutHealth.isLoading ||
    evolution.isLoading ||
    breakers.isLoading
  ) {
    return <LoadingPlaceholder label="Civilization Workbench" />;
  }

  const error = overview.error || capabilities.error || challenges.error || scoutHealth.error || evolution.error || breakers.error;
  if (error) {
    return <ErrorPlaceholder label="Civilization Workbench" error={error} />;
  }

  const summary = overview.data!;
  const capabilityItems = capabilities.data?.items ?? [];
  const challengeItems = challenges.data?.items ?? [];
  const scoutItems = scoutHealth.data?.items ?? [];
  const evolutionHealth = evolution.data!;
  const breakerState = breakers.data!;

  const topCapability = capabilityItems[0];

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap", marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "#38bdf8" }}>
            Civilization Workbench
          </div>
          <h2 style={{ fontSize: 20, fontWeight: 700, marginTop: 6 }}>
            Incentives, resilience, and shadow controls
          </h2>
        </div>
        {topCapability ? (
          <div style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 12, padding: 12, minWidth: 220 }}>
            <div style={{ fontSize: 11, color: "#94a3b8", textTransform: "uppercase" }}>Top capability leader</div>
            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 6 }}>{topCapability.persona_name}</div>
            <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>{topCapability.role_class}</div>
          </div>
        ) : null}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginBottom: 14 }}>
        <MetricCard label="Gini" value={summary.wealth_gini.toFixed(3)} color="#ef4444" />
        <MetricCard label="Top Balance Share" value={`${(summary.top_balance_share * 100).toFixed(1)}%`} color="#f59e0b" />
        <MetricCard label="Role Concentration" value={`${(summary.role_concentration * 100).toFixed(1)}%`} color="#8b5cf6" />
        <MetricCard label="Pending Challenges" value={String(summary.pending_challenges)} color="#38bdf8" />
        <MetricCard label="Pending Holdbacks" value={String(summary.pending_holdbacks)} color="#22c55e" />
        <MetricCard label="Open Breakers" value={String(summary.open_breaker_incidents)} color="#ef4444" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <Panel title="Capability Leaders">
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #334155", textAlign: "left" }}>
                  <th style={thStyle}>Persona</th>
                  <th style={thStyle}>Role</th>
                  <th style={thStyle}>Rep</th>
                  <th style={thStyle}>Balance</th>
                  <th style={thStyle}>Strongest</th>
                </tr>
              </thead>
              <tbody>
                {capabilityItems.map((item) => {
                  const strongest = Object.entries(item.capability_scores).sort((a, b) => b[1] - a[1])[0];
                  return (
                    <tr key={item.persona_id} style={{ borderBottom: "1px solid #1e293b" }}>
                      <td style={tdStyle}>{item.persona_name}</td>
                      <td style={tdStyle}>{item.role_class}</td>
                      <td style={tdStyle}>{item.reputation_score.toFixed(3)}</td>
                      <td style={tdStyle}>{item.credit_balance.toFixed(2)}</td>
                      <td style={tdStyle}>{strongest ? `${strongest[0]} ${strongest[1].toFixed(2)}` : "n/a"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>

          <Panel title="Challenge Window">
            {challengeItems.length === 0 ? (
              <div style={{ color: "#64748b" }}>No active or recent challenge cases.</div>
            ) : (
              challengeItems.map((item) => (
                <div key={item.challenge_id} style={{ padding: "10px 0", borderBottom: "1px solid #1e293b" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <div style={{ fontWeight: 600 }}>{item.finding_title}</div>
                    <div style={{ color: item.status === "open" ? "#f59e0b" : "#10b981" }}>{item.status}</div>
                  </div>
                  <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
                    {item.challenger_name} • {item.flaw_type ?? "unknown flaw"} • {item.severity ?? "unknown severity"}
                  </div>
                </div>
              ))
            )}
          </Panel>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <Panel title="Scout Coverage">
            {scoutItems.map((item) => (
              <div key={item.source_name} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "8px 0", borderBottom: "1px solid #1e293b" }}>
                <div>
                  <div>{item.source_name}</div>
                  <div style={{ fontSize: 12, color: "#94a3b8" }}>
                    runs {item.total_runs} • findings {item.findings_ingested}
                  </div>
                </div>
                <div style={{ color: healthColor[item.health_status] ?? "#94a3b8", fontWeight: 600 }}>
                  {item.health_status}
                </div>
              </div>
            ))}
          </Panel>

          <Panel title="Evolution Health">
            <MetricLine label="Concentration" value={evolutionHealth.concentration_score.toFixed(3)} />
            <MetricLine label="Role diversity" value={evolutionHealth.role_diversity_score.toFixed(3)} />
            <MetricLine label="Novelty" value={evolutionHealth.novelty_score.toFixed(3)} />
            <MetricLine label="Stagnation" value={evolutionHealth.stagnation_score.toFixed(3)} />
            <MetricLine label="Explorer pressure" value={evolutionHealth.explorer_pressure_score.toFixed(3)} />
            <MetricLine label="Pulse" value={evolutionHealth.exploration_pulse_triggered ? "triggered" : "steady"} />
          </Panel>

          <Panel title="Breaker State">
            <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>
              {breakerState.open_count} open shadow incidents
            </div>
            {breakerState.incidents.slice(0, 5).map((item) => (
              <div key={item.incident_id} style={{ padding: "8px 0", borderBottom: "1px solid #1e293b" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <div>{item.rule_code}</div>
                  <div style={{ color: item.status === "open" ? "#ef4444" : "#10b981" }}>{item.status}</div>
                </div>
                <div style={{ fontSize: 12, color: "#94a3b8" }}>
                  observed {item.observed_value.toFixed(3)} / threshold {item.threshold_value.toFixed(3)}
                </div>
              </div>
            ))}
          </Panel>
        </div>
      </div>
    </>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ background: "linear-gradient(180deg, #111827 0%, #0f172a 100%)", border: "1px solid #1e293b", borderRadius: 14, padding: 14 }}>
      <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>{title}</h3>
      {children}
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ background: "#0f172a", border: `1px solid ${color}30`, borderRadius: 12, padding: 12 }}>
      <div style={{ fontSize: 11, color: "#94a3b8", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color, marginTop: 8 }}>{value}</div>
    </div>
  );
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "6px 0", borderBottom: "1px solid #1e293b", fontSize: 13 }}>
      <span style={{ color: "#94a3b8" }}>{label}</span>
      <span>{value}</span>
    </div>
  );
}

const thStyle: CSSProperties = {
  padding: "8px 10px",
  color: "#94a3b8",
  fontWeight: 600,
};

const tdStyle: CSSProperties = {
  padding: "8px 10px",
  whiteSpace: "nowrap",
};
