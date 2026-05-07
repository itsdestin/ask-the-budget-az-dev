import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  // Use the automatic JSX runtime so `.tsx` test files don't need an
  // explicit `import React from "react"` (matches Next.js's default).
  esbuild: {
    jsx: "automatic",
  },
  resolve: {
    // Mirror tsconfig's "@/*": ["./*"] so component code that uses
    // the alias compiles in the test runner the same way it does in
    // Next.js. Tests written before this commit use relative imports;
    // both shapes work side by side.
    alias: {
      "@": __dirname,
    },
  },
  test: {
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    environment: "node",
    globals: false,
    testTimeout: 10000,
  },
});
