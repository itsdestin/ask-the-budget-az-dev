// Home's AI Mode gateway card. It has been inert since Plan 2 ("Coming soon",
// "Needs an API key"), which was honest then. It must become a live link the
// moment the server says AI answers can actually run — and stay inert, with
// the same honest copy, when it says they can't.

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Home } from "./Home";
import * as api from "../api";
import { AI_STATUS } from "./ai-test-fixtures";

describe("Home — AI card", () => {
  it("lights up as a link to /ai when AI is available", async () => {
    vi.spyOn(api, "aiStatus").mockResolvedValue(AI_STATUS);
    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    );
    const card = await screen.findByRole("link", { name: /ai mode/i });
    // /ai since 2026-07-31 — AI Mode is its own surface, not a toggle that
    // happened to live on the search page.
    expect(card).toHaveAttribute("href", "/ai");
    expect(screen.getByText(/AI Mode available/)).toBeInTheDocument();
    expect(screen.queryByText(/Coming soon/)).toBeNull();
    expect(card).not.toHaveClass("is-disabled");
  });

  it("keeps the inert card and its honest copy when AI is unavailable", async () => {
    vi.spyOn(api, "aiStatus").mockResolvedValue({
      ...AI_STATUS,
      available: false,
      reason: "no API key configured",
    });
    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Coming soon/)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("link", { name: /ai mode/i })).toBeNull();
    expect(screen.getByText(/Needs an API key/)).toBeInTheDocument();
  });

  it("stays inert when the status probe itself fails", async () => {
    // A card that lights up on a network error would promise a feature the
    // server never claimed.
    vi.spyOn(api, "aiStatus").mockRejectedValue(new Error("offline"));
    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Coming soon/)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("link", { name: /ai mode/i })).toBeNull();
  });
});
