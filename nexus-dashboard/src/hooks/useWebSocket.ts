/** Custom hook for NEXUS real-time WebSocket updates. */

import { useCallback, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import useWS, { ReadyState } from "react-use-websocket";
import { useDashboardStore } from "../store";
import type { EventMessage } from "../types";

const WS_URL = `ws://${window.location.hostname}:${window.location.port || "8000"}/ws`;

export function useNexusWebSocket() {
  const queryClient = useQueryClient();
  const addEvent = useDashboardStore((s) => s.addEvent);
  const setWsConnected = useDashboardStore((s) => s.setWsConnected);

  const { lastJsonMessage, readyState } = useWS(WS_URL, {
    shouldReconnect: () => true,
    reconnectInterval: 3000,
    reconnectAttempts: Infinity,
  });

  const invalidateForEvent = useCallback(
    (event: EventMessage) => {
      if (event.type === "connected") {
        return;
      }

      queryClient.invalidateQueries({ queryKey: ["activity"] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["objectives"] });
      queryClient.invalidateQueries({ queryKey: ["objective-dag"] });
      queryClient.invalidateQueries({ queryKey: ["telemetry-cost"] });
      queryClient.invalidateQueries({ queryKey: ["telemetry-performance"] });
      queryClient.invalidateQueries({ queryKey: ["observatory-overview"] });
      queryClient.invalidateQueries({ queryKey: ["observatory-alerts"] });
      queryClient.invalidateQueries({ queryKey: ["review-intel"] });
      queryClient.invalidateQueries({ queryKey: ["workload-board"] });
      queryClient.invalidateQueries({ queryKey: ["objective-radar"] });

      if (
        event.type.startsWith("kg_") ||
        event.type.startsWith("finding_") ||
        event.type.startsWith("review_")
      ) {
        queryClient.invalidateQueries({ queryKey: ["kg-nodes"] });
        queryClient.invalidateQueries({ queryKey: ["kg-edges"] });
        queryClient.invalidateQueries({ queryKey: ["kg-stats"] });
        queryClient.invalidateQueries({ queryKey: ["kg-workbench-overview"] });
        queryClient.invalidateQueries({ queryKey: ["kg-subgraph"] });
        queryClient.invalidateQueries({ queryKey: ["kg-node-detail"] });
        queryClient.invalidateQueries({ queryKey: ["kg-evidence"] });
        queryClient.invalidateQueries({ queryKey: ["kg-path"] });
        queryClient.invalidateQueries({ queryKey: ["kg-changes"] });
      }

      if (event.type.includes("report")) {
        queryClient.invalidateQueries({ queryKey: ["question-reports"] });
        queryClient.invalidateQueries({ queryKey: ["report-file"] });
      }

      if (
        event.type.startsWith("economy_") ||
        event.type.startsWith("bounty_") ||
        event.type.startsWith("rent_") ||
        event.type.startsWith("bond_")
      ) {
        queryClient.invalidateQueries({ queryKey: ["economy-summary"] });
        queryClient.invalidateQueries({ queryKey: ["ledger"] });
        queryClient.invalidateQueries({ queryKey: ["evolution-lineage"] });
      }

      if (
        event.type.startsWith("finding_challenged") ||
        event.type.startsWith("appeal_") ||
        event.type.startsWith("contrarian_") ||
        event.type.startsWith("slow_objective_") ||
        event.type.startsWith("exploration_") ||
        event.type.startsWith("scout_coverage_") ||
        event.type.startsWith("circuit_breaker_")
      ) {
        queryClient.invalidateQueries({ queryKey: ["civilization-overview"] });
        queryClient.invalidateQueries({ queryKey: ["civilization-capabilities"] });
        queryClient.invalidateQueries({ queryKey: ["civilization-challenges"] });
        queryClient.invalidateQueries({ queryKey: ["civilization-scout-health"] });
        queryClient.invalidateQueries({ queryKey: ["civilization-evolution"] });
        queryClient.invalidateQueries({ queryKey: ["civilization-breakers"] });
      }

      if (
        event.type.startsWith("market_") ||
        event.type.startsWith("service_contract_") ||
        event.type.startsWith("security_") ||
        event.type.startsWith("instrument_") ||
        event.type.startsWith("position_") ||
        event.type.startsWith("settlement_")
      ) {
        queryClient.invalidateQueries({ queryKey: ["marketplace-overview"] });
        queryClient.invalidateQueries({ queryKey: ["marketplace-listings"] });
        queryClient.invalidateQueries({ queryKey: ["marketplace-contracts"] });
        queryClient.invalidateQueries({ queryKey: ["marketplace-activity"] });
        queryClient.invalidateQueries({ queryKey: ["securities-overview"] });
        queryClient.invalidateQueries({ queryKey: ["securities-instruments"] });
        queryClient.invalidateQueries({ queryKey: ["securities-order-book"] });
        queryClient.invalidateQueries({ queryKey: ["securities-trades"] });
        queryClient.invalidateQueries({ queryKey: ["securities-positions"] });
      }
    },
    [queryClient],
  );

  // Track connection status.
  useEffect(() => {
    setWsConnected(readyState === ReadyState.OPEN);
  }, [readyState, setWsConnected]);

  // Push incoming messages into the store.
  useEffect(() => {
    if (lastJsonMessage) {
      const event = lastJsonMessage as EventMessage;
      addEvent(event);
      invalidateForEvent(event);
    }
  }, [lastJsonMessage, addEvent, invalidateForEvent]);

  return {
    connected: readyState === ReadyState.OPEN,
    readyState,
  };
}
