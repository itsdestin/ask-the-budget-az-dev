import { render, screen, fireEvent } from "@testing-library/react";
import { ReportChooser } from "./ReportChooser";

const BOTH = {
  singleFile: "https://www.azjlbc.gov/budget/27baselinesinglefile.pdf",
  linkedToc: "https://www.azjlbc.gov/budget/27baselinelinks.pdf",
};

test("offers both formats, each linking to its own hand-verified URL", () => {
  render(<ReportChooser title="FY 2027 Baseline" formats={BOTH} onClose={() => {}} />);
  expect(screen.getByRole("link", { name: /linked table of contents/i }))
    .toHaveAttribute("href", BOTH.linkedToc);
  expect(screen.getByRole("link", { name: /single file pdf/i }))
    .toHaveAttribute("href", BOTH.singleFile);
});

test("Escape closes it", () => {
  const onClose = vi.fn();
  render(<ReportChooser title="FY 2027 Baseline" formats={BOTH} onClose={onClose} />);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).toHaveBeenCalled();
});

test("clicking the backdrop closes it, clicking the sheet does not", () => {
  const onClose = vi.fn();
  render(<ReportChooser title="FY 2027 Baseline" formats={BOTH} onClose={onClose} />);
  fireEvent.click(screen.getByRole("dialog"));
  expect(onClose).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("link", { name: /single file pdf/i }).closest(".mbody")!);
  expect(onClose).toHaveBeenCalledTimes(1); // unchanged
});

test("focus moves into the dialog on open", () => {
  render(<ReportChooser title="FY 2027 Baseline" formats={BOTH} onClose={() => {}} />);
  expect(screen.getByRole("link", { name: /linked table of contents/i })).toHaveFocus();
});

test("focus still moves into the dialog when neither format is available", () => {
  render(
    <ReportChooser
      title="FY 2026 Budget Bill"
      formats={{ singleFile: null, linkedToc: null }}
      onClose={() => {}}
    />,
  );
  expect(screen.getByRole("button", { name: /close/i })).toHaveFocus();
});

test("Tab from the last control wraps to the first — focus never escapes", () => {
  render(<ReportChooser title="FY 2027 Baseline" formats={BOTH} onClose={() => {}} />);
  // DOM order is deterministic — the close button sits in `.mhead`, before
  // `.mbody`'s links — so `first`/`last` don't need to be derived from
  // compareDocumentPosition; the previous version of this test only checked
  // "focus moved somewhere", which passed for a wrap to the WRONG node too
  // (MINOR, 2026-08-10).
  const close = screen.getByRole("button", { name: /close/i });
  const links = screen.getAllByRole("link");
  const last = links[links.length - 1];
  last.focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(document.activeElement).toBe(close);
});

test("a missing format is not offered at all", () => {
  render(
    <ReportChooser
      title="FY 2026 Budget Bill"
      formats={{ singleFile: "https://example.gov/bb26.pdf", linkedToc: null }}
      onClose={() => {}}
    />,
  );
  expect(screen.queryByRole("link", { name: /linked table of contents/i })).toBeNull();
  expect(screen.getByRole("link", { name: /single file pdf/i })).toBeInTheDocument();
});
