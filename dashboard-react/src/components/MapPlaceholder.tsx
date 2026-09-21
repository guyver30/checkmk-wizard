// D-27: the real topology map is Phase 13 (DASH-07). This placeholder occupies exactly the
// geometry the map will occupy -- sized by its container, never by a fixed pixel height --
// so Phase 13 drops it in without a second layout pass.
export function MapPlaceholder() {
  return (
    <div className="flex h-full w-full items-center justify-center rounded-md border border-neutral-150 bg-bg-subtle">
      <span className="text-sm text-fg-tertiary">Topology map — Phase 13</span>
    </div>
  );
}
