import { useSearchParams } from "react-router";

// Preserves the ?id=<hostname> convention (D-19) on a route instead of a second HTML
// file (D-41) — Phase 11 removed Details from the nav, but the route stays bookmarkable.
export function DetailsRoute() {
  const [searchParams] = useSearchParams();
  const id = searchParams.get("id");

  return (
    <main>
      <h1>Device Details</h1>
      {id ? <p>{id}</p> : <p>No device selected</p>}
    </main>
  );
}
