import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import WelcomeHero from "../WelcomeHero";

describe("WelcomeHero", () => {
  it("renders the headline and mascot (chips moved to SuggestionRow)", () => {
    // WelcomeHero no longer takes an onPick prop — suggestion chips
    // live in SuggestionRow at the page level above the input bar.
    const html = renderToString(<WelcomeHero />);
    expect(html).toContain("let&#x27;s look at the budget");
    expect(html).toContain('aria-label="JLBC budget assistant"');
    // Aviation Fund text is intentionally absent here; it lives in SuggestionRow.
    expect(html).not.toContain("Aviation Fund");
  });

  it("says nothing below the headline", () => {
    // Destin, 2026-08-02: "i want to eliminate all text below 'hi lets look at
    // the budget'". The paragraph that used to sit here named the four
    // publishers and promised a citation per claim — both of which the honesty
    // footer under the composer states permanently, so this is a deletion of
    // repetition, not of the only place either fact was stated. If a future
    // edit re-adds prose here, that footer is where it belongs instead.
    const html = renderToString(<WelcomeHero />);
    expect(html).not.toContain("<p");
    expect(html).not.toContain("Appropriations Reports");
  });
});
