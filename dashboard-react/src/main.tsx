import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Order matters: the library CSS defines the :root custom properties that this app's
// Tailwind utilities resolve against, so it must load before ./index.css.
import "kone-design-system/style.css";
import "./index.css";
import App from "./App.tsx";
import { isAdminMode, loadAdminConfig } from "./lib/adminMode";
import { loadRuntimeConfig } from "./lib/runtimeConfig";
import { useAdminStore } from "./store/adminStore";

// The runtime config must be loaded before App mounts: App's effect calls connect() and the
// topology-editor probe runs on first render, both of which read getRuntimeConfig(). In
// admin mode the wsadmin credentials must also be in place before that connect().
// loadRuntimeConfig() and loadAdminConfig() never reject, so no catch branch is needed here.
void loadRuntimeConfig()
  .then(() => (isAdminMode() ? loadAdminConfig() : true))
  .then((adminOk) => {
    if (isAdminMode()) {
      useAdminStore.getState().setConfigError(!adminOk);
    }
    createRoot(document.getElementById("root")!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  });
