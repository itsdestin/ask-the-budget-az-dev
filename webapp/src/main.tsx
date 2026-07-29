import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./index.css";

const rootEl = document.getElementById("root");
// Fail loudly rather than silently rendering nothing if index.html drifts.
if (!rootEl) throw new Error("#root not found in index.html");

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
