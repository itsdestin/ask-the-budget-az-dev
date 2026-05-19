import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import WelcomeHero from "../components/WelcomeHero";

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
});
