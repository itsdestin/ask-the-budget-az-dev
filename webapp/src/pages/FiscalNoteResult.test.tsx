// The retrieval result card (spec F11-F13, F16, F17).

import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, vi } from "vitest";
import type { SearchResult } from "../api";
import type { PassageDoc } from "../search/contentSearch";
import { FiscalNoteResult } from "./FiscalNoteResult";

const SNAPSHOT = JSON.parse(
  readFileSync(resolve(__dirname, "../../../app/data/fiscal-notes-snapshot.json"), "utf-8"),
) as { sessions: { bills: { bill_number: string; title: string }[] }[] };

/** A REAL struck title out of the corpus — one of 241. Not invented: this whole class of
 *  defect is invisible to hand-written fixtures, which is how it survived the draft. */
const STRUCK = (() => {
  for (const s of SNAPSHOT.sessions) {
    for (const b of s.bills) if (b.title.includes("<strike>") && b.title.includes("NOW:")) return b;
  }
  throw new Error("no struck title in the snapshot — the fixture assumption changed");
})();

function passage(over: Partial<SearchResult> = {}): SearchResult {
  return {
    chunk_id: "c1",
    doc_id: "fn-2026-hb2172",
    doc_title: "Fiscal Note - HB 2407: victim notification",
    snippet: "short",
    text: "The bill would appropriate $28,700,000 from the General Fund for inmates.",
    page: 2,
    score: 4.2,
    doc_type: "fiscal-note",
    fiscal_year: 2026,
    publisher: "azleg",
    agencies: [],
    doc_url: null,
    doc_meta: "Estimated Impact",
    section_of: null,
    ...over,
  } as SearchResult;
}

function note(...passages: SearchResult[]): PassageDoc {
  return {
    doc_id: passages[0].doc_id,
    doc_title: passages[0].doc_title,
    publisher: passages[0].publisher,
    passages,
  };
}

function mount(over: Partial<Parameters<typeof FiscalNoteResult>[0]> = {}) {
  return render(
    <FiscalNoteResult
      note={note(passage())}
      sessionLabel="2026 (57th Legislature, 2nd Regular Session)"
      query="inmates"
      open={false}
      onToggle={vi.fn()}
      {...over}
    />,
  );
}

test("the bill number and title are one line, in two weights", () => {
  // F16: built from the RETRIEVAL title, which is prefixed and colon-separated — not from
  // the browse row's title. A card on a page called "Fiscal Notes" must not open with the
  // words "Fiscal Note".
  const { container } = mount();
  expect(container.querySelector(".res-no")?.textContent).toBe("HB 2407");
  expect(container.textContent).toContain("victim notification");
  expect(container.textContent).not.toContain("Fiscal Note -");
});

test("a struck title renders through BillTitle, never as raw HTML", () => {
  // Note what is asserted and what is NOT. The strikethrough must SURVIVE: it is the only
  // thing on screen saying this bill's title was REPLACED, which is the entire meaning of
  // the "(NOW: ...)" form. What must never happen is the raw scraped string reaching the
  // DOM as characters, or reaching it through dangerouslySetInnerHTML.
  const { container } = mount({
    note: note(passage({ doc_title: `Fiscal Note - HB 2172: ${STRUCK.title}` })),
  });

  expect(container.innerHTML).not.toContain("&lt;strike&gt;");
  expect(container.innerHTML).not.toContain("<strike>");
  expect(container.textContent).not.toContain("<strike>");
  // The struck words are struck, and the replacement sits beside them unstruck.
  expect(container.querySelector("s")).not.toBeNull();
  expect(container.querySelector("s")!.textContent!.length).toBeGreaterThan(0);
  expect(container.textContent).toContain("NOW:");
});

test("exactly one passage, and exactly one interactive element", () => {
  // F11: no tray, no "N more passages". F13: the whole card is ONE button, so its "Open
  // note" pill is a decorative span. A nested button or anchor is invalid HTML that jsdom
  // renders happily, so pin the absence directly.
  const { container } = mount({
    note: note(passage({ chunk_id: "best", score: 9 }), passage({ chunk_id: "other", score: 1 })),
  });

  expect(container.querySelectorAll(".doc-quote")).toHaveLength(1);
  expect(container.querySelectorAll("button")).toHaveLength(1);
  expect(container.querySelectorAll("button button, button a")).toHaveLength(0);
  expect(screen.queryByText(/more passages?/i)).not.toBeInTheDocument();
});

test("the pill reads 'Close note' while this card's drawer is open", () => {
  // The card is a TOGGLE, not a one-way action, so its label has to say which way it goes.
  expect(mount({ open: false }).container.textContent).toContain("Open note");
  expect(mount({ open: true }).container.textContent).toContain("Close note");
});

test("clicking the card hands back the BEST passage's chunk", () => {
  const onToggle = vi.fn();
  const { container } = mount({
    note: note(passage({ chunk_id: "best", score: 9 }), passage({ chunk_id: "weak", score: 1 })),
    onToggle,
  });
  (container.querySelector("[data-testid=fn-result]") as HTMLElement).click();
  expect(onToggle).toHaveBeenCalledWith("best");
});

test("the session line is what the caller joined, not a bare year", () => {
  // F4: a search result carries only `fiscal_year`; the session NAME lives in the browse
  // directory. The failure this pins is silent — a missed join renders a blank line or a
  // naked "2026", and nothing errors.
  const { container } = mount();
  expect(container.querySelector(".res-year")?.textContent)
    .toBe("2026 (57th Legislature, 2nd Regular Session)");
});

test("typed words are marked, and a mark never splits a word", () => {
  // F17: word boundaries at BOTH ends, matching the shipped highlightTerms(). Anchoring
  // only the front highlights "inmate" inside "inmates" and leaves the "s" outside the
  // mark, which renders as a highlighted word with a loose letter drifting after it.
  const { container } = mount({ query: "inmate" });
  expect(container.querySelectorAll("mark")).toHaveLength(0);

  const marked = mount({ query: "inmates" }).container;
  expect([...marked.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["inmates"]);
});

test("the excerpt is the passage's FULL text, not the 280-char snippet", () => {
  const { container } = mount();
  expect(container.querySelector(".doc-quote")?.textContent).toContain("General Fund for inmates");
});

test("a missing section legend is omitted, not faked", () => {
  const { container } = mount({ note: note(passage({ doc_meta: null })) });
  expect(container.querySelector(".exc-lbl")).toBeNull();
  expect(container.querySelector(".exc")).not.toBeNull();
});

test("no page reference on the card", () => {
  // F12: the page still names itself in the DRAWER's breadcrumb, which is where the reader
  // is actually looking at it. On the card it was noise competing with the title.
  const { container } = mount();
  expect(container.textContent).not.toMatch(/\bp\.\s*\d/);
});
