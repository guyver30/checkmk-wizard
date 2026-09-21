import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Order matters: the library CSS defines the :root custom properties that this app's
// Tailwind utilities resolve against, so it must load before ./index.css.
import "kone-design-system/style.css";
import "./index.css";
import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
