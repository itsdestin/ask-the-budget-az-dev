import { describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
import WelcomeHero from "../components/WelcomeHero";

describe("WelcomeHero", () => {
  it("renders the headline, mascot, and three suggestion chips", () => {
    const html = renderToString(<WelcomeHero onPick={vi.fn()} />);
    expect(html).toContain("let&#x27;s look at the budget");
    expect(html).toContain('aria-label="JLBC budget assistant"');
    expect(html).toContain("Aviation Fund");
  });
});
