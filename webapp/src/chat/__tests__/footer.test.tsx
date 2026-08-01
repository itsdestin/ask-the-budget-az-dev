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

  // Plan 3 shipped a GUI upload queue, so a hardcoded corpus size is wrong
  // the first time anyone adds a document — and nothing in the app would
  // notice. This footer's whole job is stating limits honestly, so it may
  // not carry a number it cannot verify. Plan 5 Task 19 restores the count
  // by reading it live; these two specs are what keep that honest.
  it("states no corpus size before the server has answered", () => {
    // renderToString runs no effects, so this is exactly the first paint:
    // fetch in flight, nothing known yet.
    const html = renderToString(<Footer connected={true} />);
    expect(html).not.toMatch(/\d+\s*docs?/i);
    expect(html).not.toMatch(/\d+\s*documents/i);
    expect(html).not.toMatch(/FY\s*\d{2,4}/i);
  });

  it("states the count it was given, grouped", () => {
    const html = renderToString(
      <Footer connected={true} documentCount={3527} />,
    );
    expect(html).toContain("3,527 documents");
  });

  it("says whether AI Mode is usable, in text and not only by colour", () => {
    expect(renderToString(<Footer connected={true} />)).toContain(
      "AI Mode available",
    );
    expect(renderToString(<Footer connected={false} />)).toContain(
      "AI Mode unavailable",
    );
  });
});
