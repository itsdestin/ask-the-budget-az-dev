import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import * as api from "../api";
import { Header } from "./Header";

// MemoryRouter (not BrowserRouter) because NavLink needs a router context and
// this test only cares about the links, not the URL bar.
test("header has nav pills for the app's surfaces", () => {
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  for (const label of ["Home", "Budget Documents", "Fiscal Notes", "Settings"]) {
    expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
  }
});

// AI Mode's nav pill (Destin, 2026-07-31). Three things are pinned because each
// was an explicit instruction: it is a real route (not a toggle on another
// page), it is ICON-ONLY with the accessible name carried by aria-label + title
// exactly as the house pill does it, and it sits apart from the corpus pills on
// the right (`.nav-ai`, which is the hook the right-alignment CSS keys off).
test("AI Mode is an icon-only pill on the right of the nav", () => {
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  const ai = screen.getByRole("link", { name: "AI Mode" });
  expect(ai).toHaveAttribute("href", "/ai");
  expect(ai).toHaveAttribute("title", "AI Mode");
  // No visible text — the accessible name comes from aria-label alone, same as
  // Home. A label appearing here would read as a fourth place to browse.
  expect(ai.textContent).toBe("");
  const glyph = ai.querySelector("svg.ai-ic");
  expect(glyph).not.toBeNull();
  // Same construction as the house glyph: stroke-only, no fills.
  expect(glyph).toHaveAttribute("fill", "none");
  expect(glyph).toHaveAttribute("stroke", "currentColor");
  expect(glyph).toHaveAttribute("aria-hidden", "true");
  // The right-aligned slot. Markup-side only (jsdom applies no stylesheet), so
  // keep this class and the `.nav-item.nav-ai` rule in app.css in step by hand.
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
  expect(screen.getByRole("link", { name: "Home" })).not.toHaveClass("active");
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
  const pill = await screen.findByRole("link", { name: "Admin" });
  expect(pill).toHaveAttribute("href", "/admin");
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
  expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
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
  expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
  vi.restoreAllMocks();
});
