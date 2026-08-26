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
    expect(container.querySelector(".adm-link")).toBeNull();
    for (const b of container.querySelectorAll("button")) expect(b.className).toMatch(/adm-btn/);
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
