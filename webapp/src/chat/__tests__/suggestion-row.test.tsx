import { describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
import SuggestionRow from "../SuggestionRow";

describe("SuggestionRow", () => {
  it("renders all three suggestion strings as buttons", () => {
    const html = renderToString(<SuggestionRow onPick={vi.fn()} />);
    expect(html).toContain("Aviation Fund");
    expect(html).toContain("ADOT");
    expect(html).toContain("General Fund revenue");
    // All three are rendered as <button> elements
    const buttonCount = (html.match(/<button/g) ?? []).length;
    expect(buttonCount).toBe(3);
  });
});
