import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import * as api from "../api";
import { AgenciesPanel } from "./AgenciesPanel";

// The office's own agencies, for the upload page's agency picker.
//
// jsdom applies no stylesheet, so nothing here says how the panel looks.

const CATALOG: api.AgencyOption[] = [
  { canonical_id: "agency:adc", name: "Corrections, State Department of", source: "catalog" },
  { canonical_id: "agency:des", name: "Economic Security, Department of", source: "catalog" },
];
const OFFICE: api.AgencyOption = {
  canonical_id: "agency:office-broadband",
  name: "Office of Broadband",
  source: "office",
};

afterEach(() => vi.restoreAllMocks());

async function open() {
  render(<AgenciesPanel />);
  // CollapsibleCard starts closed; everything below is inside it.
  fireEvent.click(await screen.findByRole("button", { name: /show|hide|agencies/i }));
}

it("counts what ships with the app before anything is added", async () => {
  vi.spyOn(api, "agencies").mockResolvedValue(CATALOG);
  render(<AgenciesPanel />);
  expect(await screen.findByText(/2 agencies ship with the app/)).toBeTruthy();
});

it("lists only the office's own agencies, never the shipped ones", async () => {
  // 🔴 The shipped catalog is 157 rows. Listing it here would bury the two
  // an admin actually manages, and none of the 157 can be removed anyway —
  // so a list of them is a list of things with no action.
  vi.spyOn(api, "agencies").mockResolvedValue([...CATALOG, OFFICE]);
  await open();
  const list = await screen.findByTestId("office-agencies");
  expect(within(list).getAllByRole("listitem")).toHaveLength(1);
  expect(list.textContent).toContain("Office of Broadband");
  expect(list.textContent).not.toContain("Corrections");
});

it("adds an agency and re-reads the server's list rather than its own guess", async () => {
  // The server de-duplicates case- and spacing-insensitively against BOTH
  // sources, so a locally appended row could show an admin an agency that
  // was actually refused.
  const add = vi.spyOn(api, "addAgency").mockResolvedValue(OFFICE);
  const list = vi
    .spyOn(api, "agencies")
    .mockResolvedValueOnce(CATALOG)
    .mockResolvedValue([...CATALOG, OFFICE]);
  await open();

  fireEvent.change(screen.getByLabelText(/agency name/i), {
    target: { value: "Office of Broadband" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));

  await waitFor(() => expect(add).toHaveBeenCalledWith("Office of Broadband"));
  expect(await screen.findByText("Office of Broadband")).toBeTruthy();
  expect(list).toHaveBeenCalledTimes(2);
});

it("shows the server's own refusal, not a rewritten one", async () => {
  // The server is what knows whether a name ships with the app, duplicates
  // one already added, or is too long to be a document title.
  vi.spyOn(api, "agencies").mockResolvedValue(CATALOG);
  vi.spyOn(api, "addAgency").mockRejectedValue(
    new Error("add agency: Corrections, State Department of is already in the list (it ships with the app)."),
  );
  await open();

  fireEvent.change(screen.getByLabelText(/agency name/i), {
    target: { value: "Corrections, State Department of" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));

  expect(await screen.findByText(/already in the list \(it ships with the app\)/)).toBeTruthy();
});

it("keeps Add disabled until something is typed", async () => {
  vi.spyOn(api, "agencies").mockResolvedValue(CATALOG);
  await open();
  const add = screen.getByRole("button", { name: "Add" });
  expect(add).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/agency name/i), { target: { value: "   " } });
  expect(add).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/agency name/i), { target: { value: "X" } });
  expect(add).toBeEnabled();
});

it("removes an office agency", async () => {
  const remove = vi.spyOn(api, "removeAgency").mockResolvedValue(undefined);
  vi.spyOn(api, "agencies")
    .mockResolvedValueOnce([...CATALOG, OFFICE])
    .mockResolvedValue(CATALOG);
  await open();

  fireEvent.click(await screen.findByRole("button", { name: "Remove" }));

  await waitFor(() => expect(remove).toHaveBeenCalledWith("agency:office-broadband"));
  await waitFor(() => expect(screen.queryByTestId("office-agencies")).toBeNull());
});

it("says plainly that removing is not undoing", async () => {
  // The natural assumption is the opposite, and an admin who expects a
  // removal to fix a document's title will otherwise go looking for a
  // change that never happened.
  vi.spyOn(api, "agencies").mockResolvedValue(CATALOG);
  await open();
  expect(
    screen.getByText(/Documents already uploaded under it keep the name they were given/),
  ).toBeTruthy();
});
