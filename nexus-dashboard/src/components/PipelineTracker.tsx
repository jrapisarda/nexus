import { useQuery } from "@tanstack/react-query";
import { fetchPipelineStatus } from "../api/client";
import { ErrorPlaceholder, LoadingPlaceholder } from "./AgentPopulation";

const STAGE_META: Record<string, { label: string; color: string; icon: string }> = {
  citation_checking: { label: "Checking Citations", color: "#f59e0b", icon: "..." },
  awaiting_review:   { label: "Awaiting Review",    color: "#38bdf8", icon: "..." },
  reviewing:         { label: "Under Review",       color: "#8b5cf6", icon: "..." },
  revision_requested:{ label: "Revision Needed",    color: "#ef4444", icon: "..." },
  validated:         { label: "Validated",           color: "#10b981", icon: "..." },
  challenged:        { label: "Challenged",          color: "#f97316", icon: "..." },
  escalated:         { label: "Escalated",           color: "#ef4444", icon: "..." },
};

function formatAge(secs: number): string {
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
  return `${Math.floor(secs / 86400)}d`;
}

function StageBadge({ stage }: { stage: string }) {
  const meta = STAGE_META[stage] || { label: stage, color: "#64748b", icon: "?" };
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        background: meta.color + "22",
        color: meta.color,
        border: `1px solid ${meta.color}44`,
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: meta.color,
          animation: stage === "citation_checking" || stage === "reviewing" ? "pulse 1.5s infinite" : undefined,
        }}
      />
      {meta.label}
    </span>
  );
}

function CitationScoreBadge({ score }: { score: number | null }) {
  if (score === null || score === undefined) return null;
  const color = score >= 0.7 ? "#10b981" : score >= 0.4 ? "#f59e0b" : "#ef4444";
  return (
    <span style={{ fontSize: 10, color, fontWeight: 600 }}>
      CIT {(score * 100).toFixed(0)}%
    </span>
  );
}

function StageProgress({ counts }: { counts: Record<string, number> }) {
  const stages = [
    { key: "citation_checking", label: "Citations", color: "#f59e0b" },
    { key: "pending_review", label: "Review", color: "#38bdf8" },
    { key: "revision_requested", label: "Revision", color: "#ef4444" },
  ];
  const total = stages.reduce((s, st) => s + (counts[st.key] || 0), 0);

  return (
    <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
      {stages.map((st) => {
        const count = counts[st.key] || 0;
        return (
          <div key={st.key} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 8, height: 8, borderRadius: "50%",
                background: count > 0 ? st.color : "#334155",
              }}
            />
            <span style={{ fontSize: 11, color: count > 0 ? "#e2e8f0" : "#475569" }}>
              {st.label}
            </span>
            <span style={{ fontSize: 13, fontWeight: 700, color: count > 0 ? st.color : "#475569" }}>
              {count}
            </span>
          </div>
        );
      })}
      <span style={{ fontSize: 11, color: "#64748b", marginLeft: 8 }}>
        {total} in pipeline
      </span>
    </div>
  );
}

export default function PipelineTracker() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["pipeline-status"],
    queryFn: fetchPipelineStatus,
    refetchInterval: 5000,
  });

  if (isLoading) return <LoadingPlaceholder label="Pipeline Tracker" />;
  if (error) return <ErrorPlaceholder label="Pipeline Tracker" error={error} />;

  const { pipeline, active_agents, recent_completed, pending_integration, stage_counts } = data!;

  return (
    <>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h2 style={{ fontSize: 16, fontWeight: 600 }}>Pipeline Tracker</h2>
            {active_agents.length > 0 && (
              <span style={{ fontSize: 10, fontWeight: 600, color: "#10b981", letterSpacing: "0.08em", textTransform: "uppercase" }}>
                {active_agents.length} agent{active_agents.length > 1 ? "s" : ""} working
              </span>
            )}
            {active_agents.length === 0 && pipeline.length > 0 && (
              <span style={{ fontSize: 10, fontWeight: 600, color: "#f59e0b", letterSpacing: "0.08em", textTransform: "uppercase" }}>
                idle — no agents running
              </span>
            )}
            {active_agents.length === 0 && pipeline.length === 0 && (
              <span style={{ fontSize: 10, fontWeight: 600, color: "#64748b", letterSpacing: "0.08em", textTransform: "uppercase" }}>
                pipeline empty
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
            Real-time finding workflow: citation check, peer review, verdict.
          </div>
        </div>
        {pending_integration > 0 && (
          <div style={{ fontSize: 11, color: "#f59e0b", background: "#f59e0b18", padding: "4px 10px", borderRadius: 8, border: "1px solid #f59e0b33" }}>
            {pending_integration} awaiting integration
          </div>
        )}
      </div>

      {/* Stage summary bar */}
      <StageProgress counts={stage_counts} />

      {/* Active agents strip */}
      {active_agents.length > 0 && (
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {active_agents.map((agent: any) => (
            <div
              key={agent.instance_id}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "4px 10px", borderRadius: 8,
                background: "#10b98118", border: "1px solid #10b98133",
                fontSize: 11,
              }}
            >
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#10b981", animation: "pulse 1.5s infinite" }} />
              <span style={{ fontWeight: 600, color: "#e2e8f0" }}>{agent.persona_name}</span>
              <span style={{ color: "#64748b" }}>{agent.spawn_reason?.replace(/_/g, " ")}</span>
              <span style={{ color: "#475569" }}>{formatAge(agent.age_seconds)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Pipeline items */}
      {pipeline.length > 0 ? (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
          {pipeline.map((item: any) => (
            <div
              key={item.finding_id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "8px 12px",
                borderRadius: 10,
                background: "#0f172a",
                border: "1px solid #1e293b",
              }}
            >
              <StageBadge stage={item.stage} />

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 12, fontWeight: 500, color: "#e2e8f0",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {item.title}
                </div>
                <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>
                  {item.author_name && (
                    <span style={{ color: "#94a3b8" }}>{item.author_name}</span>
                  )}
                  {item.objective_title && (
                    <>
                      <span style={{ margin: "0 4px" }}>/</span>
                      <span>{item.objective_title}</span>
                    </>
                  )}
                </div>
              </div>

              <CitationScoreBadge score={item.citation_score} />

              {item.reviews_completed > 0 && (
                <span style={{ fontSize: 10, color: "#8b5cf6", fontWeight: 600 }}>
                  {item.reviews_completed} review{item.reviews_completed > 1 ? "s" : ""}
                </span>
              )}

              <span style={{
                fontSize: 10, color: item.age_seconds > 3600 ? "#ef4444" : "#475569",
                fontWeight: item.age_seconds > 3600 ? 600 : 400,
                whiteSpace: "nowrap",
              }}>
                {formatAge(item.age_seconds)}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ marginTop: 16, textAlign: "center", color: "#475569", fontSize: 13 }}>
          No findings currently in the pipeline.
        </div>
      )}

      {/* Recent completions */}
      {recent_completed.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Recently Completed
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {recent_completed.map((item: any) => (
              <div
                key={item.finding_id}
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "3px 8px", borderRadius: 6,
                  background: item.status === "validated" ? "#10b98112" : "#ef444412",
                  border: `1px solid ${item.status === "validated" ? "#10b98122" : "#ef444422"}`,
                  fontSize: 10,
                }}
              >
                <span style={{ color: item.status === "validated" ? "#10b981" : "#ef4444", fontWeight: 600, textTransform: "uppercase" }}>
                  {item.status}
                </span>
                <span style={{ color: "#94a3b8", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {item.title}
                </span>
                <CitationScoreBadge score={item.citation_score} />
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
