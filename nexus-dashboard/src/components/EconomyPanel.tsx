/** Economy panel: balance distribution, Gini coefficient, credit circulation. */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { fetchEconomySummary, fetchAgents } from "../api/client";

const COLORS = [
  "#3b82f6",
  "#8b5cf6",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#06b6d4",
  "#ec4899",
  "#14b8a6",
];

export default function EconomyPanel() {
  const summaryQuery = useQuery({
    queryKey: ["economy-summary"],
    queryFn: fetchEconomySummary,
  });
  const agentsQuery = useQuery({
    queryKey: ["agents"],
    queryFn: () => fetchAgents(),
  });

  const balanceData = useMemo(() => {
    const personas = agentsQuery.data?.personas ?? [];
    return personas
      .filter((p) => p.status === "active")
      .sort((a, b) => b.credit_balance - a.credit_balance)
      .map((p) => ({
        name: p.persona_name.slice(0, 12),
        balance: p.credit_balance,
      }));
  }, [agentsQuery.data]);

  const isLoading = summaryQuery.isLoading || agentsQuery.isLoading;
  const isError = summaryQuery.error || agentsQuery.error;

  if (isLoading)
    return (
      <div style={{ color: "#64748b" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Economy
        </h2>
        Loading...
      </div>
    );

  if (isError)
    return (
      <div style={{ color: "#ef4444" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Economy
        </h2>
        Error: {String(summaryQuery.error || agentsQuery.error)}
      </div>
    );

  const s = summaryQuery.data!;

  return (
    <>
      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Economy</h2>

      {/* Key metrics */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr 1fr",
          gap: 8,
          marginBottom: 12,
        }}
      >
        <MetricCard label="Gini" value={s.gini_coefficient.toFixed(3)} />
        <MetricCard label="Net Credits" value={s.net_credits_in_system.toFixed(0)} />
        <MetricCard label="Minted" value={s.total_credits_minted.toFixed(0)} />
        <MetricCard label="Rent Collected" value={s.total_rent_collected.toFixed(0)} />
      </div>

      {/* Balance distribution bar chart */}
      <div style={{ flex: 1, minHeight: 180 }}>
        {balanceData.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={balanceData} margin={{ left: 0, right: 0 }}>
              <XAxis
                dataKey="name"
                tick={{ fill: "#94a3b8", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#94a3b8", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                width={50}
              />
              <Tooltip
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid #334155",
                  borderRadius: 4,
                  fontSize: 12,
                }}
              />
              <Bar dataKey="balance" radius={[4, 4, 0, 0]}>
                {balanceData.map((_, idx) => (
                  <Cell
                    key={idx}
                    fill={COLORS[idx % COLORS.length]}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ color: "#64748b", textAlign: "center", paddingTop: 40 }}>
            No balance data.
          </div>
        )}
      </div>
    </>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        background: "#0f172a",
        borderRadius: 6,
        padding: "8px 10px",
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 10, color: "#64748b", marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 16, fontWeight: 700 }}>{value}</div>
    </div>
  );
}
