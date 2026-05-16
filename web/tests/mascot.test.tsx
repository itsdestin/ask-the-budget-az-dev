import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import MascotBody from "../components/mascot/MascotBody";

describe("MascotBody", () => {
  it("renders the JLBC cap text and does not throw", () => {
    const html = renderToString(<svg viewBox="0 0 240 320"><MascotBody /></svg>);
    expect(html).toContain("JLBC");
    expect(html).toContain("var(--mascot-cap)");
    expect(html).toContain("var(--mascot-skin)");
  });
});
