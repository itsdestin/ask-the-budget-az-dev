import { promises as fs } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { logBridgeCall, type BridgeLogRecord } from "../src/lib/bridge-log.js";

let logDir: string;
let logPath: string;

beforeEach(async () => {
  logDir = await fs.mkdtemp(join(tmpdir(), "bridge-log-test-"));
  logPath = join(logDir, "bridge.log");
});

afterEach(async () => {
  await fs.rm(logDir, { recursive: true, force: true });
});

describe("logBridgeCall", () => {
  it("appends a JSONL record with all required fields", async () => {
    const rec: BridgeLogRecord = {
      timestamp: new Date("2026-05-20T12:00:00Z").toISOString(),
      endpoint: "/retrieve",
      durationMs: 120,
      outcome: "ok",
      httpStatus: 200,
      errorCategory: null,
      retrievalId: "abc-123",
    };
    await logBridgeCall(rec, logPath);
    const text = await fs.readFile(logPath, "utf8");
    expect(text.trim().split("\n")).toHaveLength(1);
    const parsed = JSON.parse(text);
    expect(parsed).toMatchObject(rec);
  });

  it("appends multiple records in order", async () => {
    await logBridgeCall(
      { timestamp: "t1", endpoint: "/retrieve", durationMs: 50, outcome: "ok", httpStatus: 200, errorCategory: null },
      logPath,
    );
    await logBridgeCall(
      { timestamp: "t2", endpoint: "/cite/validate", durationMs: 30, outcome: "ok", httpStatus: 200, errorCategory: null },
      logPath,
    );
    const lines = (await fs.readFile(logPath, "utf8")).trim().split("\n");
    expect(lines).toHaveLength(2);
    expect(JSON.parse(lines[0]!).endpoint).toBe("/retrieve");
    expect(JSON.parse(lines[1]!).endpoint).toBe("/cite/validate");
  });

  it("swallows file-write errors so they don't break the caller", async () => {
    // Path that can't be opened (a directory).
    await expect(
      logBridgeCall(
        { timestamp: "t", endpoint: "/retrieve", durationMs: 1, outcome: "ok", httpStatus: 200, errorCategory: null },
        logDir, // a directory, not a file — write will fail
      ),
    ).resolves.toBeUndefined();
  });
});
