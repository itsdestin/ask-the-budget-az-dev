import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import Footer from "../Footer";

describe("Footer", () => {
  it("renders the honesty line (Core Invariant 5)", () => {
    const html = renderToString(<Footer connected={true} />);
    expect(html).toContain("Answers are cited, not guaranteed");
    expect(html).toContain("JLBC");
  });

  it("must never claim the system is hallucination-free", () => {
    const html = renderToString(<Footer connected={true} />).toLowerCase();
    expect(html).not.toContain("hallucination-free");
    expect(html).not.toContain("grounded");
  });
});
