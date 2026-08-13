import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { GuidancePanel } from "./GuidancePanel";

// "See System Guidance" — the read-only window onto everything the
// assistant is already told (Destin, 2026-08-12).
//
// The problem it solves: the office guidance box above it is written
// blind. An admin who cannot see the ~1,170 lines of instructions already
// in place duplicates them, contradicts them, or spends the whole
// 8,192-byte allowance restating something already said at length.
//
// What these specs protect, in order of how badly they fail when broken:
//
//  1. The window shows EVERYTHING, grouped. If a group silently stops
//     rendering, the admin is back to writing blind but now believes they
//     have checked.
//  2. Their own guidance is marked where it lands. Without it the admin
//     cannot tell "what I wrote" from "what shipped".
//  3. The size line. It is the only thing that makes 8,192 bytes read as a
//     small addition rather than as the whole budget.
//  4. Read-only. There is no way to edit any of this from here, ever.
//  5. Plain words in the app's OWN copy — the quoted instructions are the
//     assistant's own text and are shown verbatim, on purpose.

function section(
  heading: string,
  over: Partial<api.PromptSection> = {},
): api.PromptSection {
  return {
    heading,
    text: `The words under ${heading}.`,
    is_office_guidance: false,
    subsections: [],
    ...over,
  };
}

function prompt(over: Partial<api.AdminPrompt> = {}): api.AdminPrompt {
  return {
    corpus: "budget",
    lead: "# Ask the Budget AZ — assistant instructions",
    groups: [
      {
        label: "What the assistant is, and how it decides",
        sections: [section("Your role")],
      },
      {
        label: "Arizona budget background",
        sections: [
          section("Reading budget documents", {
            subsections: [
              {
                heading: "Accuracy hierarchy for actuals",
                text: "The AFR wins for actual spending.",
              },
            ],
          }),
        ],
      },
    ],
    total_lines: 1169,
    total_bytes: 58900,
    office_guidance_present: false,
    ...over,
  };
}

function guidance(): api.AdminGuidance {
  return {
    text: "Prefer the AFR for actual spending.",
    max_bytes: 8192,
    edited_by: "Destin",
    edited_at: "2026-08-01T17:00:00Z",
  };
}

afterEach(() => vi.restoreAllMocks());

/** Render the panel with both reads stubbed, and return the spy on the
 *  instructions read so a spec can assert it was NOT called yet. */
async function renderPanel(over: Partial<api.AdminPrompt> = {}) {
  vi.spyOn(api, "adminGuidance").mockResolvedValue(guidance());
  const spy = vi.spyOn(api, "adminPrompt").mockResolvedValue(prompt(over));
  render(<GuidancePanel />);
  await screen.findByTestId("admin-guidance");
  return spy;
}

/** The payload shape once the office HAS written something: their block is
 *  a real section, in its own group, shown last. */
const WITH_OFFICE_GUIDANCE: Partial<api.AdminPrompt> = {
  office_guidance_present: true,
  groups: [
    {
      label: "What the assistant is, and how it decides",
      sections: [section("Your role")],
    },
    {
      label: "Your office's own guidance",
      sections: [
        section("Office guidance from the administrator", {
          is_office_guidance: true,
        }),
      ],
    },
  ],
};

async function openWindow(over: Partial<api.AdminPrompt> = {}) {
  const spy = await renderPanel(over);
  // Focused before the click because jsdom does not focus a button on click
  // the way a browser does, and the dialog's focus RESTORE is measured
  // against wherever focus actually was when it opened.
  const trigger = screen.getByTestId("admin-see-system");
  trigger.focus();
  fireEvent.click(trigger);
  await screen.findByRole("dialog");
  return spy;
}

describe("the See System Guidance button", () => {
  it("is the only thing about the shipped instructions on the panel", async () => {
    const spy = await renderPanel();
    // Destin's call: everything is behind one button, so the panel stays a
    // place to WRITE guidance rather than a wall of somebody else's.
    expect(screen.getByTestId("admin-see-system")).toHaveTextContent(
      "See System Guidance",
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    // The panel BODY, which is what the name claims and what this spec used
    // to leave unchecked: no group labels, no headings, no quoted words.
    const panel = screen.getByTestId("admin-guidance");
    expect(panel).not.toHaveTextContent(/Your role/);
    expect(panel).not.toHaveTextContent(/Reading budget documents/);
    expect(panel).not.toHaveTextContent(/What the assistant is, and how it decides/);
    expect(panel).not.toHaveTextContent(/The words under/);
    expect(within(panel).queryAllByTestId("sysg-group-label")).toHaveLength(0);
    // And nothing is fetched until asked for — this read is the whole set
    // of instructions, tens of thousands of characters nobody asked to see.
    expect(spy).not.toHaveBeenCalled();
  });

  it("opens a window even when the office's own guidance failed to load", async () => {
    // The two reads are independent. A share hiccup on one must not take
    // away the admin's ability to read the other.
    vi.spyOn(api, "adminGuidance").mockRejectedValue(new Error("load office guidance failed: 500"));
    vi.spyOn(api, "adminPrompt").mockResolvedValue(prompt());
    render(<GuidancePanel />);
    fireEvent.click(await screen.findByTestId("admin-see-system"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});

describe("the System guidance window", () => {
  it("groups the instructions under plain labels", async () => {
    await openWindow();
    const labels = screen.getAllByTestId("sysg-group-label").map((h) => h.textContent);
    expect(labels).toEqual([
      "What the assistant is, and how it decides",
      "Arizona budget background",
    ]);
  });

  it("keeps each section shut until it is asked for, then shows its words", async () => {
    await openWindow();
    const card = screen.getByRole("button", { name: /Your role/ });
    expect(screen.queryByText(/The words under Your role\./)).toBeNull();

    fireEvent.click(card);
    expect(screen.getByText(/The words under Your role\./)).toBeInTheDocument();
  });

  it("shows the parts within a section, where the detail actually lives", async () => {
    await openWindow();
    fireEvent.click(screen.getByRole("button", { name: /Reading budget documents/ }));
    fireEvent.click(screen.getByRole("button", { name: /Accuracy hierarchy for actuals/ }));
    expect(screen.getByText(/The AFR wins for actual spending\./)).toBeInTheDocument();
  });

  it("switches between the two sets of documents", async () => {
    const spy = await openWindow();
    expect(spy).toHaveBeenCalledWith("budget");

    spy.mockResolvedValue(
      prompt({
        corpus: "fiscal_notes",
        groups: [
          {
            label: "Arizona budget background",
            sections: [section("Reading fiscal notes")],
          },
        ],
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Fiscal notes" }));

    await waitFor(() => expect(spy).toHaveBeenCalledWith("fiscal_notes"));
    expect(
      await screen.findByRole("button", { name: /Reading fiscal notes/ }),
    ).toBeInTheDocument();
  });

  it("shows the words above the first heading, which are read too", async () => {
    // These were dropped on the floor (review, 2026-08-12): the splitter
    // returned only the sections, so the document's own title line — which
    // the assistant really does read — never reached a window captioned as
    // showing everything it is told.
    await openWindow();
    expect(screen.getByTestId("sysg-lead")).toHaveTextContent(
      /Ask the Budget AZ — assistant instructions/,
    );
  });

  it("marks where the office's own guidance lands", async () => {
    await openWindow(WITH_OFFICE_GUIDANCE);
    expect(screen.getByTestId("sysg-mine")).toHaveTextContent(
      /Office guidance from the administrator/,
    );
    expect(screen.getByTestId("sysg-mine")).toHaveTextContent(/written by your office/i);
  });

  it("says the office's words are NOT the last thing the assistant reads", async () => {
    // The honesty defect this pins (review, 2026-08-12). The group is shown
    // last because that is where an admin looks for their own words — but
    // the block renders MID-way through, with the refusal rules after it.
    // An admin who believes theirs comes last writes overrides that the
    // shipped rules then beat, and never finds out why.
    await openWindow(WITH_OFFICE_GUIDANCE);
    const note = screen.getByTestId("sysg-position");
    expect(note).toHaveTextContent(/the assistant does not read it last/i);
    expect(note).toHaveTextContent(/several sections come after it/i);
    expect(note).toHaveTextContent(/refuse to answer/i);
    expect(note).toHaveTextContent(/those rules win/i);
  });

  it("does not claim a position for guidance nobody has written", async () => {
    await openWindow();
    expect(screen.queryByTestId("sysg-position")).toBeNull();
  });

  it("says so when the office has written nothing yet", async () => {
    await openWindow();
    // Otherwise an admin hunts the list for their own words and concludes
    // the save never landed.
    expect(screen.getByTestId("sysg-size")).toHaveTextContent(
      /Your office has not written any guidance yet/i,
    );
  });

  it("sizes the whole thing against what the office may add", async () => {
    await openWindow();
    const size = screen.getByTestId("sysg-size");
    expect(size).toHaveTextContent("1,169 lines");
    // Bytes on both halves of the comparison — the guidance cap is a byte
    // cap, and this text is full of em dashes at 3 bytes each.
    expect(size).toHaveTextContent("58 KB");
    expect(size).toHaveTextContent("up to 8.0 KB");
  });

  it("stops saying the office's guidance is 'added to this' once it is in it", async () => {
    // The total is the RENDERED instructions, and a saved guidance block is
    // already inside that number — so the old sentence counted it twice
    // (review, 2026-08-12).
    await openWindow(WITH_OFFICE_GUIDANCE);
    const size = screen.getByTestId("sysg-size");
    expect(size).toHaveTextContent(/your office's own guidance included/i);
    expect(size).not.toHaveTextContent(/added to this/i);
    expect(size).not.toHaveTextContent(/has not written any guidance/i);
    // The cap is still on screen — it is the number an admin is writing to.
    expect(size).toHaveTextContent("up to 8.0 KB");
  });

  it("offers nothing that could change any of it", async () => {
    await openWindow();
    const dialog = screen.getByRole("dialog");
    // Guard the guard: every "there is no X" below would pass against an
    // empty <div role="dialog"/>, so first prove the instructions are on
    // screen at all.
    expect(within(dialog).getByRole("button", { name: /Your role/ })).toBeInTheDocument();

    expect(
      dialog.querySelectorAll("input, textarea, select, [contenteditable]"),
    ).toHaveLength(0);
    expect(within(dialog).queryByRole("textbox")).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /save/i })).toBeNull();
    // Every control in the window is a way to READ: close it, switch which
    // documents are shown, or open a card. Nothing else is offered.
    const controls = within(dialog)
      .getAllByRole("button")
      .map((b) => (b.getAttribute("aria-label") ?? b.textContent ?? "").trim());
    expect(controls.length).toBeGreaterThan(0);
    for (const name of controls) {
      expect(name).toMatch(/^(Close|Budget documents|Fiscal notes|.*(Show|Hide))$/);
    }
    expect(dialog).toHaveTextContent(/You can read this, but not change it/i);
  });

  it("never puts a deeper heading above a shallower one", async () => {
    // The group label used to be an <h4> sitting above each card's <h3>,
    // so the window's outline ran backwards for anyone reading it by
    // structure — a screen reader, or the browser's own outline view.
    await openWindow();
    const level = (el: Element) => Number(el.tagName.slice(1));
    const label = screen.getAllByTestId("sysg-group-label")[0];
    const card = within(screen.getByRole("dialog")).getByRole("button", {
      name: /Your role/,
    });
    const cardHeading = card.querySelector("h1,h2,h3,h4,h5,h6");
    expect(cardHeading).not.toBeNull();
    expect(level(label)).toBeLessThanOrEqual(level(cardHeading!));
  });

  it("closes on Escape and puts focus back on the button that opened it", async () => {
    await openWindow();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByTestId("admin-see-system")).toHaveFocus();
  });

  it("says so in a plain sentence when the instructions cannot be read", async () => {
    vi.spyOn(api, "adminGuidance").mockResolvedValue(guidance());
    vi.spyOn(api, "adminPrompt").mockRejectedValue(
      new Error("load the assistant's instructions failed: 500"),
    );
    render(<GuidancePanel />);
    fireEvent.click(await screen.findByTestId("admin-see-system"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /load the assistant's instructions/i,
    );
  });

  it("keeps developer vocabulary out of the app's own words", async () => {
    // The same guard as pages/Admin.test.tsx's "keeps developer vocabulary
    // off the page", applied with the window OPEN — that one runs with
    // every card collapsed, so it would never see any of this.
    //
    // The QUOTED instructions are exempt and are marked `data-quoted` in
    // the markup: they are the assistant's own text, shown verbatim
    // because the entire point of the window is to show exactly what it
    // reads. One shipped heading really is "What this corpus contains",
    // and relabelling it here would make the page lie about the thing it
    // exists to reveal.
    //
    // The exemption is exactly the quoted heading and the quoted <pre>.
    // It used to be a wrapper around whole cards (review, 2026-08-12),
    // which also exempted the app's OWN chrome — the "written by your
    // office" hint and each card's Show/Hide label — so the guard below
    // never saw them. Opened with the office block present so the position
    // note is checked too.
    await openWindow(WITH_OFFICE_GUIDANCE);
    const dialog = screen.getByRole("dialog").cloneNode(true) as HTMLElement;
    dialog.querySelectorAll("[data-quoted]").forEach((n) => n.remove());
    const text = dialog.textContent?.toLowerCase() ?? "";
    // The guard is worthless if the strip took the page with it: the app's
    // own words must still be here to check.
    expect(text).toContain("written by your office");
    expect(text).toContain("show");
    expect(text).toContain("the assistant does not read it last");

    for (const jargon of ["endpoint", "corpus", "chunk", "prompt", "catalog", "tier"]) {
      expect(text).not.toContain(jargon);
    }
  });
});
