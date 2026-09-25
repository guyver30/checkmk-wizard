import { useEffect } from "react";
import { BrowserRouter, Route, Routes, useLocation, useNavigate } from "react-router";
import { NavBar } from "kone-design-system";
import { ConnectionIndicator } from "./components/ConnectionIndicator";
import { DetailsRoute } from "./routes/DetailsRoute";
import { IndexRoute } from "./routes/IndexRoute";
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
      <AppNav />
      <Routes>
        <Route path="/" element={<IndexRoute />} />
        <Route path="/details" element={<DetailsRoute />} />
        <Route path="*" element={<IndexRoute />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
