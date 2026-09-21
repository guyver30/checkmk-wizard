import { BrowserRouter, Route, Routes, useLocation, useNavigate } from "react-router";
import { NavBar } from "kone-design-system";
import { DetailsRoute } from "./routes/DetailsRoute";
import { DevicesRoute } from "./routes/DevicesRoute";
import { IndexRoute } from "./routes/IndexRoute";

// Details is deliberately NOT in the nav (Phase 11 removed it, D-19/D-21) — the route
// stays reachable via a bookmarked/shared ?id= link, just not linked from here.
function AppNav() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <NavBar
      appName="Checkmk Live Dashboard"
      items={[
        { id: "overview", label: "Overview", active: location.pathname === "/", onClick: () => navigate("/") },
        {
          id: "devices",
          label: "Devices",
          active: location.pathname === "/devices",
          onClick: () => navigate("/devices"),
        },
      ]}
    />
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppNav />
      <Routes>
        <Route path="/" element={<IndexRoute />} />
        <Route path="/devices" element={<DevicesRoute />} />
        <Route path="/details" element={<DetailsRoute />} />
        <Route path="*" element={<IndexRoute />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
