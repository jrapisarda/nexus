import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchOrderBook,
  fetchPositions,
  fetchSecuritiesInstruments,
  fetchSecuritiesOverview,
  fetchTrades,
} from "../api/client";
import { ErrorPlaceholder, LoadingPlaceholder } from "./AgentPopulation";

export default function SecuritiesView() {
  const [selectedInstrumentId, setSelectedInstrumentId] = useState<string | null>(null);
  const overviewQuery = useQuery({
    queryKey: ["securities-overview"],
    queryFn: fetchSecuritiesOverview,
  });
  const instrumentsQuery = useQuery({
    queryKey: ["securities-instruments"],
    queryFn: () => fetchSecuritiesInstruments(30),
  });
  const tradesQuery = useQuery({
    queryKey: ["securities-trades"],
    queryFn: () => fetchTrades(30),
  });
  const positionsQuery = useQuery({
    queryKey: ["securities-positions"],
    queryFn: () => fetchPositions(20),
  });

  const effectiveInstrumentId = selectedInstrumentId ?? instrumentsQuery.data?.[0]?.instrument_id ?? null;
  const orderBookQuery = useQuery({
    queryKey: ["securities-order-book", effectiveInstrumentId],
    queryFn: () => fetchOrderBook(effectiveInstrumentId),
    enabled: instrumentsQuery.isSuccess,
  });

  const isLoading =
    overviewQuery.isLoading ||
    instrumentsQuery.isLoading ||
    tradesQuery.isLoading ||
    positionsQuery.isLoading ||
    orderBookQuery.isLoading;
  const error =
    overviewQuery.error ||
    instrumentsQuery.error ||
    tradesQuery.error ||
    positionsQuery.error ||
    orderBookQuery.error;

  const selectedInstrument = useMemo(
    () => instrumentsQuery.data?.find((item) => item.instrument_id === effectiveInstrumentId) ?? instrumentsQuery.data?.[0] ?? null,
    [instrumentsQuery.data, effectiveInstrumentId],
  );

  if (isLoading) return <LoadingPlaceholder label="Securities Exchange" />;
  if (error) return <ErrorPlaceholder label="Securities Exchange" error={error} />;

  const overview = overviewQuery.data!;
  const instruments = instrumentsQuery.data ?? [];
  const trades = tradesQuery.data ?? [];
  const positions = positionsQuery.data ?? [];
  const orderBook = orderBookQuery.data!;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <section
        style={{
          background: "linear-gradient(135deg, #172554 0%, #0f172a 48%, #111827 100%)",
          border: "1px solid #1d4ed8",
          borderRadius: 16,
          padding: 18,
        }}
      >
        <div style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "#60a5fa" }}>
          Securities Exchange
        </div>
        <h2 style={{ fontSize: 26, fontWeight: 700, marginTop: 8 }}>Continuous order book for objective, finding, and persona notes</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginTop: 14 }}>
          <MetricCard label="Instruments" value={String(overview.instrument_count)} />
          <MetricCard label="Open Orders" value={String(overview.open_order_count)} />
          <MetricCard label="Trade Volume" value={`${overview.trade_volume.toFixed(0)} cr`} />
          <MetricCard label="Settlement Backlog" value={String(overview.settlement_backlog)} />
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "1.1fr 0.9fr", gap: 16 }}>
        <Panel title="Instrument Board">
          <div style={{ display: "grid", gap: 8 }}>
            {instruments.slice(0, 10).map((instrument) => {
              const selected = instrument.instrument_id === selectedInstrument?.instrument_id;
              return (
                <button
                  key={instrument.instrument_id}
                  type="button"
                  onClick={() => setSelectedInstrumentId(instrument.instrument_id)}
                  style={{
                    textAlign: "left",
                    background: selected ? "#0b1733" : "#0f172a",
                    color: "#e2e8f0",
                    border: `1px solid ${selected ? "#60a5fa" : "#1f2937"}`,
                    borderRadius: 12,
                    padding: 12,
                    cursor: "pointer",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <strong>{instrument.symbol}</strong>
                    <span style={{ color: instrument.halted ? "#f59e0b" : "#94a3b8" }}>
                      {instrument.settlement_status}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>{instrument.name}</div>
                  <div style={{ display: "flex", gap: 12, marginTop: 8, fontSize: 12 }}>
                    <span>Mark {instrument.mark_price.toFixed(1)}</span>
                    <span>Last {instrument.last_trade_price.toFixed(1)}</span>
                    <span>{instrument.family}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </Panel>

        <Panel title={`Order Book${selectedInstrument ? ` | ${selectedInstrument.symbol}` : ""}`}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <BookSide title="Bids" accent="#22c55e" rows={orderBook.bids} />
            <BookSide title="Asks" accent="#ef4444" rows={orderBook.asks} />
          </div>
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Panel title={`Recent Trades (${trades.length})`}>
          <SimpleTable
            columns={["Symbol", "Buyer", "Seller", "Price", "Qty"]}
            rows={trades.slice(0, 12).map((trade) => [
              trade.instrument_symbol,
              trade.buyer_name,
              trade.seller_name,
              trade.price.toFixed(1),
              trade.quantity.toFixed(2),
            ])}
          />
        </Panel>

        <Panel title={`Positions Leaderboard (${positions.length})`}>
          <SimpleTable
            columns={["Persona", "Symbol", "Qty", "Avg", "Value"]}
            rows={positions.slice(0, 12).map((position) => [
              position.persona_name,
              position.instrument_symbol,
              position.net_quantity.toFixed(2),
              position.average_entry_price.toFixed(1),
              position.market_value.toFixed(1),
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

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ background: "#111827", borderRadius: 16, padding: 16, border: "1px solid #1f2937" }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>{title}</h3>
      {children}
    </section>
  );
}

function BookSide({
  title,
  accent,
  rows,
}: {
  title: string;
  accent: string;
  rows: Array<{ order_id: string; price: number; remaining_quantity: number; persona_name: string }>;
}) {
  return (
    <div style={{ background: "#0f172a", borderRadius: 12, border: `1px solid ${accent}33`, padding: 12 }}>
      <div style={{ color: accent, fontWeight: 700, marginBottom: 8 }}>{title}</div>
      <div style={{ display: "grid", gap: 8 }}>
        {rows.length > 0 ? rows.map((row) => (
          <div key={row.order_id} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
            <span>{row.persona_name}</span>
            <span>{row.remaining_quantity.toFixed(2)} @ {row.price.toFixed(1)}</span>
          </div>
        )) : <div style={{ color: "#64748b", fontSize: 12 }}>No resting orders.</div>}
      </div>
    </div>
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
