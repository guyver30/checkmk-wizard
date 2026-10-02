// One-shot "centre the map on this host" request, raised by a double-click on a device-tree
// row and consumed by TopologyMap. A seq counter (not just the id) lets a second double-click
// on the same host centre again after the user has panned away. Not an admin store: the
// request is only raised outside admin mode (a double-click there is a selection gesture).

import { create } from "zustand";

export interface MapFocusRequest {
  id: string;
  seq: number;
}

interface MapFocusState {
  request: MapFocusRequest | null;
  requestCenter: (id: string) => void;
}

export const useMapFocusStore = create<MapFocusState>((set) => ({
  request: null,
  requestCenter: (id) =>
    set((s) => ({ request: { id, seq: (s.request?.seq ?? 0) + 1 } })),
}));

export function __resetMapFocusStoreForTests(): void {
  useMapFocusStore.setState({ request: null });
}
