// Carried from web/tests/tool-card.test.tsx. The two original assertions are
// unchanged; a third was added for create_document, the tool Plan 4 introduced.

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { toolGlyph } from "../tool-views/primitives.js";

describe("toolGlyph", () => {
  it("returns a distinct glyph element for each known tool", () => {
    const retrieve = renderToString(<svg>{toolGlyph("retrieve")}</svg>);
    const cite = renderToString(<svg>{toolGlyph("cite")}</svg>);
    expect(retrieve).not.toEqual(cite);
  });

  it("falls back for an unknown tool without throwing", () => {
    expect(() =>
      renderToString(<svg>{toolGlyph("mystery_tool")}</svg>),
    ).not.toThrow();
  });

  it("gives create_document its own glyph, not the fallback square", () => {
    const created = renderToString(<svg>{toolGlyph("create_document")}</svg>);
    const fallback = renderToString(<svg>{toolGlyph("mystery_tool")}</svg>);
    expect(created).not.toEqual(fallback);
  });
});
