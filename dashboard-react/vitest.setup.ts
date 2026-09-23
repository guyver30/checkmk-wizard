import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";
import { FakeNetwork } from "./src/test/fakeVisNetwork";

// vis-network's canvas renderer calls getContext("2d"), which jsdom does not implement --
// this mock is registered globally (not per-test-file) so every test that renders IndexRoute
// (App, IndexRoute, GroupingControls, StaleStability) can mount TopologyMap without a real
// canvas. Follows the same "stub what jsdom lacks, comment why" convention Splitter.test.tsx
// established for setPointerCapture/releasePointerCapture.
vi.mock("vis-network/peer", () => ({
  Network: FakeNetwork,
}));
