import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { toolGlyph } from "../components/tool-views/primitives";

describe("toolGlyph", () => {
  it("returns a distinct glyph element for each known tool", () => {
    const retrieve = renderToString(<svg>{toolGlyph("retrieve")}</svg>);
    const cite = renderToString(<svg>{toolGlyph("cite")}</svg>);
    expect(retrieve).not.toEqual(cite);
  });
  it("falls back for an unknown tool without throwing", () => {
    expect(() => renderToString(<svg>{toolGlyph("mystery_tool")}</svg>)).not.toThrow();
  });
});
