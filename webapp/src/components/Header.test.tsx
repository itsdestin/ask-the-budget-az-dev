import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import * as api from "../api";
import { Header } from "./Header";

// MemoryRouter (not BrowserRouter) because NavLink needs a router context and
// this test only cares about the links, not the URL bar.
test("the nav row is the two corpora and AI Mode, and nothing else", () => {
  // Destin, 2026-08-02. Home left (the logo already goes there, and two
  // controls for one destination is one too many in a row this narrow), and
  // Upload/Settings/Admin moved into the tools menu — they are places you
  // administer, not places you read, and they were taking width from the two
  // things analysts actually came for.
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  for (const label of ["Budget Documents", "AI Mode", "Fiscal Notes"]) {
    expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
  }
  expect(screen.queryByRole("link", { name: "Home" })).toBeNull();
  for (const gone of ["Upload", "Settings"]) {
    expect(screen.queryByRole("link", { name: gone })).toBeNull();
  }
});

test("home is still reachable, from the logo", () => {
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: /JLBC home/i })).toHaveAttribute("href", "/");
});

test("AI Mode sits between the two corpus pills", () => {
  // It is the thing you do WITH either corpus, so the middle is where it
  // belongs — being flanked says that more clearly than the old right-hand
  // slot said "stands apart".
  const { container } = render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  const labels = [...container.querySelectorAll("nav.primary .nav-item > a")].map(
    (a) => a.getAttribute("aria-label") ?? a.textContent,
  );
  expect(labels).toEqual(["Budget Documents", "AI Mode", "Fiscal Notes"]);
});

// AI Mode's nav pill (Destin, 2026-07-31). Three things are pinned because each
// was an explicit instruction: it is a real route (not a toggle on another
// page), it is ICON-ONLY with the accessible name carried by aria-label + title
// exactly as the house pill does it, and it sits apart from the corpus pills on
// the right (`.nav-ai`, which is the hook the right-alignment CSS keys off).
test("AI Mode's pill carries its label but keeps one accessible name", () => {
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  const ai = screen.getByRole("link", { name: "AI Mode" });
  expect(ai).toHaveAttribute("href", "/ai");
  expect(ai).toHaveAttribute("title", "AI Mode");
  // The label rolls out of the pill when active (see .nav-ai-text), so the
  // text IS in the markup — but it is aria-hidden, because the link already
  // carries `aria-label`. Without that the accessible name would double up to
  // "AI Mode AI Mode" the moment the pill opened.
  expect(ai.textContent).toContain("AI");
  expect(ai.querySelector(".nav-ai-text")).toHaveAttribute("aria-hidden", "true");
  expect(ai).toHaveAccessibleName("AI Mode");
  // The spark is a separate group so CSS can move it between the icon's two
  // states; a flat pair of paths could not be animated as one.
  expect(ai.querySelector(".nav-ai-spark")).not.toBeNull();
  const glyph = ai.querySelector("svg.ai-ic");
  expect(glyph).not.toBeNull();
  // Same construction as the house glyph: stroke-only, no fills.
  expect(glyph).toHaveAttribute("fill", "none");
  expect(glyph).toHaveAttribute("stroke", "currentColor");
  expect(glyph).toHaveAttribute("aria-hidden", "true");
  // Markup-side only (jsdom applies no stylesheet), so keep this class and the
  // `.nav-item.nav-ai` rules in app.css in step by hand.
  expect(ai.closest(".nav-item")).toHaveClass("nav-ai");
});

// Pins the one CSS deviation from the mockup: it styles the azure pill via
// `.nav-item.active>a`, we style `.nav-item>a.active` because NavLink can only put
// the class on the anchor. Two things are pinned: NavLink still emits the "active"
// class at all, and exactly one pill is lit for a given route. (It does NOT pin the
// `end` prop — react-router 7.18 never prefix-matches "/", so removing `end` would
// still pass; `end` is kept in Header.tsx as future-proofing, not as behavior here.)
test("only the current surface gets the mockup's azure active pill", () => {
  render(
    <MemoryRouter initialEntries={["/fiscal-notes"]}>
      <Header />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: "Fiscal Notes" })).toHaveClass("active");
  expect(screen.getByRole("link", { name: "Budget Documents" })).not.toHaveClass("active");
});

// Guards the MARKUP side of the port only: the ported CSS is keyed to this selector
// chain, so renaming a class in Header.tsx would silently unstyle the header. It does
// not verify styling end-to-end — a rename in app.css alone still passes (jsdom
// applies no stylesheet), so keep the two files in step by hand.
test("keeps the mockup's header markup hooks", () => {
  const { container } = render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  expect(container.querySelector("header.site .wrap.head nav.primary .nav-item > a")).not.toBeNull();
  expect(screen.getByAltText(/Joint Legislative Budget Committee/)).toHaveAttribute(
    "src",
    "/jlbc-logo.png",
  );
});

// The Admin pill (Plan 5 Task 8). It renders only when /api/me says the caller
// holds the admin seat.
//
// This is PRESENTATION, not protection, and the distinction matters enough to
// pin: the gate that counts is server-side (every /api/admin route answers 403
// to a non-admin, pinned by tests/test_admin_settings_route.py), and it is
// soft by design (spec S11) because it is keyed on a Windows username anyone
// can override. Hiding the pill keeps the page from being advertised
// office-wide. It keeps nobody out, and nothing behind it would be harmful if
// it did not.
test("the Admin pill renders only for the admin", async () => {
  vi.spyOn(api, "me").mockResolvedValue({
    user: "Destin",
    is_admin: true,
    admin_username: "Destin",
    admin_claimable: false,
    admin_reset_pending: false,
  });
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  // It lives inside the tools menu now, so it has to be opened first.
  fireEvent.click(await screen.findByTestId("nav-tools-button"));
  const item = await screen.findByRole("menuitem", { name: /Admin/ });
  expect(item).toHaveAttribute("href", "/admin");
  vi.restoreAllMocks();
});

test("a non-admin never sees the Admin pill", async () => {
  vi.spyOn(api, "me").mockResolvedValue({
    user: "analyst1",
    is_admin: false,
    admin_username: "Destin",
    admin_claimable: false,
    admin_reset_pending: false,
  });
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  await screen.findByRole("link", { name: "Budget Documents" });
  await waitFor(() => expect(api.me).toHaveBeenCalled());
  fireEvent.click(screen.getByTestId("nav-tools-button"));
  expect(screen.queryByRole("menuitem", { name: /Admin/ })).toBeNull();
  // …and the two anyone may reach are still there, so a missing seat costs the
  // one item and not the menu.
  expect(screen.getByRole("menuitem", { name: /Upload/ })).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: /Settings/ })).toBeInTheDocument();
  vi.restoreAllMocks();
});

// A failing /api/me must cost the pill, not the header. The nav is how an
// analyst reaches every other surface; losing it because an identity probe
// hiccupped would take down the whole app over a cosmetic detail.
test("a failed identity probe still renders the rest of the nav", async () => {
  vi.spyOn(api, "me").mockRejectedValue(new Error("who am I failed: 500"));
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("link", { name: "Budget Documents" })).toBeInTheDocument();
  await waitFor(() => expect(api.me).toHaveBeenCalled());
  fireEvent.click(screen.getByTestId("nav-tools-button"));
  expect(screen.queryByRole("menuitem", { name: /Admin/ })).toBeNull();
  vi.restoreAllMocks();
});

// The tools menu (Destin, 2026-08-02).
test("the tools menu opens on click as well as hover", () => {
  // Hover is what was asked for, but it cannot be the only way in: a keyboard
  // user has no pointer, and this is the app's only route to Settings.
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  const btn = screen.getByTestId("nav-tools-button");
  expect(btn).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("menu")).toBeNull();

  fireEvent.click(btn);
  expect(btn).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("menuitem", { name: /Upload/ })).toHaveAttribute("href", "/upload");
  expect(screen.getByRole("menuitem", { name: /Settings/ })).toHaveAttribute("href", "/settings");
});

test("Escape closes the menu", () => {
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByTestId("nav-tools-button"));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();
});

test("the trigger reads as selected when the current page lives in the menu", () => {
  // Without this the header shows NO active pill on /settings, and the app
  // looks like it has lost track of where you are.
  render(
    <MemoryRouter initialEntries={["/settings"]}>
      <Header />
    </MemoryRouter>,
  );
  expect(screen.getByTestId("nav-tools-button")).toHaveClass("is-current");
});

test("the trigger is NOT selected on a page outside the menu", () => {
  render(
    <MemoryRouter initialEntries={["/search"]}>
      <Header />
    </MemoryRouter>,
  );
  expect(screen.getByTestId("nav-tools-button")).not.toHaveClass("is-current");
});

test("the current tool is marked so the fill has something to start on", () => {
  // `is-current` is ours rather than NavLink's `active`, because the fill must
  // be able to LEAVE this item when the pointer moves to another one — that is
  // a CSS rule keyed on hovering the popover, and it needs the two ideas
  // ("where you are" vs "what you are pointing at") kept separable.
  render(
    <MemoryRouter initialEntries={["/upload"]}>
      <Header />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByTestId("nav-tools-button"));
  expect(screen.getByRole("menuitem", { name: /Upload/ })).toHaveClass("is-current");
  expect(screen.getByRole("menuitem", { name: /Settings/ })).not.toHaveClass("is-current");
});

// "i cant reach upload/settings, they disappear when i try to scroll to them"
// (Destin, 2026-08-02). The popover is absolutely positioned, so the gap
// between it and the trigger belongs to neither — crossing it left the
// component's subtree, fired mouseleave, and shut the menu mid-journey.
test("the menu survives the pointer leaving briefly", () => {
  vi.useFakeTimers();
  try {
    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );
    const wrap = screen.getByTestId("nav-tools-button").parentElement!;
    fireEvent.mouseEnter(wrap);
    expect(screen.getByRole("menu")).toBeInTheDocument();

    // Pointer slips out on its way to an item…
    fireEvent.mouseLeave(wrap);
    act(() => {
      vi.advanceTimersByTime(80);
    });
    expect(screen.getByRole("menu"), "must not close instantly").toBeInTheDocument();

    // …and comes back. The pending close is cancelled, not merely deferred.
    fireEvent.mouseEnter(wrap);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByRole("menu")).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

test("the menu does close once the pointer is really gone", () => {
  // The other half: a grace period that never expires is a menu stuck open.
  vi.useFakeTimers();
  try {
    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );
    const wrap = screen.getByTestId("nav-tools-button").parentElement!;
    fireEvent.mouseEnter(wrap);
    fireEvent.mouseLeave(wrap);
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(screen.queryByRole("menu")).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});
