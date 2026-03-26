/** Zustand store for global NEXUS dashboard state. */

import { create } from "zustand";
import type { EventMessage } from "../types";

interface DashboardState {
  /** Currently selected objective ID (for DAG view). */
  selectedObjectiveId: string | null;
  setSelectedObjectiveId: (id: string | null) => void;

  /** Currently selected persona ID (for detail view). */
  selectedPersonaId: string | null;
  setSelectedPersonaId: (id: string | null) => void;

  /** Most recent WebSocket events (ring buffer, max 100). */
  recentEvents: EventMessage[];
  addEvent: (event: EventMessage) => void;

  /** WebSocket connection status. */
  wsConnected: boolean;
  setWsConnected: (connected: boolean) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  selectedObjectiveId: null,
  setSelectedObjectiveId: (id) => set({ selectedObjectiveId: id }),

  selectedPersonaId: null,
  setSelectedPersonaId: (id) => set({ selectedPersonaId: id }),

  recentEvents: [],
  addEvent: (event) =>
    set((state) => ({
      recentEvents: [event, ...state.recentEvents].slice(0, 100),
    })),

  wsConnected: false,
  setWsConnected: (connected) => set({ wsConnected: connected }),
}));
