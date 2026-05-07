import { defineConfig } from "vitest/config";

export default defineConfig({
  // Use the automatic JSX runtime so `.tsx` test files don't need an
  // explicit `import React from "react"` (matches Next.js's default).
  esbuild: {
    jsx: "automatic",
  },
  test: {
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    environment: "node",
    globals: false,
    testTimeout: 10000,
  },
});
