import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Home } from "./Home";

// vi.hoisted: vi.mock factories are hoisted above imports, so a plain `const
// navigate = vi.fn()` would still be undefined when the factory runs.
const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  // Only useNavigate is faked — MemoryRouter/Link below stay the real thing.
  useNavigate: () => navigate,
}));

beforeEach(() => navigate.mockClear());

describe("Home", () => {
  it("routes the hero search to /search with the query", () => {
    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    );
    const box = screen.getByPlaceholderText(/search/i);
    fireEvent.change(box, { target: { value: "dcs caseworkers" } });
    fireEvent.submit(box.closest("form")!);
    expect(navigate).toHaveBeenCalledWith("/search?q=dcs%20caseworkers");
  });

  it("does not route a blank hero search", () => {
    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    );
    const box = screen.getByPlaceholderText(/search/i);
    // Whitespace-only counts as blank: /search queries on mount from ?q=, so routing
    // here would fire a pointless request and show an empty results page.
    fireEvent.change(box, { target: { value: "   " } });
    fireEvent.submit(box.closest("form")!);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("links the feature cards to the three surfaces", () => {
    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    );
    // Asserted by role+href rather than by bare text (the plan's first draft) for
    // two reasons: the hrefs ARE the behavior worth pinning, and the hero
    // subtitle legitimately contains the words "fiscal notes", which would make a
    // bare getByText(/fiscal notes/i) ambiguous the moment the copy is correct.
    expect(screen.getByRole("link", { name: /budget library/i })).toHaveAttribute(
      "href",
      "/search",
    );
    expect(screen.getByRole("link", { name: /fiscal notes/i })).toHaveAttribute(
      "href",
      "/fiscal-notes",
    );
    // AI Mode is present but deliberately NOT navigable until Plan 4 wires it.
    expect(screen.getByText(/ai mode/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /ai mode/i })).not.toBeInTheDocument();
  });
});
