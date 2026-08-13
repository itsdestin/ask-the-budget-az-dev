import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { IssuesPanel } from "./IssuesPanel";

// The admin's end of the analyst's door. What these specs protect:
//
//  1. Open reports come first and are counted in the heading. A report that
//     scrolls below three resolved ones is a report nobody answers.
//  2. Resolving re-renders from the server's copy of the report — the note
//     and the "resolved by" line are the server's to write.
//  3. A torn report file shows as a visible row, never a blank list, and
//     offers no buttons: there is nothing an admin could act on.
//  4. An attached conversation reads as a conversation. Dumped JSON would
//     be unreadable to the person the attachment exists for.

function report(over: Partial<api.IssueReport> = {}): api.IssueReport {
  return {
    id: "r1",
    version: 1,
    submitted_by: "analyst1",
    submitted_at: "2026-08-10T17:00:00Z",
    description: "Search for the AHCCCS caseload returned nothing.",
    expected: "The 2024 caseload table.",
    status: "unresolved",
    admin_note: null,
    resolved_by: null,
    resolved_at: null,
    ...over,
  };
}

function response(over: Partial<api.IssuesResponse> = {}): api.IssuesResponse {
  return {
    reports: [report()],
    ...over,
  };
}

afterEach(() => vi.restoreAllMocks());

async function renderPanel(over: Partial<api.IssuesResponse> = {}) {
  vi.spyOn(api, "issues").mockResolvedValue(response(over));
  render(<IssuesPanel />);
  await screen.findByTestId("admin-issues");
}

function openRow(title: RegExp) {
  const heading = screen
    .getAllByRole("heading", { level: 3 })
    .find((h) => title.test(h.textContent ?? ""));
  if (!heading) throw new Error(`no report titled ${title}`);
  fireEvent.click(heading.closest("button")!);
}

describe("the issue report inbox", () => {
  it("counts the open ones in its heading", async () => {
    await renderPanel({
      reports: [report(), report({ id: "r2", description: "Second problem." })],
    });
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      /issue reports \(2 open\)/i,
    );
  });

  it("says so when there is nothing waiting", async () => {
    await renderPanel({ reports: [] });
    expect(screen.getByTestId("admin-issues-empty")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2 })).not.toHaveTextContent(/open/i);
  });

  it("does not claim there are no reports when the folder could not be read", async () => {
    // An empty list plus `unreachable` is "nobody could look", and the
    // empty-state sentence would be a fact this screen does not know.
    await renderPanel({ reports: [], unreachable: true });
    expect(screen.getByTestId("admin-issues-unreachable")).toHaveTextContent(
      /shared folder couldn.t be read/i,
    );
    expect(screen.queryByTestId("admin-issues-empty")).toBeNull();
  });

  it("puts open reports above resolved ones, newest first", async () => {
    await renderPanel({
      reports: [
        report({ id: "a", description: "Old and resolved.", status: "resolved",
                 submitted_at: "2026-08-01T00:00:00Z" }),
        report({ id: "b", description: "Older and open.",
                 submitted_at: "2026-08-02T00:00:00Z" }),
        report({ id: "c", description: "Newest and open.",
                 submitted_at: "2026-08-09T00:00:00Z" }),
      ],
    });

    const titles = screen
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    expect(titles).toEqual(["Newest and open.", "Older and open.", "Old and resolved."]);
  });

  it("shows the whole report when a row is opened", async () => {
    await renderPanel();
    openRow(/AHCCCS caseload/);

    const row = screen.getByTestId("admin-issue-r1");
    expect(row).toHaveTextContent("Search for the AHCCCS caseload returned nothing.");
    expect(row).toHaveTextContent("The 2024 caseload table.");
    expect(within(row).getByLabelText(/note/i)).toBeInTheDocument();
  });

  it("resolves a report and re-renders the server's copy of it", async () => {
    await renderPanel();
    openRow(/AHCCCS caseload/);
    const update = vi.spyOn(api, "updateIssue").mockResolvedValue({
      report: report({
        status: "resolved",
        admin_note: "Re-filed the 2024 tables.",
        resolved_by: "Destin",
        resolved_at: "2026-08-12T17:00:00Z",
      }),
    });

    fireEvent.change(screen.getByLabelText(/note/i), {
      target: { value: "Re-filed the 2024 tables." },
    });
    fireEvent.click(screen.getByRole("button", { name: /mark resolved/i }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith("r1", {
        status: "resolved",
        admin_note: "Re-filed the 2024 tables.",
      }),
    );
    // The note reads back from the server's report, not from the input.
    const row = await screen.findByTestId("admin-issue-r1");
    expect(row).toHaveTextContent("Re-filed the 2024 tables.");
    expect(within(row).getByRole("button", { name: /reopen/i })).toBeInTheDocument();
  });

  it("shows the server's own sentence when an update is refused", async () => {
    await renderPanel();
    openRow(/AHCCCS caseload/);
    vi.spyOn(api, "updateIssue").mockRejectedValue(
      new Error("update issue report: That note is too long."),
    );

    fireEvent.click(screen.getByRole("button", { name: /mark resolved/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/note is too long/i);
  });

  it("shows a report whose file is damaged, with nothing to click", async () => {
    await renderPanel({
      reports: [{ id: "torn-file", unreadable: true } as api.IssueReport],
    });

    const row = screen.getByTestId("admin-issue-torn-file");
    expect(row).toHaveTextContent(/unreadable report/i);
    // Nothing here can be acted on — offering a button would be a lie.
    expect(within(row).queryByRole("button")).toBeNull();
  });
});

describe("an attached conversation", () => {
  const withTranscript = report({
    id: "t1",
    description: "The answer cited the wrong year.",
    transcript: {
      id: "conv1",
      title: "AHCCCS caseload",
      messages: [
        { role: "user", content: "What was the AHCCCS caseload in 2024?" },
        { role: "tool", content: '[{"doc":"afr-2024.pdf","score":0.81}]' },
        { role: "assistant", content: "The 2024 caseload was 2.1 million." },
      ],
    },
  });

  it("reads as a conversation, not as a data dump", async () => {
    await renderPanel({ reports: [withTranscript] });
    openRow(/wrong year/);

    const view = screen.getByTestId("admin-issue-transcript");
    expect(within(view).getByText(/What was the AHCCCS caseload in 2024\?/)).toBeInTheDocument();
    expect(within(view).getByText(/The 2024 caseload was 2\.1 million\./)).toBeInTheDocument();
    // The tool message is a summary, never the raw result it carried.
    expect(view).toHaveTextContent(/retrieved passages/i);
    expect(view.textContent ?? "").not.toContain("afr-2024.pdf");
    expect(view.textContent ?? "").not.toContain('"role"');
  });

  it("labels who said what in words an admin reads", async () => {
    await renderPanel({ reports: [withTranscript] });
    openRow(/wrong year/);

    const view = screen.getByTestId("admin-issue-transcript");
    expect(within(view).getByText(/^asked$/i)).toBeInTheDocument();
    expect(within(view).getByText(/^answered$/i)).toBeInTheDocument();
  });

  it("shows nothing about a conversation when none was attached", async () => {
    await renderPanel();
    openRow(/AHCCCS caseload/);
    expect(screen.queryByTestId("admin-issue-transcript")).toBeNull();
  });
});
