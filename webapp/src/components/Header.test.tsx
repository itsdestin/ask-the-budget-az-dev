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
// the class on the anchor. If NavLink ever stops emitting "active" (or the `end`
// prop is dropped, making Home match every route), this fails instead of shipping
// a header with two lit pills or none.
test("only the current surface gets the mockup's azure active pill", () => {
  render(
    <MemoryRouter initialEntries={["/fiscal-notes"]}>
      <Header />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: "Fiscal Notes" })).toHaveClass("active");
  expect(screen.getByRole("link", { name: "Home" })).not.toHaveClass("active");
});

// Guards the ported chrome: the mockup's CSS is keyed to these exact selectors, so
// renaming a class here would silently unstyle the header.
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
