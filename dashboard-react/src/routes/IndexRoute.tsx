import { MapPlaceholder } from "../components/MapPlaceholder";
import { ThreePaneLayout } from "../components/ThreePaneLayout";

export function IndexRoute() {
  return (
    <ThreePaneLayout
      tree={
        // Plan 08 fills the device tree in here.
        <p className="p-3 text-sm text-fg-tertiary">Device tree</p>
      }
      centreTop={
        <div className="h-full p-3">
          {/* Plan 07 inserts the stats strip above this placeholder. */}
          <MapPlaceholder />
        </div>
      }
      centreBottom={
        // Plan 10 fills the event history in here.
        <p className="p-3 text-sm text-fg-tertiary">Event history</p>
      }
    />
  );
}
