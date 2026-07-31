// Carried from web/tests/system-health-banner.test.tsx. Both original
// assertions are unchanged — role="alert" and the parenthesized reason
// passthrough — and they still pass against the rewritten copy, which opens
// "AI Mode is offline." The added cases pin the new failure modes and the one
// rule the old copy broke: never name a fix that doesn't exist.

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import SystemHealthBanner from "../SystemHealthBanner";

describe("SystemHealthBanner", () => {
  it("renders the offline message inside an alert role", () => {
    const html = renderToString(<SystemHealthBanner />);
    expect(html).toContain("role=\"alert\"");
    expect(html).toContain("offline");
  });

  it("surfaces the underlying reason in parentheses when supplied", () => {
    const html = renderToString(<SystemHealthBanner reason="HTTP 503" />);
    expect(html).toContain("HTTP 503");
  });

  it("tells the analyst to ask an admin when no API key is configured", () => {
    // Exact reason string pinned by harness/settings.py::ai_available.
    const html = renderToString(
      <SystemHealthBanner reason="no API key configured" />,
    );
    expect(html).toContain("no key");
    expect(html).toContain("admin");
  });

  it("distinguishes an unconfigured model from a missing key", () => {
    const html = renderToString(
      <SystemHealthBanner reason="no model configured — ask the admin" />,
    );
    expect(html).toContain("no model assigned");
  });

  it("names the shared drive when the document store is unreachable", () => {
    // Different remedy from the config failures: waiting can fix this one,
    // and search is NOT unaffected, so the copy must not claim it is.
    const html = renderToString(
      <SystemHealthBanner reason="corpus unavailable: lancedb table missing" />,
    );
    expect(html).toContain("shared drive");
    expect(html).not.toContain("unaffected");
  });

  it("makes no claim about Budget Search when it doesn't know the cause", () => {
    // The two config branches CAN promise search is fine, because a missing
    // key or model cannot affect it. The generic branch cannot: matching is
    // substring-based, so a store outage surfacing as a bare OSError or a
    // plain HTTP 500 lands here rather than in the store branch. Telling that
    // analyst search still works sends them to a second dead feature.
    for (const reason of [undefined, "HTTP 500", "connection refused"]) {
      const html = renderToString(<SystemHealthBanner reason={reason} />);
      expect(html).not.toContain("unaffected");
    }
  });

  it("outranks the per-answer notice visually, not just in its ARIA role", () => {
    // AssistantTurnBubble's max_steps notice is `chat-notice is-warn` with
    // role="status" — one degraded answer. This is the whole feature being
    // down, so it must not render in the same amber.
    const html = renderToString(<SystemHealthBanner />);
    expect(html).toContain("is-danger");
    expect(html).not.toContain("is-warn");
  });

  it("never names a component or command that no longer exists", () => {
    // The old copy said "start the retrieval sidecar (uv run uvicorn
    // retrieval.api:app --port 9200)" and elsewhere mentioned a YouCoded
    // session. Both are gone; telling an analyst to start them would be
    // instructions to nowhere.
    for (const reason of [
      undefined,
      "no API key configured",
      "no model configured — ask the admin",
      "corpus unavailable",
      "HTTP 500",
    ]) {
      const html = renderToString(
        <SystemHealthBanner reason={reason} />,
      ).toLowerCase();
      expect(html).not.toContain("sidecar");
      expect(html).not.toContain("youcoded");
      expect(html).not.toContain("uvicorn");
      expect(html).not.toContain("9200");
    }
  });
});
