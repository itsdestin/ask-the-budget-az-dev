import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Search } from "../../pages/Search";
import * as api from "../../api";

// Restores the coverage deleted with the browse rewrite. Provenance is the
// point of this page: a passage that cannot be opened back to its own PDF
// page is a quote with no source.

const DOCS: api.CorpusDocument[] = [
  { doc_id: "b27", title: "FY 2027 Baseline — AHCCCS", publisher: "jlbc",
    doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/axs.pdf" },
];

const HITS: api.SearchResult[] = [
  { chunk_id: "chunk-142", doc_id: "b27", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "Child care subsidy assistance rose.", page: 142, score: 0.9,
    doc_type: "baseline-per-agency", fiscal_year: 2027, publisher: "jlbc",
    agencies: [], doc_url: "https://x/axs.pdf", doc_meta: null },
];

// PassageCard's <Quote> wraps the matched substring in a <mark>, so the
// snippet is split across sibling text nodes ("Child care" / " subsidy
// assistance rose."). Testing Library's default text matcher only reads a
// node's OWN direct text-node children (see @testing-library/dom's
// getNodeText), so a plain findByText(/regex/) can never see the whole
// phrase once it's highlighted — confirmed by running the brief's verbatim
// regex matcher against this exact markup and hitting RTL's own "text is
// broken up by multiple elements" hint. This matcher targets the wrapping
// `.doc-quote` span by its full textContent instead, which is unaffected by
// how highlight() split it internally.
const PASSAGE_TEXT = "Child care subsidy assistance rose.";
function findPassageQuote() {
  return screen.findByText((_content, node) => {
    if (!node || !(node instanceof Element)) return false;
    return node.classList.contains("doc-quote") && node.textContent === PASSAGE_TEXT;
  });
}

function mount() {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  vi.spyOn(api, "search").mockResolvedValue({ results: HITS, total: 1, provider: "test" });
  vi.spyOn(api, "chunk").mockResolvedValue({
    chunk_id: "chunk-142", doc_id: "b27", page: 142, bbox: null,
    text: "Child care subsidy assistance rose.", source_format: "pdf",
    pdf_unavailable_reason: null,
  });
  render(
    <MemoryRouter initialEntries={["/search?q=child%20care&in=contents"]}>
      <Search />
    </MemoryRouter>,
  );
}

test("clicking a passage opens the source drawer for THAT chunk", async () => {
  mount();
  fireEvent.click(await findPassageQuote());
  expect(await screen.findByRole("complementary", { name: /source passage/i }))
    .toBeInTheDocument();
  await waitFor(() => expect(api.chunk).toHaveBeenCalledWith("chunk-142", "budget"));
});

test("the drawer opens from the KEYBOARD — provenance is not mouse-only", async () => {
  mount();
  const row = (await findPassageQuote()).closest("button")!;
  row.focus();
  fireEvent.click(row); // a real <button> activates on Enter/Space via click
  expect(await screen.findByRole("complementary", { name: /source passage/i }))
    .toBeInTheDocument();
});

test("switching modes closes the drawer", async () => {
  mount();
  fireEvent.click(await findPassageQuote());
  await screen.findByRole("complementary", { name: /source passage/i });
  fireEvent.click(screen.getByRole("button", { name: /back to title matches/i }));
  await waitFor(() =>
    expect(screen.queryByRole("complementary", { name: /source passage/i })).toBeNull(),
  );
});
