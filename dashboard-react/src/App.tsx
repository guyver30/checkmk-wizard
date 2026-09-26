import { useEffect } from "react";
import { BrowserRouter, Route, Routes, useLocation, useNavigate, useSearchParams } from "react-router";
import { NavBar } from "kone-design-system";
import { ConnectionIndicator } from "./components/ConnectionIndicator";
import { DetailsRoute } from "./routes/DetailsRoute";
import { IndexRoute } from "./routes/IndexRoute";
import { KioskView } from "./routes/KioskView";
import { connect } from "./store/mqttClient";

// Details is deliberately NOT in the nav (Phase 11 removed it, D-19/D-21) — the route
// stays reachable via a bookmarked/shared ?id= link, just not linked from here.
function AppNav() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <NavBar
      appName="DMC digital live dashboard"
      logo={<img src="/kone-logo.png" alt="KONE" className="h-6 w-auto rounded-sm" />}
      items={[
        { id: "overview", label: "Overview", active: location.pathname === "/", onClick: () => navigate("/") },
      ]}
      actions={<ConnectionIndicator />}
    />
  );
}

// DASH-17/D-14: kiosk is a rendering mode of "/", not a separate route -- ?kiosk=1 swaps the
// entire chrome+layout for KioskView here, at the one place that decides what "/" renders, so
// the incident/map logic KioskView reuses (IncidentList, TopologyMap) cannot drift into a
// second, route-level implementation of its own.
function AppShell() {
  const location = useLocation();
  const [searchParams] = useSearchParams();

  if (location.pathname === "/" && searchParams.get("kiosk") === "1") {
    return <KioskView />;
  }

  return (
    <>
      <AppNav />
      <Routes>
        <Route path="/" element={<IndexRoute />} />
        <Route path="/details" element={<DetailsRoute />} />
        <Route path="*" element={<IndexRoute />} />
      </Routes>
    </>
  );
}

function App() {
  // Connects once, at app startup. This effect body is safe despite React 18/19 StrictMode's
  // double-invoked effects because mqttClient.connect() carries its own module-level
  // idempotency guard (plan 05's `if (client) return;`) -- a future reader must not "fix" this
  // by adding a cleanup that tears the connection down, since mqttClient is a module singleton
  // intended to outlive any one component and a StrictMode cleanup would close the shared
  // connection immediately after opening it.
  useEffect(() => {
    connect();
  }, []);

  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}

export default App;
