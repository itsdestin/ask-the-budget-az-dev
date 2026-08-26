import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type * as api from "../api";
import { PeoplePanel, sortPeople } from "./PeoplePanel";

// The mockup this must match:
// docs/superpowers/specs/assets/2026-08-25-user-roster-mockup/people-panel.html

function person(over: Partial<api.PersonRow>): api.PersonRow {
  return {
    key: "x", username: "x", display_name: "", name_source: "", first_seen: "2026-08-01T09:00:00-07:00",
    last_seen: "2026-08-25T09:00:00-07:00", hidden: false, spent_usd: 0,
    limit: { kind: "default", amount: null, collision: [] }, ...over,
  };
}

const PEOPLE: api.PersonRow[] = [
  person({ key: "dmoss", username: "dmoss", display_name: "Danielle Moss", spent_usd: 14.2,
    limit: { kind: "custom", amount: 25, collision: [] } }),
  person({ key: "gpaulsen", username: "gpaulsen", display_name: "Geoff Paulsen", spent_usd: 9.85,
    last_seen: "2026-08-24T09:00:00-07:00" }),
  person({ key: "bjw2", username: "bjw2", spent_usd: 3.1, last_seen: "2026-08-19T09:00:00-07:00",
    limit: { kind: "exempt", amount: null, collision: [] } }),
  person({ key: "pchen", username: "pchen", display_name: "Pat Chen", hidden: true,
    last_seen: "2026-06-30T09:00:00-07:00" }),
];

const DRAFT = {
  provider: { provider: "openrouter", base_url: "", api_key_set: true, api_key_hint: "", prompt_usd_per_m: null, completion_usd_per_m: null },
  tiers: {}, admin_username: "Destin", ai_enabled: true, default_monthly_limit_usd: 40,
  user_limits: { dmoss: 25 }, exempt_users: ["bjw2"], hidden_users: ["pchen"],
} as api.AdminSettings;

function renderPanel(over: Partial<React.ComponentProps<typeof PeoplePanel>> = {}) {
  const props = {
    people: { month: "2026-08", unreachable: false, unreadable: 0, people: PEOPLE },
    loadError: null, draft: DRAFT, onLimitChange: vi.fn(), onHiddenChange: vi.fn(), ...over,
  };
  render(<PeoplePanel {...props} />);
  return props;
}

describe("the table", () => {
  it("lists everyone who is not hidden, spend-first, username under the name", () => {
    renderPanel();
    const rows = screen.getAllByRole("row").slice(1); // minus the header
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual([
      "Danielle Mossdmoss", "Geoff Paulsengpaulsen", "No name yetbjw2",
    ]);
    expect(screen.getByRole("columnheader", { name: /spent this month/i })).toHaveAttribute("aria-sort", "descending");
  });

  it("collapses hidden people to one line with a Show pill, and expands in place", () => {
    renderPanel();
    expect(screen.getByText(/1 person hidden/)).toHaveTextContent("Pat Chen");
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByRole("rowheader", { name: /Pat Chen/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Unhide Pat Chen/ })).toBeInTheDocument();
  });

  it("hides and unhides by editing the draft's hidden_users", () => {
    const props = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Hide Geoff Paulsen/ }));
    expect(props.onHiddenChange).toHaveBeenCalledWith(["pchen", "gpaulsen"]);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: /Unhide Pat Chen/ }));
    expect(props.onHiddenChange).toHaveBeenCalledWith([]);
  });

  it("shows the limit dropdown in the right state per row", () => {
    renderPanel();
    expect(screen.getByRole("combobox", { name: /limit for Danielle Moss/i })).toHaveValue("custom");
    expect(screen.getByRole("spinbutton", { name: /amount for Danielle Moss/i })).toHaveValue(25);
    expect(screen.getByRole("combobox", { name: /limit for Geoff Paulsen/i })).toHaveValue("default");
    expect(screen.queryByRole("spinbutton", { name: /amount for Geoff Paulsen/i })).toBeNull();
    expect(screen.getByRole("combobox", { name: /limit for bjw2/i })).toHaveValue("exempt");
  });

  it("writes the right one of the two settings fields and clears the other", () => {
    const props = renderPanel();
    fireEvent.change(screen.getByRole("combobox", { name: /limit for Geoff Paulsen/i }), { target: { value: "exempt" } });
    expect(props.onLimitChange).toHaveBeenLastCalledWith("gpaulsen", "exempt", null);
    fireEvent.change(screen.getByRole("combobox", { name: /limit for bjw2/i }), { target: { value: "custom" } });
    expect(props.onLimitChange).toHaveBeenLastCalledWith("bjw2", "custom", 40); // starts at the office default
    fireEvent.change(screen.getByRole("spinbutton", { name: /amount for Danielle Moss/i }), { target: { value: "30" } });
    expect(props.onLimitChange).toHaveBeenLastCalledWith("dmoss", "custom", 30);
  });

  it("names both spellings when a limit is stored twice", () => {
    renderPanel({ people: { month: "2026-08", unreachable: false, unreadable: 0, people: [
      person({ key: "dmoss", username: "dmoss", display_name: "Danielle Moss",
        limit: { kind: "custom", amount: 25, collision: ["dmoss", "DMOSS"] } }),
    ] } });
    expect(screen.getByText(/two spellings/i)).toHaveTextContent("DMOSS");
  });

  it("says the folder could not be read rather than showing an empty table", () => {
    renderPanel({ people: { month: "2026-08", unreachable: true, unreadable: 0, people: [] } });
    expect(screen.getByRole("alert")).toHaveTextContent(/couldn't be read/i);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText(/nobody has opened/i)).toBeNull();
  });

  it("says nobody yet on a fresh install, which is a different fact", () => {
    renderPanel({ people: { month: "2026-08", unreachable: false, unreadable: 0, people: [] } });
    expect(screen.getByText(/nobody has opened the app yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reports unreadable rows as a count, never silently", () => {
    renderPanel({ people: { month: "2026-08", unreachable: false, unreadable: 2, people: PEOPLE } });
    expect(screen.getByText(/2 people's records couldn't be read/)).toBeInTheDocument();
  });

  it("uses pills, never bare link text, for every action", () => {
    const { container } = render(<PeoplePanel people={{ month: "2026-08", unreachable: false, unreadable: 0, people: PEOPLE }}
      loadError={null} draft={DRAFT} onLimitChange={vi.fn()} onHiddenChange={vi.fn()} />);
    // Assert the Show pill BEFORE clicking it: the click unmounts the hidden
    // line (and the button), so a post-click query can never see it.
    const showBtn = screen.getByRole("button", { name: "Show" });
    expect(showBtn.className).toMatch(/\badm-btn\b/);
    fireEvent.click(showBtn);
    expect(container.querySelector(".adm-link")).toBeNull();
    // Every action — Hide, Unhide, Show — is a pill. Column-sort headings are
    // headings, not actions, and are deliberately NOT in this set.
    const actions = container.querySelectorAll(".adm-people-act button, .adm-people-hidden button");
    expect(actions.length).toBeGreaterThan(0);
    for (const b of actions) expect(b.className).toMatch(/\badm-btn\b/);
    for (const h of container.querySelectorAll("thead button")) expect(h.className).not.toMatch(/adm-btn/);
  });

  it("carries no jargon", () => {
    const { container } = render(<PeoplePanel people={{ month: "2026-08", unreachable: true, unreadable: 1, people: [] }}
      loadError={null} draft={DRAFT} onLimitChange={vi.fn()} onHiddenChange={vi.fn()} />);
    for (const jargon of ["endpoint", "corpus", "chunk", "prompt caching", "catalog", "tier", "roster"]) {
      expect(container.textContent!.toLowerCase()).not.toContain(jargon);
    }
  });
});

describe("sortPeople", () => {
  const rows = PEOPLE.filter((p) => !p.hidden);

  it("sorts every column both ways", () => {
    expect(sortPeople(rows, "spent", "desc").map((p) => p.username)).toEqual(["dmoss", "gpaulsen", "bjw2"]);
    expect(sortPeople(rows, "spent", "asc").map((p) => p.username)).toEqual(["bjw2", "gpaulsen", "dmoss"]);
    expect(sortPeople(rows, "last_seen", "desc").map((p) => p.username)).toEqual(["dmoss", "gpaulsen", "bjw2"]);
    expect(sortPeople(rows, "last_seen", "asc").map((p) => p.username)).toEqual(["bjw2", "gpaulsen", "dmoss"]);
    // limit: highest amount, then office default, then no limit — reversed exactly
    expect(sortPeople(rows, "limit", "desc").map((p) => p.username)).toEqual(["dmoss", "gpaulsen", "bjw2"]);
    expect(sortPeople(rows, "limit", "asc").map((p) => p.username)).toEqual(["bjw2", "gpaulsen", "dmoss"]);
  });

  it("puts a person with no name LAST in a name sort in BOTH directions", () => {
    expect(sortPeople(rows, "person", "asc").map((p) => p.username)).toEqual(["dmoss", "gpaulsen", "bjw2"]);
    expect(sortPeople(rows, "person", "desc").map((p) => p.username)).toEqual(["gpaulsen", "dmoss", "bjw2"]);
  });

  it("clicking a heading sorts, clicking again reverses, and aria-sort says so", () => {
    renderPanel();
    const person = screen.getByRole("columnheader", { name: /person/i });
    fireEvent.click(within(person).getByRole("button"));
    expect(person).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getAllByRole("rowheader")[0]).toHaveTextContent("Danielle Moss");
    fireEvent.click(within(person).getByRole("button"));
    expect(person).toHaveAttribute("aria-sort", "descending");
    expect(screen.getAllByRole("rowheader")[0]).toHaveTextContent("Geoff Paulsen");
    expect(screen.getByRole("columnheader", { name: /spent/i })).not.toHaveAttribute("aria-sort");
  });
});

// Fix 1 (2026-08-26 final review): the limit dropdown and amount box were
// bound to `people` (the SERVER row), which never changes as the admin
// edits — so the dropdown snapped back to the server's kind and a typed
// amount was overwritten on the next render. Reproduced live before the
// fix. This wrapper mirrors Admin.tsx's `setPersonLimit` exactly (same
// mutually-exclusive-field logic, U8) and holds the draft in real React
// state, so `onLimitChange` actually flows back into what the panel
// renders — a static `draft` prop (as every other test above uses) cannot
// tell the fixed binding from the broken one, because neither ever
// re-renders from a changed draft.
function StatefulPeoplePanel({
  people, initialDraft,
}: { people: api.AdminUsers; initialDraft: api.AdminSettings }) {
  const [draft, setDraft] = useState(initialDraft);
  function onLimitChange(username: string, kind: api.PersonLimit["kind"], amount: number | null) {
    setDraft((d) => {
      const user_limits = { ...d.user_limits };
      for (const k of Object.keys(user_limits)) {
        if (k.trim().toLowerCase() === username.trim().toLowerCase()) delete user_limits[k];
      }
      const exempt_users = d.exempt_users.filter(
        (u) => u.trim().toLowerCase() !== username.trim().toLowerCase(),
      );
      if (kind === "custom") user_limits[username] = amount ?? 0;
      if (kind === "exempt") exempt_users.push(username);
      return { ...d, user_limits, exempt_users };
    });
  }
  return (
    <PeoplePanel
      people={people}
      loadError={null}
      draft={draft}
      onLimitChange={onLimitChange}
      onHiddenChange={() => {}}
    />
  );
}

describe("the limit control reads the draft, not the server row", () => {
  it("keeps a dropdown change instead of snapping back to the server's kind", () => {
    render(<StatefulPeoplePanel
      people={{ month: "2026-08", unreachable: false, unreadable: 0, people: PEOPLE }}
      initialDraft={DRAFT}
    />);
    const select = screen.getByRole("combobox", { name: /limit for Geoff Paulsen/i });
    expect(select).toHaveValue("default"); // starting state, matches the server row
    fireEvent.change(select, { target: { value: "exempt" } });
    expect(select).toHaveValue("exempt");
  });

  it("keeps a typed amount instead of being overwritten by the server row", () => {
    render(<StatefulPeoplePanel
      people={{ month: "2026-08", unreachable: false, unreadable: 0, people: PEOPLE }}
      initialDraft={DRAFT}
    />);
    const amountBox = screen.getByRole("spinbutton", { name: /amount for Danielle Moss/i });
    expect(amountBox).toHaveValue(25); // starting state, matches the server row
    fireEvent.change(amountBox, { target: { value: "30" } });
    expect(amountBox).toHaveValue(30);
  });
});

describe("hide/unhide fold under U0 (spec, samePerson)", () => {
  it("hides a person whose roster spelling differs from the stored hidden key, and Unhide clears it", () => {
    const props = renderPanel({
      people: { month: "2026-08", unreachable: false, unreadable: 0, people: [
        person({ key: "pchen", username: "PCHEN", display_name: "Pat Chen" }),
      ] },
      draft: { ...DRAFT, hidden_users: ["pchen"] },
    });
    // The roster's current observed spelling is "PCHEN"; the stored hidden
    // entry is "pchen". Under U0 these are the same person, so the row
    // collapses to the "1 person hidden" line rather than appearing in
    // the visible table.
    expect(screen.queryByRole("rowheader", { name: /PCHEN/ })).toBeNull();
    expect(screen.getByText(/1 person hidden/)).toHaveTextContent("Pat Chen");
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: /Unhide Pat Chen/ }));
    expect(props.onHiddenChange).toHaveBeenCalledWith([]);
  });
});
