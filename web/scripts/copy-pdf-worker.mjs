#!/usr/bin/env node
// Copy pdfjs-dist's worker bundle to web/public/ so the renderer can
// load it from a stable URL (`/pdf.worker.min.mjs`). Re-run on every
// `npm install` via the postinstall script in package.json.
//
// Why a copy step rather than `?url` import: Next.js 15 / Turbopack
// + pdfjs-dist's mjs worker has fragile module-graph behavior that
// breaks on dev reload. Copying the file once at install time keeps
// the worker URL static and decoupled from the build pipeline.
//
// Pinned to the version in package-lock.json — keeps the runtime
// worker in lockstep with the API client. If pdfjs-dist is bumped,
// `npm install` re-runs this script and the public/ copy refreshes.

import { copyFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, "..");

const SRC = resolve(
  projectRoot,
  "node_modules/pdfjs-dist/build/pdf.worker.min.mjs",
);
const DEST = resolve(projectRoot, "public/pdf.worker.min.mjs");

try {
  await mkdir(dirname(DEST), { recursive: true });
  await copyFile(SRC, DEST);
  console.log(`[copy-pdf-worker] ${SRC}\n  → ${DEST}`);
} catch (err) {
  // Don't fail npm install if pdfjs-dist isn't present yet (e.g.
  // first install). Log and exit cleanly so the install completes
  // and the next run will succeed.
  console.warn(
    `[copy-pdf-worker] skipped: ${err instanceof Error ? err.message : err}`,
  );
}
