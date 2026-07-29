// Vitest's defineConfig (not vite's) so the `test` key below typechecks.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev mode: vite on 5173 proxies API calls to the FastAPI app on 9300.
    // Keeps the browser on a single origin so fetch("/api/...") needs no CORS
    // handling and the same relative paths work in the production build (where
    // FastAPI serves webapp/dist itself).
    proxy: {
      "/api": "http://127.0.0.1:9300",
      "/health": "http://127.0.0.1:9300",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    globals: true,
  },
});
