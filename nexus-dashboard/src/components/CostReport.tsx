/** Cost Report panel: cumulative spend, per-agent cost, budget gauge. */

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
import { fetchTelemetryCost } from "../api/client";

const COLORS = [
  "#ef4444",
  "#f59e0b",
  "#3b82f6",
  "#10b981",
  "#8b5cf6",
  "#06b6d4",
  "#ec4899",
  "#14b8a6",
];

export default function CostReport() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["telemetry-cost"],
    queryFn: fetchTelemetryCost,
  });

  const agentCostData = useMemo(
    () =>
      (data?.per_agent ?? []).map((a) => ({
        name: a.persona_name.slice(0, 12),
        cost: parseFloat(a.total_cost.toFixed(4)),
        calls: a.call_count,
      })),
    [data],
  );

  if (isLoading)
    return (
      <div style={{ color: "#64748b" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Cost Report
        </h2>
        Loading...
      </div>
    );

  if (error)
    return (
      <div style={{ color: "#ef4444" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Cost Report
        </h2>
        Error: {String(error)}
      </div>
    );

  const d = data!;
  const budgetPct =
    d.budget_ceiling_usd > 0
      ? (d.total_spend_usd / d.budget_ceiling_usd) * 100
      : 0;
  const gaugeColor =
    budgetPct > 90 ? "#ef4444" : budgetPct > 70 ? "#f59e0b" : "#10b981";

  return (
    <>
      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
        Cost Report
      </h2>

      {/* Budget gauge */}
      <div style={{ marginBottom: 12 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 11,
            color: "#94a3b8",
            marginBottom: 4,
          }}
        >
          <span>
            Spent: ${d.total_spend_usd.toFixed(4)}
          </span>
          <span>
            Remaining: ${d.budget_remaining_usd.toFixed(4)}
          </span>
        </div>
        <div
          style={{
            height: 10,
            background: "#0f172a",
            borderRadius: 5,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${Math.min(budgetPct, 100)}%`,
              height: "100%",
              background: gaugeColor,
              borderRadius: 5,
              transition: "width 0.5s ease",
            }}
          />
        </div>
        <div
          style={{
            textAlign: "center",
            fontSize: 10,
            color: "#64748b",
            marginTop: 2,
          }}
        >
          {budgetPct.toFixed(1)}% of ${d.budget_ceiling_usd.toFixed(2)} budget
        </div>
      </div>

      {/* Per-agent cost bar chart */}
      <div style={{ flex: 1, minHeight: 180 }}>
        {agentCostData.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={agentCostData} margin={{ left: 0, right: 0 }}>
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
                width={55}
                tickFormatter={(v: number) => `$${v.toFixed(3)}`}
              />
              <Tooltip
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid #334155",
                  borderRadius: 4,
                  fontSize: 12,
                }}
                formatter={(value: number) => [`$${value.toFixed(4)}`, "Cost"]}
              />
              <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                {agentCostData.map((_, idx) => (
                  <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div
            style={{
              color: "#64748b",
              textAlign: "center",
              paddingTop: 40,
            }}
          >
            No cost data yet.
          </div>
        )}
      </div>
    </>
  );
}
