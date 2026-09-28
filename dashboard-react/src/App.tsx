import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from "react-router";
import { NavBar } from "kone-design-system";
import { ConnectionIndicator } from "./components/ConnectionIndicator";
import { HeaderStats } from "./components/StatsStrip";
import { hostHref } from "./lib/searchLinks";
import { IndexRoute } from "./routes/IndexRoute";
import { connect } from "./store/mqttClient";

// Details is deliberately NOT in the nav (Phase 11 removed it, D-19/D-21) — the host details
// view now lives in the overview's right-hand pane (?host=<id>, 260928-l4h), reachable from the
// map/tree/incident cards, not from here.
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
      navExtra={<HeaderStats />}
      actions={<ConnectionIndicator />}
    />
  );
}

// A bookmarked/shared old /details?id=<id> link (pre-260928-l4h) redirects to the new
// /?host=<id> pane; /details with no id just lands on the overview. `replace` so the old URL
// doesn't linger in browser history.
function DetailsRedirect() {
  const [searchParams] = useSearchParams();
  const id = searchParams.get("id");
  return <Navigate replace to={id ? hostHref("", id) : "/"} />;
}

export function AppShell() {
  return (
    <>
      <AppNav />
      <Routes>
        <Route path="/" element={<IndexRoute />} />
        <Route path="/details" element={<DetailsRedirect />} />
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
