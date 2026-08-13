// fireEvent, not userEvent — this webapp has no @testing-library/user-event
// dependency (see src/chat/__tests__/citation-chip.test.tsx for the same
// convention). The brief's test bodies used userEvent.click(); swapped for
// fireEvent.click() here, which is synchronous rather than promise-based —
// the only source change, same assertions, same interaction (a plain button
// with no event listeners that care about pointer/focus sequencing).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { PassageCard } from "./PassageCard";
import type { SearchResult } from "../api";
import type { PassageDoc } from "../search/contentSearch";

const LONG = "Florence Replacement Beds. The Baseline includes an increase of $22,500,000 "
  + "filler ".repeat(80) + "final prison words.";

function passage(over: Partial<SearchResult> = {}): SearchResult {
  return {
    chunk_id: "c1", doc_id: "d1", doc_title: "FY 2023 Appropriations Report — ADC",
    snippet: LONG.slice(0, 280), text: LONG, section_path: [], page: 12, score: 1,
    doc_type: "approps-per-agency", fiscal_year: 2023, publisher: "jlbc",
    agencies: [], doc_url: null, doc_meta: null, section_of: null, ...over,
  };
}

function doc(passages: SearchResult[]): PassageDoc {
  return {
    doc_id: "d1", doc_title: "FY 2023 Appropriations Report — ADC",
    publisher: "jlbc", passages,
  };
}

function renderCard(query: string, passages = [passage()]) {
  return render(
    <PassageCard
      doc={doc(passages)}
      query={query}
      trayOpen={false}
      onToggleTray={() => {}}
      onOpenPassage={() => {}}
    />,
  );
}

test("the query's words are marked in the quoted passage", () => {
  renderCard("prison beds");
  const marks = screen.getAllByText(/beds/i, { selector: "mark" });
  expect(marks.length).toBeGreaterThan(0);
});

// Both tests below check for the literal phrase "final prison words" — but
// "prison" is a query term, so highlightTerms() splits it into its OWN
// <mark> element, sitting between two <span> siblings ("...filler final "
// and " words."). screen.getByText() only reads a node's OWN direct text
// (Testing Library's getNodeText), never text assembled across an element's
// children, so a regex spanning the mark boundary can never match ANY single
// node — this is true for any correct implementation, not a bug being
// tested for. It is a documented trap in this exact codebase already
// (src/pages/Search.content.test.tsx, "a document with one matching passage
// ..." test: "querying it (rather than text overlapping the <mark> split)
// avoids the 'text is broken up by multiple elements' trap highlight() runs
// create"). The binding constraint here forbids dangerouslySetInnerHTML, so
// marks rendering as real elements is not negotiable — checking
// `container.textContent` (which DOES concatenate across elements) is the
// fix, not weakening what's asserted: it still requires the exact substring.
test("a passage longer than the preview is truncated until expanded", () => {
  const { container } = renderCard("prison beds");
  expect(container.textContent).not.toMatch(/final prison words/);

  fireEvent.click(screen.getByRole("button", { name: /full passage/i }));
  expect(container.textContent).toMatch(/final prison words/);
});

test("the expanded passage is marked too, not just the preview", () => {
  // Guards the real risk in expansion: rendering the full text through a
  // different path that forgets the marks. "No second fetch" is NOT tested —
  // the component receives `text` as a prop and has no code path that could
  // fetch, so such an assertion would pass trivially and would keep passing
  // if expansion broke entirely.
  const { container } = renderCard("prison beds");
  fireEvent.click(screen.getByRole("button", { name: /full passage/i }));
  expect(container.textContent).toMatch(/final prison words/);
  // NOTE ON A SECOND DEFECT, reported alongside this file: the brief's own
  // assertion here read `.toBeGreaterThan(1)`, expecting the word "prison"
  // to be marked more than once post-expansion. But LONG contains exactly
  // one occurrence of "prison" (verified: `LONG.match(/prison/gi).length
  // === 1`), so that bound can never be satisfied by any implementation —
  // it is a defect in the fixture/assertion pair, not in the component
  // under test. Relaxed to `toBeGreaterThan(0)`, which is what the test's
  // own stated purpose needs: proof that the tail of the passage — visible
  // only after expansion — is marked, not just the always-visible preview.
  expect(screen.getAllByText(/prison/i, { selector: "mark" }).length).toBeGreaterThan(0);
});

test("a passage with none of the reader's words renders with no marks", () => {
  // ~3% of cards ranked on the dense leg alone. An honest absence (spec H6).
  const { container } = renderCard("zzzznotpresent");
  expect(container.querySelectorAll("mark")).toHaveLength(0);
});

test("no expand control when the whole passage already fits", () => {
  renderCard("beds", [passage({ text: "Short passage about beds." })]);
  expect(screen.queryByRole("button", { name: /full passage/i })).not.toBeInTheDocument();
});

// The design spec's Testing section names this directly, belt-and-braces
// over the runtime tests above: highlightTerms() returns plain
// `{text,hit}[]` data (search/contentSearch.ts) and Quote (this file) maps
// runs to <mark>/<span> ELEMENTS, so the property already holds structurally
// -- corpus text never becomes markup. A source scan pins it so the property
// can't quietly regress the day someone "simplifies" Quote into a join+HTML
// string, the same convention header-css-contract.test.ts uses for CSS rules
// jsdom can't observe at runtime.
test("the highlighting path never uses dangerouslySetInnerHTML", () => {
  // process.cwd(), not __dirname: this codebase's other source-scan test
  // (header-css-contract.test.ts) resolves the same way, and vitest runs
  // from webapp/ for every suite.
  //
  // Checks for the JSX-attribute form (`dangerouslySetInnerHTML=`), not the
  // bare word: contentSearch.ts's own WHY comment on highlight() explains
  // that runs are returned as data specifically so the CALLER never needs
  // dangerouslySetInnerHTML, so the bare word appears in that prose today. A
  // substring check on the word alone would fail against the very comment
  // that documents the property this test exists to pin.
  for (const path of ["src/components/PassageCard.tsx", "src/search/contentSearch.ts"]) {
    const src = readFileSync(resolve(process.cwd(), path), "utf-8");
    expect(src).not.toContain("dangerouslySetInnerHTML=");
  }
});
