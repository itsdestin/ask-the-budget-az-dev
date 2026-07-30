import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { FiscalNotes } from "./FiscalNotes";
import * as api from "../api";

const DATA = {
  sessions: [
    {
      year: 2026,
      name: "2026 Legislative Session",
      bills: [
        {
          bill_number: "HB2001",
          title: "appropriations; K-12 rollover",
          chamber: "H" as const,
          fiscal_note_url: "https://example.gov/hb2001.pdf",
        },
        {
          bill_number: "SB1101",
          title: "AHCCCS; provider rates",
          chamber: "S" as const,
          fiscal_note_url: "https://example.gov/sb1101.pdf",
        },
      ],
    },
    {
      year: 2025,
      name: "2025 Legislative Session",
      bills: [
        {
          bill_number: "HB2500",
          title: "school facilities; funding",
          chamber: "H" as const,
          fiscal_note_url: "https://example.gov/hb2500.pdf",
        },
      ],
    },
  ],
};

beforeEach(() => vi.spyOn(api, "fiscalNotes").mockResolvedValue(DATA));

test("renders sessions with bill cards", async () => {
  render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText("HB2001")).toBeInTheDocument());
  expect(screen.getByText(/2026 legislative session/i)).toBeInTheDocument();
});

test("chamber switcher filters", async () => {
  render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.click(screen.getByRole("button", { name: /^senate$/i }));
  expect(screen.queryByText("HB2001")).not.toBeInTheDocument();
  expect(screen.getByText("SB1101")).toBeInTheDocument();
});

test("text filter matches bill number prefix and title keywords", async () => {
  render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.change(screen.getByPlaceholderText(/filter/i), {
    target: { value: "ahcccs" },
  });
  expect(screen.getByText("SB1101")).toBeInTheDocument();
  expect(screen.queryByText("HB2001")).not.toBeInTheDocument();
});

// The snapshot spaces bill numbers ("HB 2011") and people type them unspaced, so the
// prefix test has to survive both. Pinned because the fix (collapsing whitespace on
// both sides) is invisible from the mock fixtures above, which are unspaced.
test("bill-number prefix match ignores the space in 'HB 2011'", async () => {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue({
    sessions: [
      {
        year: 2026,
        name: "2026 Legislative Session",
        bills: [
          {
            bill_number: "HB 2011",
            title: "individual income tax; subtraction; adoption",
            chamber: "H" as const,
            fiscal_note_url: "https://example.gov/hb2011.pdf",
          },
          {
            bill_number: "HB 2725",
            title: "AHCCCS; prescription drug coverage",
            chamber: "H" as const,
            fiscal_note_url: "https://example.gov/hb2725.pdf",
          },
        ],
      },
    ],
  });
  render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
  await waitFor(() => screen.getByText("HB 2011"));
  fireEvent.change(screen.getByPlaceholderText(/filter/i), {
    target: { value: "hb2011" },
  });
  expect(screen.getByText("HB 2011")).toBeInTheDocument();
  expect(screen.queryByText("HB 2725")).not.toBeInTheDocument();
});

// ~241 of the 2,126 real titles carry raw <strike> markup from the source page. React
// escapes strings, so rendering the title as-is would show literal "<strike>" tags to
// users; using dangerouslySetInnerHTML on scraped text would inject them. This pins the
// third path: parse the known pattern into real elements.
test("a struck-and-renamed title renders as real elements, never as tag text", async () => {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue({
    sessions: [
      {
        year: 2026,
        name: "2026 Legislative Session",
        bills: [
          {
            bill_number: "HB2002",
            title:
              "<strike>DCS; intake hotline; multiple reports</strike> (NOW: deficiencies; denial; credentialing)",
            chamber: "H" as const,
            fiscal_note_url: "https://example.gov/hb2002.pdf",
          },
        ],
      },
    ],
  });
  const { container } = render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
  await waitFor(() => screen.getByText("HB2002"));

  // The struck old title is a real <s> element…
  const struck = container.querySelector("s");
  expect(struck).not.toBeNull();
  expect(struck).toHaveTextContent("DCS; intake hotline; multiple reports");
  // …the renamed title survives as text…
  expect(screen.getByText(/NOW: deficiencies; denial; credentialing/)).toBeInTheDocument();
  // …and no user ever sees the tag itself.
  expect(container.textContent).not.toContain("<strike>");
  expect(container.textContent).not.toContain("</strike>");
});

// The title filter must match the words a user can SEE. Matching the raw string would
// let "strike" find 241 unrelated bills and would break on the tag boundary.
test("text filter matches the visible words of a struck title", async () => {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue({
    sessions: [
      {
        year: 2026,
        name: "2026 Legislative Session",
        bills: [
          {
            bill_number: "HB2002",
            title: "<strike>light rail expansion; prohibition</strike> (NOW: feasibility review)",
            chamber: "H" as const,
            fiscal_note_url: "https://example.gov/hb2002.pdf",
          },
        ],
      },
    ],
  });
  render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
  await waitFor(() => screen.getByText("HB2002"));
  const box = screen.getByPlaceholderText(/filter/i);

  fireEvent.change(box, { target: { value: "strike" } });
  expect(screen.queryByText("HB2002")).not.toBeInTheDocument();

  fireEvent.change(box, { target: { value: "feasibility" } });
  expect(screen.getByText("HB2002")).toBeInTheDocument();
});

test("bills link to their fiscal note PDF", async () => {
  render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
  await waitFor(() => screen.getByText("HB2001"));
  const link = screen.getByText("HB2001").closest("a");
  expect(link).toHaveAttribute("href", "https://example.gov/hb2001.pdf");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
});

test("the semantic-search box is honestly disabled until the corpus is ingested", async () => {
  render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
  await waitFor(() => screen.getByText("HB2001"));
  const box = screen.getByPlaceholderText(/semantic search across all notes/i);
  expect(box).toBeDisabled();
  expect(screen.getByText(/unlocks when the fiscal-note corpus is ingested/i)).toBeInTheDocument();
});

test("a failed load shows the backend's own detail and can be retried", async () => {
  const spy = vi
    .spyOn(api, "fiscalNotes")
    .mockRejectedValueOnce(new Error("fiscal-notes: snapshot missing"));
  render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText(/snapshot missing/)).toBeInTheDocument());

  spy.mockResolvedValue(DATA);
  fireEvent.click(screen.getByRole("button", { name: /retry/i }));
  await waitFor(() => expect(screen.getByText("HB2001")).toBeInTheDocument());
});
