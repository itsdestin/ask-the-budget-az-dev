import { useEffect, useState } from "react";
import * as api from "../api";
import { Card, CollapsibleCard } from "./Card";
import { when } from "./format";

// The admin's end of the analyst's "Report an issue" door (spec E3).
//
// Self-contained: its own fetch, its own PATCH, no part of the settings
// draft. It renders even when the list is empty — the analyst was told their
// report would be seen, so the door needs a visible other end.

/** A card title has to fit on one line beside its date. */
const TITLE_MAX = 80;

function title(description: string): string {
  const clean = description.trim().replace(/\s+/g, " ");
  return clean.length > TITLE_MAX ? `${clean.slice(0, TITLE_MAX)}…` : clean;
}

/** Open reports first, then newest first. A report that scrolls below three
 *  resolved ones is a report nobody answers. */
function inReadingOrder(reports: api.IssueReport[]): api.IssueReport[] {
  return [...reports].sort((a, b) => {
    const openA = a.status === "resolved" ? 1 : 0;
    const openB = b.status === "resolved" ? 1 : 0;
    if (openA !== openB) return openA - openB;
    return (b.submitted_at ?? "").localeCompare(a.submitted_at ?? "");
  });
}

// --- the attached conversation ---------------------------------------------
// The transcript is typed `unknown` because it is whatever the analyst's own
// machine wrote to disk. It is read defensively and rendered as a message
// list: an admin opening a report is trying to see what the analyst saw, and
// a JSON dump shows them nothing. Tool messages carry raw search results, so
// they are summarised rather than printed — they are long, they are not what
// the analyst read, and they are the one part with no plain-language shape.

type Said = { who: string; text: string };

function conversationOf(transcript: unknown): Said[] {
  if (!transcript || typeof transcript !== "object") return [];
  const messages = (transcript as { messages?: unknown }).messages;
  if (!Array.isArray(messages)) return [];
  const said: Said[] = [];
  for (const message of messages) {
    if (!message || typeof message !== "object") continue;
    const role = (message as { role?: unknown }).role;
    const content = (message as { content?: unknown }).content;
    if (role === "user" && typeof content === "string") {
      said.push({ who: "Asked", text: content });
    } else if (role === "assistant" && typeof content === "string" && content !== "") {
      said.push({ who: "Answered", text: content });
    } else if (role === "tool") {
      said.push({ who: "Looked up", text: "retrieved passages" });
    }
    // Anything else (system text, a tool call with no content) is skipped
    // rather than printed raw — this view is for reading, not for auditing.
  }
  return said;
}

function Conversation({ transcript }: { transcript: unknown }) {
  const said = conversationOf(transcript);
  if (said.length === 0) return null;
  return (
    <>
      <p className="adm-label">Attached conversation</p>
      <ol className="adm-convo" data-testid="admin-issue-transcript">
        {said.map((line, i) => (
          <li key={i}>
            <span className="adm-convo-who">{line.who}</span>
            <p>{line.text}</p>
          </li>
        ))}
      </ol>
    </>
  );
}

// --- one report -------------------------------------------------------------

function ReportRow({
  report,
  onUpdated,
}: {
  report: api.IssueReport;
  onUpdated: (next: api.IssueReport) => void;
}) {
  const [note, setNote] = useState(report.admin_note ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // A torn file. It gets a visible row rather than being dropped, because a
  // list that silently omits a report is indistinguishable from a list with
  // nothing in it — and there is nothing here to act on, so no buttons.
  if (report.unreadable) {
    return (
      <Card
        title="Unreadable report"
        hint={report.id}
        tone="muted"
        testId={`admin-issue-${report.id}`}
      >
        <p className="adm-hint">
          This report's file could not be read, so its contents are not
          available. The file is still on the share.
        </p>
      </Card>
    );
  }

  const resolved = report.status === "resolved";

  async function setStatus(status: "resolved" | "unresolved") {
    setError(null);
    setBusy(true);
    try {
      // The note goes with the action: the server stamps who resolved it and
      // when, so its copy of the report — not this form — is what gets shown.
      const result = await api.updateIssue(report.id, { status, admin_note: note });
      onUpdated(result.report);
      // Back to the server's copy of the note, not the typed one — if it
      // trimmed or dropped anything, the box has to say so.
      setNote(result.report.admin_note ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <CollapsibleCard
      title={title(report.description)}
      hint={`${report.submitted_by} · ${when(report.submitted_at)}${
        resolved ? " · resolved" : ""
      }`}
      testId={`admin-issue-${report.id}`}
    >
      <p className="adm-label">What happened</p>
      <p className="adm-sub">{report.description}</p>

      {report.expected ? (
        <>
          <p className="adm-label">What they expected</p>
          <p className="adm-sub">{report.expected}</p>
        </>
      ) : null}

      {report.transcript ? <Conversation transcript={report.transcript} /> : null}

      {resolved ? (
        <p className="adm-hint">
          Marked resolved by {report.resolved_by || "the administrator"}
          {report.resolved_at ? ` on ${when(report.resolved_at)}` : ""}.
        </p>
      ) : null}

      {/* The note as STORED, beside the box for editing it. A note that only
          exists in an input reads as typed-but-maybe-unsaved, which is the
          one thing an admin needs to be sure about here — the person who
          filed the report sees this sentence. */}
      {report.admin_note ? (
        <p className="adm-sub" data-testid={`admin-issue-note-${report.id}`}>
          Note sent back: {report.admin_note}
        </p>
      ) : null}

      <label className="adm-field" htmlFor={`adm-issue-note-${report.id}`}>
        <span>Note</span>
        <input
          id={`adm-issue-note-${report.id}`}
          type="text"
          autoComplete="off"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <p className="adm-hint">
        The person who sent the report sees this note. It is saved with the
        button below.
      </p>

      {error ? (
        <p className="adm-warn" role="alert">
          {error}
        </p>
      ) : null}

      <p className="adm-actions">
        <button
          type="button"
          className={resolved ? "adm-btn adm-btn-quiet" : "adm-btn"}
          disabled={busy}
          onClick={() => setStatus(resolved ? "unresolved" : "resolved")}
        >
          {resolved ? "Reopen" : "Mark resolved"}
        </button>
      </p>
    </CollapsibleCard>
  );
}

// --- the panel --------------------------------------------------------------

export function IssuesPanel() {
  const [reports, setReports] = useState<api.IssueReport[] | null>(null);
  const [open, setOpen] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .issues()
      .then((r) => {
        if (cancelled) return;
        setReports(r.reports);
        setOpen(r.unresolved);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** Swap in the server's copy of one report and re-count what is open, so
   *  the heading badge and the rows can never disagree. */
  function onUpdated(next: api.IssueReport) {
    setReports((current) => {
      const merged = (current ?? []).map((r) => (r.id === next.id ? next : r));
      setOpen(merged.filter((r) => !r.unreadable && r.status !== "resolved").length);
      return merged;
    });
  }

  return (
    <section
      className="card adm-panel"
      aria-labelledby="adm-issues-h"
      data-testid="admin-issues"
    >
      <h2 id="adm-issues-h">Issue reports{open > 0 ? ` (${open} open)` : ""}</h2>

      {error ? (
        <p className="adm-warn" role="alert">
          {error}
        </p>
      ) : null}

      {reports === null && !error ? <p className="adm-empty">Loading…</p> : null}

      {reports !== null && reports.length === 0 ? (
        <p className="adm-empty" data-testid="admin-issues-empty">
          No reports yet. Anyone can send one from "Report an issue" in the
          top-right menu.
        </p>
      ) : null}

      {(reports ?? []).length > 0
        ? inReadingOrder(reports ?? []).map((report) => (
            <ReportRow key={report.id} report={report} onUpdated={onUpdated} />
          ))
        : null}
    </section>
  );
}
