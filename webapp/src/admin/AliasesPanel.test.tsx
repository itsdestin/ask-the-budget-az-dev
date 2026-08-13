import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { AliasesPanel } from "./AliasesPanel";

// The office's own shorthand, layered over the shipped agency list. What
// these specs protect:
//
//  1. Every mutation renders the SERVER's list. The server validates,
//     lowercases and de-duplicates; a locally appended row would show an
//     admin a mapping that does not exist.
//  2. A refusal shows the server's own sentence. Those sentences carry the
//     reason ("that word is too easy to confuse"), which is the only thing
//     that tells an admin what to type instead.
//  3. The honest limitation is on the page, in the spec's words: this
//     improves typed searches, and does nothing for documents already
//     filed.

function aliases(over: Partial<api.AdminAliases> = {}): api.AdminAliases {
  return {
    added: [
      {
        alias: "dor",
        canonical_id: "agency:rev",
        agency_name: "Revenue, Department of",
        added_by: "Destin",
        added_at: "2026-08-01T17:00:00Z",
      },
    ],
    disabled: [],
    shipped: [
      {
        alias: "adoa",
        canonical_id: "agency:doa",
        agency_name: "Administration, Arizona Department of",
      },
    ],
    agencies: [
      { canonical_id: "agency:rev", name: "Revenue, Department of" },
      { canonical_id: "agency:doa", name: "Administration, Arizona Department of" },
    ],
    warnings: [],
    ...over,
  };
}

afterEach(() => vi.restoreAllMocks());

async function renderPanel(over: Partial<api.AdminAliases> = {}) {
  vi.spyOn(api, "adminAliases").mockResolvedValue(aliases(over));
  render(<AliasesPanel />);
  await screen.findByTestId("admin-aliases");
}

/** Click a card's header by its title. Bodies genuinely are not in the DOM
 *  until then, so opening is part of proving the content is reachable. */
function openCard(title: RegExp) {
  const heading = screen
    .getAllByRole("heading", { level: 3 })
    .find((h) => title.test(h.textContent ?? ""));
  if (!heading) throw new Error(`no card titled ${title}`);
  fireEvent.click(heading.closest("button")!);
}

describe("the office's own shorthand", () => {
  it("lists what the office has added, and who added it", async () => {
    await renderPanel();
    openCard(/your office's shorthand/i);

    const table = screen.getByTestId("admin-aliases-table");
    expect(within(table).getByText("dor")).toBeInTheDocument();
    expect(within(table).getByText("Revenue, Department of")).toBeInTheDocument();
    expect(within(table).getByText("Destin")).toBeInTheDocument();
  });

  it("says plainly what a new shorthand does and does not do", async () => {
    await renderPanel();
    openCard(/your office's shorthand/i);

    // Verbatim from the design spec. The gap it names is real (documents
    // already filed were not stamped with this word), and an admin who
    // isn't told will read the feature as broken.
    expect(screen.getByTestId("admin-aliases")).toHaveTextContent(
      "Aliases apply to searches immediately. Documents already in the corpus " +
        "were catalogued without them, so a new alias improves typed searches, " +
        "not older documents' own labels.",
    );
  });

  it("adds one, and shows the row the server sent back", async () => {
    await renderPanel();
    openCard(/your office's shorthand/i);
    // The server lowercases. A panel that appended what was typed would show
    // "ADE" here and disagree with the file on the share.
    const save = vi.spyOn(api, "saveAdminAliases").mockResolvedValue(
      aliases({
        added: [
          {
            alias: "dor",
            canonical_id: "agency:rev",
            agency_name: "Revenue, Department of",
            added_by: "Destin",
            added_at: "2026-08-01T17:00:00Z",
          },
          {
            alias: "ade",
            canonical_id: "agency:doa",
            agency_name: "Administration, Arizona Department of",
            added_by: "Destin",
            added_at: "2026-08-12T17:00:00Z",
          },
        ],
      }),
    );

    fireEvent.change(screen.getByLabelText(/shorthand/i), { target: { value: "ADE" } });
    fireEvent.change(screen.getByLabelText(/^agency$/i), {
      target: { value: "agency:doa" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    // The whole list every time — the file is written as a whole.
    expect(save.mock.calls[0][0]).toEqual({
      added: [
        { alias: "dor", canonical_id: "agency:rev" },
        { alias: "ADE", canonical_id: "agency:doa" },
      ],
      disabled: [],
    });

    const table = await screen.findByTestId("admin-aliases-table");
    expect(within(table).getByText("ade")).toBeInTheDocument();
    expect(within(table).queryByText("ADE")).toBeNull();
  });

  it("removes one by sending the list without it", async () => {
    await renderPanel();
    openCard(/your office's shorthand/i);
    const save = vi
      .spyOn(api, "saveAdminAliases")
      .mockResolvedValue(aliases({ added: [] }));

    fireEvent.click(screen.getByRole("button", { name: /remove dor/i }));

    await waitFor(() => expect(save).toHaveBeenCalledWith({ added: [], disabled: [] }));
    expect(await screen.findByTestId("admin-aliases-empty")).toBeInTheDocument();
  });

  it("shows the server's own refusal, as an alert", async () => {
    await renderPanel();
    openCard(/your office's shorthand/i);
    vi.spyOn(api, "saveAdminAliases").mockRejectedValue(
      new Error(
        'save search language: "for" matches too many ordinary sentences to be used as shorthand.',
      ),
    );

    fireEvent.change(screen.getByLabelText(/shorthand/i), { target: { value: "for" } });
    fireEvent.change(screen.getByLabelText(/^agency$/i), {
      target: { value: "agency:rev" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /matches too many ordinary sentences/i,
    );
    // Nothing was stored, so nothing may be shown as stored.
    expect(within(screen.getByTestId("admin-aliases-table")).queryByText("for")).toBeNull();
  });

  it("shows a warning the server sent with an accepted save", async () => {
    await renderPanel();
    openCard(/your office's shorthand/i);
    vi.spyOn(api, "saveAdminAliases").mockResolvedValue(
      aliases({
        warnings: ['"ad" is only two letters — it may match more than you meant.'],
      }),
    );

    fireEvent.change(screen.getByLabelText(/shorthand/i), { target: { value: "ad" } });
    fireEvent.change(screen.getByLabelText(/^agency$/i), {
      target: { value: "agency:rev" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    expect(await screen.findByTestId("admin-aliases-warnings")).toHaveTextContent(
      /only two letters/i,
    );
  });
});

describe("the shorthand that ships with the app", () => {
  it("can be switched off, one at a time", async () => {
    await renderPanel();
    openCard(/shorthand that comes with the app/i);
    const save = vi
      .spyOn(api, "saveAdminAliases")
      .mockResolvedValue(aliases({ disabled: ["adoa"] }));

    const row = screen.getByTestId("admin-shipped-adoa");
    expect(within(row).getByRole("switch")).toBeChecked();
    fireEvent.click(within(row).getByRole("switch"));

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({
        added: [{ alias: "dor", canonical_id: "agency:rev" }],
        disabled: ["adoa"],
      }),
    );
    // Off because the SERVER says it is off.
    await waitFor(() =>
      expect(
        within(screen.getByTestId("admin-shipped-adoa")).getByRole("switch"),
      ).not.toBeChecked(),
    );
  });

  it("says so when the shorthand cannot be loaded at all", async () => {
    vi.spyOn(api, "adminAliases").mockRejectedValue(
      new Error("load search language failed: 500"),
    );
    render(<AliasesPanel />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/search language/i);
  });
});
