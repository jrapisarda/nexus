import { useEffect, useState } from "react";
import { useNexusWebSocket } from "./hooks/useWebSocket";
import { useDashboardStore } from "./store";
import MissionControl from "./components/MissionControl";
import AlertCenter from "./components/AlertCenter";
import AgentPopulation from "./components/AgentPopulation";
import ObjectiveRadar from "./components/ObjectiveRadar";
import ReviewIntel from "./components/ReviewIntel";
import PipelineTracker from "./components/PipelineTracker";
import WorkloadBoard from "./components/WorkloadBoard";
import ActivityFeed from "./components/ActivityFeed";
import EvolutionaryLineage from "./components/EvolutionaryLineage";
import ObjectiveDAG from "./components/ObjectiveDAG";
import KnowledgeGraph from "./components/KnowledgeGraph";
import KnowledgeGraphWorkbench from "./components/KnowledgeGraphWorkbench";
import MarketplaceView from "./components/MarketplaceView";
import SecuritiesView from "./components/SecuritiesView";
import EconomyPanel from "./components/EconomyPanel";
import KGNodePortfolio from "./components/KGNodePortfolio";
import CostReport from "./components/CostReport";
import CivilizationWorkbench from "./components/CivilizationWorkbench";

type AppTab = "overview" | "marketplace" | "securities" | "kg";

const panelStyle: React.CSSProperties = {
  background: "#1e293b",
  borderRadius: 8,
  padding: 16,
  overflow: "hidden",
  display: "flex",
  flexDirection: "column",
};

function readHashTab(): AppTab {
  switch (window.location.hash) {
    case "#/marketplace":
      return "marketplace";
    case "#/securities":
      return "securities";
    case "#/kg":
      return "kg";
    default:
      return "overview";
  }
}

export default function App() {
  useNexusWebSocket();
  const wsConnected = useDashboardStore((s) => s.wsConnected);
  const [activeTab, setActiveTab] = useState<AppTab>(readHashTab());

  useEffect(() => {
    const onHashChange = () => setActiveTab(readHashTab());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const switchTab = (tab: AppTab) => {
    const path =
      tab === "kg"
        ? "/kg"
        : tab === "marketplace"
          ? "/marketplace"
          : tab === "securities"
            ? "/securities"
            : "/overview";
    window.location.hash = path;
    setActiveTab(tab);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "#38bdf8" }}>
            Autonomous Research Control Room
          </div>
          <h1 style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>
            NEXUS Observatory
          </h1>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <TabButton label="Overview" active={activeTab === "overview"} onClick={() => switchTab("overview")} />
          <TabButton label="Marketplace" active={activeTab === "marketplace"} onClick={() => switchTab("marketplace")} />
          <TabButton label="Securities" active={activeTab === "securities"} onClick={() => switchTab("securities")} />
          <TabButton label="Knowledge Graph" active={activeTab === "kg"} onClick={() => switchTab("kg")} />
          <span
            style={{
              fontSize: 12,
              color: wsConnected ? "#10b981" : "#ef4444",
              letterSpacing: "0.08em",
            }}
          >
            {wsConnected ? "LIVE" : "DISCONNECTED"}
          </span>
        </div>
      </header>

      {activeTab === "overview" ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
            gap: 16,
            flex: 1,
          }}
        >
          <div
            style={{
              ...panelStyle,
              gridColumn: "1 / -1",
              background: "linear-gradient(135deg, #172554 0%, #0f172a 48%, #111827 100%)",
              border: "1px solid #1d4ed8",
            }}
          >
            <MissionControl />
          </div>

          <div style={{ ...panelStyle, gridColumn: "1 / -1", border: "1px solid #334155" }}>
            <PipelineTracker />
          </div>

          <div style={{ ...panelStyle, gridColumn: "1 / -1" }}>
            <AlertCenter />
          </div>

          <div style={{ ...panelStyle, gridColumn: "1 / -1" }}>
            <AgentPopulation />
          </div>

          <div style={{ ...panelStyle, gridColumn: "1 / -1", minHeight: 280 }}>
            <ObjectiveRadar />
          </div>

          <div style={{ ...panelStyle, minHeight: 420 }}>
            <ReviewIntel />
          </div>
          <div style={{ ...panelStyle, minHeight: 420 }}>
            <WorkloadBoard />
          </div>

          <div style={{ ...panelStyle, gridColumn: "1 / -1", minHeight: 300 }}>
            <ActivityFeed />
          </div>

          <div style={{ ...panelStyle, gridColumn: "1 / -1", minHeight: 420 }}>
            <CivilizationWorkbench />
          </div>

          <div style={{ ...panelStyle, minHeight: 380 }}>
            <ObjectiveDAG />
          </div>
          <div style={{ ...panelStyle, minHeight: 380 }}>
            <EvolutionaryLineage />
          </div>

          <div style={{ ...panelStyle, gridColumn: "1 / -1", minHeight: 420 }}>
            <KnowledgeGraph />
          </div>

          <div style={{ ...panelStyle, gridColumn: "1 / -1", minHeight: 260 }}>
            <KGNodePortfolio />
          </div>

          <div style={{ ...panelStyle, minHeight: 340 }}>
            <EconomyPanel />
          </div>
          <div style={{ ...panelStyle, minHeight: 340 }}>
            <CostReport />
          </div>
        </div>
      ) : activeTab === "marketplace" ? (
        <div
          style={{
            ...panelStyle,
            flex: 1,
            minHeight: 0,
            background: "linear-gradient(180deg, #111827 0%, #0f172a 100%)",
            border: "1px solid #1e293b",
            overflow: "auto",
          }}
        >
          <MarketplaceView />
        </div>
      ) : activeTab === "securities" ? (
        <div
          style={{
            ...panelStyle,
            flex: 1,
            minHeight: 0,
            background: "linear-gradient(180deg, #111827 0%, #0f172a 100%)",
            border: "1px solid #1e293b",
            overflow: "auto",
          }}
        >
          <SecuritiesView />
        </div>
      ) : (
        <div
          style={{
            ...panelStyle,
            flex: 1,
            minHeight: 0,
            background: "linear-gradient(180deg, #111827 0%, #0f172a 100%)",
            border: "1px solid #1e293b",
            overflow: "auto",
          }}
        >
          <KnowledgeGraphWorkbench />
        </div>
      )}
    </div>
  );
}

function TabButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        border: `1px solid ${active ? "#38bdf8" : "#334155"}`,
        background: active ? "#0f172a" : "#111827",
        color: active ? "#e2e8f0" : "#94a3b8",
        borderRadius: 999,
        padding: "8px 14px",
        fontSize: 12,
        fontWeight: 600,
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );
}
