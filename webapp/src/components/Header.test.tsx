import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Header } from "./Header";

// MemoryRouter (not BrowserRouter) because NavLink needs a router context and
// this test only cares about the links, not the URL bar.
test("header has nav pills for the app's surfaces", () => {
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
  for (const label of ["Home", "Budget Search", "Fiscal Notes", "Settings"]) {
    expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
  }
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
