import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type * as api from "../api";
import { CostsPanel } from "./CostsPanel";

// The table lives inside a CollapsibleCard that defaults to collapsed, so
// every test opens it first.

// The one thing this test pins: the raw tier key "title" must never reach
// the admin's page. An admin who sees "title" next to "standard" and
// "deep_research" has no way to tell what it is — the display map turns it
// into "Chat naming" so it reads as a sentence in the same voice as the
// other two. The stored key stays "title" (renaming it would orphan every
// row already written); only the rendering changes.

function usage(over: Partial<api.AdminUsage> = {}): api.AdminUsage {
  return {
    month: "2026-08",
    total_usd: 0.5,
    rows: 10,
    rows_with_unknown_cost: 0,
    cached_tokens: 0,
    tokens_in: 1000,
    by_user: [],
    by_model: [],
    by_tier: [
      { key: "standard", cost_usd: 0.3, tokens_in: 500, tokens_out: 200, cached_tokens: 0, rows: 8, rows_with_unknown_cost: 0 },
      { key: "title", cost_usd: 0.0001, tokens_in: 50, tokens_out: 6, cached_tokens: 0, rows: 2, rows_with_unknown_cost: 0 },
    ],
    limits_active: true,
    limits_inactive_reason: null,
    ...over,
  };
}

describe("CostsPanel tier labels", () => {
  it("shows 'Chat naming' for the title tier, not the raw key", () => {
    render(
      <CostsPanel
        usage={usage()}
        month="2026-08"
        onMonthChange={() => {}}
        tab="by_tier"
        onTabChange={() => {}}
        isCustomEndpoint={false}
      />,
    );
    // The breakdown table is inside a CollapsibleCard — open it first.
    fireEvent.click(screen.getByText("Show"));
    expect(screen.getByText("Chat naming")).toBeInTheDocument();
    // The raw key must not appear as a row label — it would read as a
    // mystery word next to "Standard" and "Deep Research".
    expect(screen.queryByText("title")).not.toBeInTheDocument();
  });

  it("still shows Standard and Deep Research with their display names", () => {
    render(
      <CostsPanel
        usage={usage()}
        month="2026-08"
        onMonthChange={() => {}}
        tab="by_tier"
        onTabChange={() => {}}
        isCustomEndpoint={false}
      />,
    );
    fireEvent.click(screen.getByText("Show"));
    expect(screen.getByText("Standard")).toBeInTheDocument();
  });

  it("falls back to the raw key for an unknown tier", () => {
    // A future tier or a corrupt row should still render SOMETHING, not a
    // blank cell.
    const u = usage({
      by_tier: [
        { key: "platinum", cost_usd: 0.1, tokens_in: 0, tokens_out: 0, cached_tokens: 0, rows: 1, rows_with_unknown_cost: 0 },
      ],
    });
    render(
      <CostsPanel
        usage={u}
        month="2026-08"
        onMonthChange={() => {}}
        tab="by_tier"
        onTabChange={() => {}}
        isCustomEndpoint={false}
      />,
    );
    fireEvent.click(screen.getByText("Show"));
    expect(screen.getByText("platinum")).toBeInTheDocument();
  });

  it("does not apply tier labels on the by_user or by_model tabs", () => {
    // The label map is for the "By answer mode" tab only — on "By person"
    // a user named "title" should render as "title", not "Chat naming".
    const u = usage({
      by_user: [
        { key: "title", cost_usd: 0.1, tokens_in: 0, tokens_out: 0, cached_tokens: 0, rows: 1, rows_with_unknown_cost: 0 },
      ],
    });
    render(
      <CostsPanel
        usage={u}
        month="2026-08"
        onMonthChange={() => {}}
        tab="by_user"
        onTabChange={() => {}}
        isCustomEndpoint={false}
      />,
    );
    fireEvent.click(screen.getByText("Show"));
    expect(screen.getByText("title")).toBeInTheDocument();
  });
});
