import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import Footer from "../Footer";

describe("Footer", () => {
  it("renders the honesty line (Core Invariant 5)", () => {
    const html = renderToString(<Footer />);
    expect(html).toContain("Answers are cited, not guaranteed");
    expect(html).toContain("JLBC");
  });

  it("must never claim the system is hallucination-free", () => {
    const html = renderToString(<Footer />).toLowerCase();
    expect(html).not.toContain("hallucination-free");
    expect(html).not.toContain("grounded");
  });

  // Plan 3 shipped a GUI upload queue, so a hardcoded corpus size is wrong
  // the first time anyone adds a document — and nothing in the app would
  // notice. This footer's whole job is stating limits honestly, so it may
  // not carry a number it cannot verify. Plan 5 Task 19 restores the count
  // by reading it live; these two specs are what keep that honest.
  it("states no corpus size before the server has answered", () => {
    // renderToString runs no effects, so this is exactly the first paint:
    // fetch in flight, nothing known yet.
    const html = renderToString(<Footer />);
    expect(html).not.toMatch(/\d+\s*docs?/i);
    expect(html).not.toMatch(/\d+\s*documents/i);
    expect(html).not.toMatch(/FY\s*\d{2,4}/i);
  });

  it("states the count it was given, grouped", () => {
    const html = renderToString(
      <Footer documentCount={3527} />,
    );
    expect(html).toContain("3,527 documents");
  });

  it("says nothing about whether AI Mode is working", () => {
    // Destin, 2026-08-02: "if it's working, the analyst doesn't need separate
    // text telling them so." A live composer is the message. The failing case
    // did carry information and was NOT dropped — it became the whole
    // unavailable screen (see Ai.test.tsx), which is the right weight for a
    // condition that stops the page doing its job.
    const html = renderToString(<Footer />);
    expect(html).not.toContain("AI Mode available");
    expect(html).not.toContain("AI Mode unavailable");
  });
});
