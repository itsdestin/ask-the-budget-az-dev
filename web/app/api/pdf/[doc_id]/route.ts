// GET /api/pdf/[doc_id] — Range-aware PDF streamer.
//
// PDF.js loads PDFs in 64KB chunks via HTTP Range requests; serving
// the file as a single 200 OK response would force the whole PDF
// into memory before the first page can render. This route resolves
// `doc_id` → on-disk path via the FastAPI sidecar's `/docs/{doc_id}`
// endpoint, then streams the requested byte range from the local
// filesystem with the right `Content-Range` / `Content-Length` /
// `Accept-Ranges` headers.
//
// Phase 1 is single-machine — the sidecar and Next server share a
// filesystem, so the path returned by `/docs/{doc_id}` is always
// readable here. When the app moves to Vercel + Supabase (Phase 2),
// this route changes to fetch from object storage instead; nothing
// upstream of this route needs to know.

import { promises as fs, createReadStream } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import { Readable } from "node:stream";
import { NextResponse } from "next/server";

const RETRIEVAL_BRIDGE_URL =
  process.env.RETRIEVAL_BRIDGE_URL ?? "http://127.0.0.1:9200";

// FastAPI's /docs endpoint returns `source_blob_path` as a path
// relative to the project root (e.g. `data/cached-pdfs/...pdf`).
// Next.js's `process.cwd()` is the `web/` subdir, not the project
// root, so plain `fs.stat(blobPath)` would look in `web/data/...`
// and miss every cached PDF. Resolve relative paths against the
// repo root, configurable via env for non-local deployments.
const CORPUS_ROOT =
  process.env.BUDGET_CORPUS_ROOT ?? resolve(process.cwd(), "..");

function resolveBlobPath(blobPath: string): string {
  return isAbsolute(blobPath) ? blobPath : resolve(CORPUS_ROOT, blobPath);
}

interface DocMetadata {
  doc_id: string;
  title: string;
  publisher: string;
  doc_type: string;
  fiscal_year: number;
  source_format: string;
  source_blob_path: string;
  page_count?: number | null;
  source_url?: string | null;
}

/**
 * Pulls metadata for a doc from the FastAPI sidecar. Returns null if
 * the sidecar reports 404 so the route handler can translate that to
 * a Next 404 with no extra parsing.
 */
async function fetchDocMetadata(docId: string): Promise<DocMetadata | null> {
  const url = `${RETRIEVAL_BRIDGE_URL}/docs/${encodeURIComponent(docId)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(
      `retrieval bridge returned ${res.status} for /docs/${docId}`,
    );
  }
  return (await res.json()) as DocMetadata;
}

/**
 * Parses the Range header. Supports the single-range bytes form PDF.js
 * uses; multi-range and other unit names are ignored (caller falls
 * back to a 200 full-body response).
 */
export function parseRangeHeader(
  header: string | null,
  size: number,
): { start: number; end: number } | null {
  if (!header) return null;
  const m = header.match(/^bytes=(\d*)-(\d*)$/);
  if (!m) return null;
  const startStr = m[1] ?? "";
  const endStr = m[2] ?? "";
  if (startStr === "" && endStr === "") return null;
  let start: number;
  let end: number;
  if (startStr === "") {
    // Suffix-byte-range: last N bytes.
    const suffix = parseInt(endStr, 10);
    if (!Number.isFinite(suffix) || suffix <= 0) return null;
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = parseInt(startStr, 10);
    if (!Number.isFinite(start) || start < 0 || start >= size) return null;
    if (endStr === "") {
      end = size - 1;
    } else {
      end = parseInt(endStr, 10);
      if (!Number.isFinite(end)) return null;
      // Inverted ranges (end < start) are spec-violating — reject so
      // the caller falls back to a 200 full body. Don't clamp: a
      // negative or transposed range almost always indicates a
      // bug-level header, not a recoverable overshoot.
      if (end < start) return null;
      // Clamp end past EOF down to the last byte — PDF.js sometimes
      // asks for ranges past the file end on the trailing fetch and
      // recovers fine when the server caps it.
      if (end >= size) end = size - 1;
    }
  }
  return { start, end };
}

export async function GET(
  req: Request,
  ctx: { params: Promise<{ doc_id: string }> },
) {
  const { doc_id } = await ctx.params;

  let meta: DocMetadata | null;
  try {
    meta = await fetchDocMetadata(doc_id);
  } catch (err) {
    return NextResponse.json(
      {
        error: "retrieval_bridge_unreachable",
        detail: err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    );
  }
  if (!meta) {
    return NextResponse.json({ error: "doc_not_found" }, { status: 404 });
  }
  if (meta.source_format !== "pdf") {
    // DOCX bills are served via a future /api/docx route (Phase 2 per
    // D10). For v1 we return 415 so the PdfViewer can render a
    // "DOCX viewer coming soon" panel instead of trying to load.
    return NextResponse.json(
      { error: "unsupported_source_format", source_format: meta.source_format },
      { status: 415 },
    );
  }

  const absPath = resolveBlobPath(meta.source_blob_path);
  let stat: { size: number };
  try {
    stat = await fs.stat(absPath);
  } catch (err) {
    return NextResponse.json(
      {
        error: "source_blob_missing",
        path: absPath,
        relative: meta.source_blob_path,
        detail: err instanceof Error ? err.message : String(err),
      },
      { status: 500 },
    );
  }
  const totalSize = stat.size;
  const range = parseRangeHeader(req.headers.get("range"), totalSize);

  // Common headers — Accept-Ranges so PDF.js uses Range requests on
  // subsequent fetches; Content-Type so the browser parses as PDF.
  const baseHeaders: Record<string, string> = {
    "Content-Type": "application/pdf",
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, max-age=300",
  };

  if (!range) {
    // Full body — used on the very first fetch (PDF.js sends a HEAD
    // first in some configurations; this branch covers both HEAD
    // fallback and clients without Range support).
    const stream = createReadStream(absPath);
    return new Response(Readable.toWeb(stream) as ReadableStream, {
      status: 200,
      headers: {
        ...baseHeaders,
        "Content-Length": String(totalSize),
      },
    });
  }

  const { start, end } = range;
  const chunkSize = end - start + 1;
  const stream = createReadStream(absPath, { start, end });
  return new Response(Readable.toWeb(stream) as ReadableStream, {
    status: 206,
    headers: {
      ...baseHeaders,
      "Content-Length": String(chunkSize),
      "Content-Range": `bytes ${start}-${end}/${totalSize}`,
    },
  });
}
