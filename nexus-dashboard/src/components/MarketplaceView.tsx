import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchAgents,
  fetchMarketplaceActivity,
  fetchMarketplaceContracts,
  fetchMarketplaceListings,
  fetchMarketplaceOverview,
} from "../api/client";
import { ErrorPlaceholder, LoadingPlaceholder } from "./AgentPopulation";

export default function MarketplaceView() {
  const overviewQuery = useQuery({
    queryKey: ["marketplace-overview"],
    queryFn: fetchMarketplaceOverview,
  });
  const listingsQuery = useQuery({
    queryKey: ["marketplace-listings"],
    queryFn: () => fetchMarketplaceListings(30),
  });
  const contractsQuery = useQuery({
    queryKey: ["marketplace-contracts"],
    queryFn: () => fetchMarketplaceContracts(20),
  });
  const activityQuery = useQuery({
    queryKey: ["marketplace-activity"],
    queryFn: () => fetchMarketplaceActivity(30),
  });
  const agentsQuery = useQuery({
    queryKey: ["agents"],
    queryFn: () => fetchAgents(),
  });

  const isLoading =
    overviewQuery.isLoading ||
    listingsQuery.isLoading ||
    contractsQuery.isLoading ||
    activityQuery.isLoading ||
    agentsQuery.isLoading;

  const error =
    overviewQuery.error ||
    listingsQuery.error ||
    contractsQuery.error ||
    activityQuery.error ||
    agentsQuery.error;

  const nameById = useMemo(() => {
    const personas = agentsQuery.data?.personas ?? [];
    return Object.fromEntries(personas.map((persona) => [persona.persona_id, persona.persona_name]));
  }, [agentsQuery.data]);

  if (isLoading) return <LoadingPlaceholder label="Marketplace" />;
  if (error) return <ErrorPlaceholder label="Marketplace" error={error} />;

  const overview = overviewQuery.data!;
  const listings = listingsQuery.data ?? [];
  const contracts = contractsQuery.data ?? [];
  const activity = activityQuery.data?.items ?? [];

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <section
        style={{
          background: "linear-gradient(135deg, #0f3b2e 0%, #10221f 48%, #111827 100%)",
          border: "1px solid #14532d",
          borderRadius: 16,
          padding: 18,
        }}
      >
        <div style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "#34d399" }}>
          Autonomous Marketplace
        </div>
        <h2 style={{ fontSize: 26, fontWeight: 700, marginTop: 8 }}>Crafted goods, bounded services, and live escrow</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginTop: 14 }}>
          <MetricCard label="Active Listings" value={String(overview.active_listings)} />
          <MetricCard label="Pending Contracts" value={String(overview.pending_contracts)} />
          <MetricCard label="Fulfilled 24h" value={String(overview.fulfilled_contracts_24h)} />
          <MetricCard label="Listing Value" value={`${overview.total_listing_value.toFixed(0)} cr`} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 14 }}>
          <InlineList
            title="Top Sellers"
            items={overview.top_seller_ids.map((id) => nameById[id] ?? id.slice(0, 8))}
          />
          <InlineList
            title="Top Buyers"
            items={overview.top_buyer_ids.map((id) => nameById[id] ?? id.slice(0, 8))}
          />
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 16 }}>
        <Panel title="Live Market Tape">
          <div style={{ display: "grid", gap: 8 }}>
            {activity.slice(0, 10).map((item) => (
              <div key={item.event_id} style={{ background: "#0f172a", borderRadius: 10, padding: 10, border: "1px solid #1f2937" }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#e2e8f0" }}>{item.event_type.replace(/_/g, " ")}</div>
                <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>{summarizePayload(item.payload)}</div>
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 6 }}>{formatRelative(item.created_at)}</div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Category Breakdown">
          <div style={{ display: "grid", gap: 8 }}>
            {Object.entries(overview.category_breakdown).map(([label, count]) => (
              <div key={label} style={{ display: "flex", justifyContent: "space-between", padding: "10px 12px", background: "#0f172a", borderRadius: 10 }}>
                <span style={{ color: "#cbd5e1" }}>{label}</span>
                <strong>{count}</strong>
              </div>
            ))}
            {Object.keys(overview.category_breakdown).length === 0 && (
              <div style={{ color: "#64748b" }}>No marketplace inventory yet.</div>
            )}
          </div>
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.15fr 0.85fr", gap: 16 }}>
        <Panel title={`Active Listings (${listings.length})`}>
          <SimpleTable
            columns={["Seller", "Template", "Kind", "Price", "Qty", "Status"]}
            rows={listings.slice(0, 12).map((listing) => [
              listing.seller_name,
              listing.template_title,
              listing.listing_kind,
              `${listing.price.toFixed(0)} cr`,
              String(listing.quantity_available),
              listing.status,
            ])}
          />
        </Panel>
        <Panel title={`Contract Queue (${contracts.length})`}>
          <SimpleTable
            columns={["Buyer", "Seller", "Service", "Price", "Status"]}
            rows={contracts.slice(0, 12).map((contract) => [
              contract.buyer_name,
              contract.seller_name,
              contract.template_title,
              `${contract.agreed_price.toFixed(0)} cr`,
              contract.status,
            ])}
          />
        </Panel>
      </div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: "rgba(15, 23, 42, 0.72)", borderRadius: 12, padding: 12, border: "1px solid #1f2937" }}>
      <div style={{ fontSize: 11, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: "#f8fafc", marginTop: 8 }}>{value}</div>
    </div>
  );
}

function InlineList({ title, items }: { title: string; items: string[] }) {
  return (
    <div style={{ background: "rgba(15, 23, 42, 0.72)", borderRadius: 12, padding: 12, border: "1px solid #1f2937" }}>
      <div style={{ fontSize: 11, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.08em" }}>{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
        {items.length > 0 ? items.map((item) => (
          <span key={item} style={{ background: "#0f172a", borderRadius: 999, padding: "5px 10px", fontSize: 12 }}>
            {item}
          </span>
        )) : <span style={{ color: "#64748b" }}>No activity yet.</span>}
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ background: "#111827", borderRadius: 16, padding: 16, border: "1px solid #1f2937" }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>{title}</h3>
      {children}
    </section>
  );
}

function SimpleTable({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #1f2937" }}>
            {columns.map((column) => (
              <th key={column} style={{ padding: "8px 10px", color: "#94a3b8", fontWeight: 600 }}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length > 0 ? rows.map((row, index) => (
            <tr key={`${row[0]}-${index}`} style={{ borderBottom: "1px solid #111827" }}>
              {row.map((cell, cellIndex) => (
                <td key={`${cell}-${cellIndex}`} style={{ padding: "8px 10px", color: "#e2e8f0" }}>{cell}</td>
              ))}
            </tr>
          )) : (
            <tr>
              <td colSpan={columns.length} style={{ padding: "12px 10px", color: "#64748b" }}>No data available.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function summarizePayload(payload: Record<string, unknown>) {
  if (payload.instrument_symbol) return `${payload.instrument_symbol} ${payload.side ?? ""} ${payload.price ?? ""}`.trim();
  if (payload.template_code) return String(payload.template_code);
  if (payload.service_objective_id) return `Service objective ${String(payload.service_objective_id).slice(0, 8)}`;
  return Object.entries(payload)
    .slice(0, 2)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(" ");
}

function formatRelative(value: string) {
  const deltaMs = Date.now() - new Date(value).getTime();
  const minutes = Math.max(Math.floor(deltaMs / 60000), 0);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
