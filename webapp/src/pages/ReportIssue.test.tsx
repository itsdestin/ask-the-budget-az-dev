import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { ReportIssue } from "./ReportIssue";

// The analyst's door into issue reports (spec E3, Task 11). Two properties
// are worth protecting above the rest:
//
//  1. A report visibly exists the moment it is filed — "Your reports" below
//     the form is a REFETCH from the server, not the POST response spliced
//     in locally, so it proves the save actually landed.
//  2. Attaching a conversation is opt-in and SAID PLAINLY. The picker
//     defaults to no attachment, and the consent sentence renders only once
//     one is actually chosen.

function me(over: Partial<api.Me> = {}): api.Me {
  return {
    user: "analyst1",
    is_admin: false,
    admin_username: "Destin",
    admin_claimable: false,
    admin_reset_pending: false,
    ...over,
  };
}

function report(over: Partial<api.IssueReport> = {}): api.IssueReport {
  return {
    id: "r1",
    version: 1,
    submitted_by: "analyst1",
    submitted_at: "2026-08-01T10:00:00Z",
    description: "Search came back empty for HB123",
    expected: "",
    status: "unresolved",
    admin_note: null,
    resolved_by: null,
    resolved_at: null,
    ...over,
  };
}

function chat(over: Partial<api.HistoryRow> = {}): api.HistoryRow {
  return {
    id: "c1",
    title: "Roads spending FY24",
    corpus: "budget",
    created_at: "2026-08-01T09:00:00Z",
    updated_at: "2026-08-01T09:05:00Z",
    title_is_manual: true,
    message_count: 4,
    ...over,
  };
}

/** The common case: nobody's chats, no reports yet — used by specs that only
 *  care about the form itself. */
function mockEmpty(over: { me?: Partial<api.Me> } = {}) {
  vi.spyOn(api, "me").mockResolvedValue(me(over.me));
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [] });
  return vi.spyOn(api, "issues").mockResolvedValue({
    reports: [],
  });
}

afterEach(() => vi.restoreAllMocks());

describe("filing a report", () => {
  it("submits description + expected, and the new report appears in Your reports below", async () => {
    mockEmpty();
    const newReport = report({ description: "Search came back empty for HB123", expected: "Some results" });
    const submitSpy = vi.spyOn(api, "submitIssue").mockResolvedValue({ report: newReport });
    const issuesSpy = vi
      .spyOn(api, "issues")
      .mockResolvedValueOnce({ reports: [] })
      .mockResolvedValueOnce({ reports: [newReport] });

    render(<ReportIssue />);
    await screen.findByText(/you haven.t filed a report yet/i);

    fireEvent.change(screen.getByLabelText(/what happened/i), {
      target: { value: "Search came back empty for HB123" },
    });
    fireEvent.change(screen.getByLabelText(/what you expected/i), {
      target: { value: "Some results" },
    });
    fireEvent.click(screen.getByTestId("report-submit"));

    await waitFor(() =>
      expect(submitSpy).toHaveBeenCalledWith({
        description: "Search came back empty for HB123",
        expected: "Some results",
      }),
    );
    // A refetch, not the POST response spliced in — proves the save landed.
    await waitFor(() => expect(issuesSpy).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Search came back empty for HB123")).toBeInTheDocument();
  });

  it("never sends conversation_id or expected when left blank", async () => {
    mockEmpty();
    const submitSpy = vi.spyOn(api, "submitIssue").mockResolvedValue({ report: report() });
    render(<ReportIssue />);
    await screen.findByText(/you haven.t filed a report yet/i);

    fireEvent.change(screen.getByLabelText(/what happened/i), {
      target: { value: "Something is wrong" },
    });
    fireEvent.click(screen.getByTestId("report-submit"));

    await waitFor(() => expect(submitSpy).toHaveBeenCalled());
    expect(submitSpy.mock.calls[0][0]).not.toHaveProperty("conversation_id");
    expect(submitSpy.mock.calls[0][0]).not.toHaveProperty("expected");
  });

  it("disables submit while the description is empty or just whitespace", async () => {
    mockEmpty();
    render(<ReportIssue />);
    await screen.findByText(/you haven.t filed a report yet/i);

    expect(screen.getByTestId("report-submit")).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/what happened/i), { target: { value: "   " } });
    expect(screen.getByTestId("report-submit")).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/what happened/i), { target: { value: "Real text" } });
    expect(screen.getByTestId("report-submit")).toBeEnabled();
  });

  it("surfaces the server's refusal instead of silently failing", async () => {
    mockEmpty();
    vi.spyOn(api, "submitIssue").mockRejectedValue(
      new Error("submit issue report: A description is required."),
    );
    render(<ReportIssue />);
    await screen.findByText(/you haven.t filed a report yet/i);

    fireEvent.change(screen.getByLabelText(/what happened/i), { target: { value: "Something broke" } });
    fireEvent.click(screen.getByTestId("report-submit"));

    expect(await screen.findByTestId("report-submit-error")).toHaveTextContent(
      /A description is required/,
    );
    // The words the analyst typed must not vanish behind a failed save.
    expect(screen.getByLabelText(/what happened/i)).toHaveValue("Something broke");
  });
});

describe("the transcript picker", () => {
  it("renders the caller's chats with no attachment as the default, and shows consent only once one is chosen", async () => {
    vi.spyOn(api, "me").mockResolvedValue(me());
    vi.spyOn(api, "issues").mockResolvedValue({ reports: [] });
    vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [chat()] });

    render(<ReportIssue />);
    const picker = await screen.findByLabelText(/attach one of your conversations/i);

    expect(within(picker).getByText(/don.t attach a conversation/i)).toBeInTheDocument();
    expect(within(picker).getByText("Roads spending FY24")).toBeInTheDocument();
    expect(picker).toHaveValue("");
    expect(screen.queryByTestId("report-consent")).toBeNull();

    fireEvent.change(picker, { target: { value: "c1" } });

    expect(await screen.findByTestId("report-consent")).toHaveTextContent(
      "Attaching shares this conversation with the administrator — they will be able to read everything in it.",
    );
  });

  it("sends conversation_id once a conversation is chosen", async () => {
    mockEmpty();
    vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [chat()] });
    const submitSpy = vi.spyOn(api, "submitIssue").mockResolvedValue({ report: report() });

    render(<ReportIssue />);
    const picker = await screen.findByLabelText(/attach one of your conversations/i);
    fireEvent.change(picker, { target: { value: "c1" } });
    fireEvent.change(screen.getByLabelText(/what happened/i), { target: { value: "Answer looked wrong" } });
    fireEvent.click(screen.getByTestId("report-submit"));

    await waitFor(() =>
      expect(submitSpy).toHaveBeenCalledWith(
        expect.objectContaining({ conversation_id: "c1" }),
      ),
    );
  });
});

describe("Your reports", () => {
  it("renders each report's status and the administrator's note when present", async () => {
    vi.spyOn(api, "me").mockResolvedValue(me());
    vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [] });
    vi.spyOn(api, "issues").mockResolvedValue({
      reports: [
        report({ id: "r1", description: "Search came back empty", status: "unresolved" }),
        report({
          id: "r2",
          description: "Answer looked wrong",
          status: "resolved",
          admin_note: "Fixed the indexing bug.",
          resolved_by: "Destin",
          resolved_at: "2026-08-03T10:00:00Z",
        }),
      ],
    });

    render(<ReportIssue />);
    const rows = await screen.findAllByTestId("report-row");
    expect(rows).toHaveLength(2);

    expect(rows[0]).toHaveTextContent("Search came back empty");
    expect(rows[0]).toHaveTextContent(/not resolved yet/i);
    expect(rows[0]).not.toHaveTextContent(/administrator.s note/i);

    expect(rows[1]).toHaveTextContent("Answer looked wrong");
    expect(rows[1]).toHaveTextContent(/resolved/i);
    expect(rows[1]).toHaveTextContent("Fixed the indexing bug.");
  });

  it("does not claim you have filed nothing when the folder could not be read", async () => {
    // "You haven't filed a report yet." off an unreadable share tells the
    // analyst their report is gone. It is not known to be gone — nobody
    // could look.
    vi.spyOn(api, "me").mockResolvedValue(me());
    vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [] });
    vi.spyOn(api, "issues").mockResolvedValue({ reports: [], unreachable: true });

    render(<ReportIssue />);
    expect(await screen.findByTestId("report-history-unreachable")).toHaveTextContent(
      /shared folder couldn.t be read/i,
    );
    expect(screen.queryByText(/haven.t filed a report yet/i)).toBeNull();
  });

  it("shows a torn report of your own as a visible row", async () => {
    // The row carries no fields at all — the server keeps it in a non-admin
    // list precisely so the person who filed it learns it did not land.
    vi.spyOn(api, "me").mockResolvedValue(me());
    vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [] });
    vi.spyOn(api, "issues").mockResolvedValue({
      reports: [{ id: "20260101T000000-abcd", unreadable: true } as api.IssueReport],
    });

    render(<ReportIssue />);
    const rows = await screen.findAllByTestId("report-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent(/couldn.t be read back/i);
  });

  it("renders a resolved report as a visibly different row", async () => {
    vi.spyOn(api, "me").mockResolvedValue(me());
    vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [] });
    vi.spyOn(api, "issues").mockResolvedValue({
      reports: [
        report({ id: "r1", status: "unresolved" }),
        report({ id: "r2", status: "resolved", admin_note: "Done." }),
      ],
    });

    render(<ReportIssue />);
    const rows = await screen.findAllByTestId("report-row");
    expect(rows[0]).not.toHaveClass("is-resolved");
    expect(rows[1]).toHaveClass("is-resolved");
  });

  it("states the context the server records, with wording that stays true whether or not a conversation is attached", async () => {
    vi.spyOn(api, "me").mockResolvedValue(me({ user: "jsmith" }));
    vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [chat()] });
    vi.spyOn(api, "issues").mockResolvedValue({ reports: [] });

    render(<ReportIssue />);
    const context = await screen.findByTestId("report-context");
    // No attachment yet — the sentence must not claim more than it can back
    // up, and must leave the "anything else" question to the consent line.
    expect(context).toHaveTextContent(
      "This report will be filed as jsmith, timestamped the moment you send it.",
    );

    const picker = await screen.findByLabelText(/attach one of your conversations/i);
    fireEvent.change(picker, { target: { value: "c1" } });

    // Once a conversation is attached, this sentence must read identically —
    // if it still claimed "nothing else is collected" here it would be
    // false, since the attached conversation is exactly the extra thing
    // going along with the report.
    expect(screen.getByTestId("report-context")).toHaveTextContent(
      "This report will be filed as jsmith, timestamped the moment you send it.",
    );
  });
});
