import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
// tokens.css first: app.css (and every page CSS ported after it) reads the
// custom properties it defines, so the :root block has to be in the cascade first.
import "./styles/tokens.css";
import "./styles/app.css";

const rootEl = document.getElementById("root");
// Fail loudly rather than silently rendering nothing if index.html drifts.
if (!rootEl) throw new Error("#root not found in index.html");

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
