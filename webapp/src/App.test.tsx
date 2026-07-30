import { render, screen } from "@testing-library/react";
import { App } from "./App";

// Scaffold smoke test: proves the whole test stack is wired (vitest globals +
// jsdom + RTL + jest-dom matchers) and that the router mounts Home at "/".
// Tasks 7-10 replace the placeholders these testids hang off.
describe("App shell", () => {
  it("renders the header and the Home route at /", () => {
    render(<App />);
    expect(screen.getByTestId("header")).toBeInTheDocument();
    expect(screen.getByTestId("home")).toBeInTheDocument();
    expect(screen.queryByTestId("search")).not.toBeInTheDocument();
  });
});
