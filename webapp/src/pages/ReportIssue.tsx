import { useCallback, useEffect, useState } from "react";
import * as api from "../api";
import { when } from "../admin/format";

// The analyst's door into issue reports (spec E3, Task 11). An analyst tells
// the administrator something went wrong — a search came back empty, an
// answer looked off — and can see the state of everything they've already
// filed. This page never talks about "authentication": the admin seat is a
// soft gate the page doesn't touch (see Admin.tsx), and this route is open
// to everyone, same as Settings.
//
// The one property worth protecting above the rest: attaching a conversation
// is opt-in and SAID PLAINLY. The picker defaults to no attachment, and the
// consent sentence only renders once one is actually chosen — an analyst
// should never learn after the fact that their conversation went along with
// the report.
const CONSENT_COPY =
  "Attaching shares this conversation with the administrator — they will be able to read everything in it.";

export function ReportIssue() {
  const [me, setMe] = useState<api.Me | null>(null);
  const [chats, setChats] = useState<api.HistoryRow[]>([]);

  const [description, setDescription] = useState("");
  const [expected, setExpected] = useState("");
  const [conversationId, setConversationId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [reports, setReports] = useState<api.IssueReport[]>([]);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [reportsError, setReportsError] = useState<string | null>(null);
  // Fix: "the shared folder couldn't be read" is not "you haven't filed
  // anything" — the empty-state sentence below would otherwise assert a fact
  // derived from an unknown state.
  const [reportsUnreachable, setReportsUnreachable] = useState(false);

  const loadReports = useCallback(() => {
    setReportsLoading(true);
    setReportsError(null);
    return api
      .issues()
      .then((r) => {
        setReports(r.reports);
        setReportsUnreachable(r.unreachable === true);
      })
      .catch((err) =>
        setReportsError(
          err instanceof Error ? err.message : "Could not load your reports.",
        ),
      )
      .finally(() => setReportsLoading(false));
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.me().then((m) => !cancelled && setMe(m)).catch(() => {});
    // A failed history load just means an empty picker — the report can
    // still be filed with no conversation attached, so this stays silent.
    api
      .listHistory()
      .then((h) => !cancelled && setChats(h.conversations))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmedDescription = description.trim();
    // No dead-click: the button is already disabled for this case, but a
    // stray Enter in the textarea still routes through here.
    if (!trimmedDescription || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await api.submitIssue({
        description: trimmedDescription,
        ...(expected.trim() ? { expected: expected.trim() } : {}),
        ...(conversationId ? { conversation_id: conversationId } : {}),
      });
      setDescription("");
      setExpected("");
      setConversationId("");
      // Refetch rather than splice the POST's response into the list — the
      // whole point of this page is that a filed report visibly exists, and
      // reading it back from the server is what actually proves it saved.
      await loadReports();
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Could not submit your report.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page-report" data-testid="report-issue">
      <div className="wrap">
        <h1>Report an issue</h1>

        <section className="card adm-panel" data-testid="report-form">
          <form onSubmit={submit}>
            <label className="adm-field">
              <span className="adm-label">What happened</span>
              <textarea
                required
                rows={4}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>

            <label className="adm-field">
              <span className="adm-label">What you expected (optional)</span>
              <textarea
                rows={2}
                value={expected}
                onChange={(e) => setExpected(e.target.value)}
              />
            </label>

            <label className="adm-field">
              <span className="adm-label">
                Attach one of your conversations (optional)
              </span>
              <select
                value={conversationId}
                onChange={(e) => setConversationId(e.target.value)}
              >
                <option value="">Don&rsquo;t attach a conversation</option>
                {chats.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </select>
              {conversationId ? (
                <span className="adm-warn" data-testid="report-consent">
                  {CONSENT_COPY}
                </span>
              ) : null}
            </label>

            {/* The auto-captured context, stated rather than hidden — the
                server records who filed this and when, and this sentence is
                the only place that happens, so nothing is collected on the
                analyst without their seeing it said. */}
            <p className="adm-hint" data-testid="report-context">
              This report will be filed as <strong>{me?.user ?? "you"}</strong>
              , timestamped the moment you send it.
            </p>

            {submitError ? (
              <p className="adm-warn" role="alert" data-testid="report-submit-error">
                {submitError}
              </p>
            ) : null}

            <button
              type="submit"
              className="adm-btn"
              data-testid="report-submit"
              disabled={!description.trim() || submitting}
            >
              {submitting ? "Sending…" : "Submit report"}
            </button>
          </form>
        </section>

        <section className="card adm-panel" data-testid="report-history">
          <h2>Your reports</h2>
          {reportsLoading ? (
            <p className="adm-empty">Loading…</p>
          ) : reportsError ? (
            <p className="adm-warn" role="alert" data-testid="report-history-error">
              {reportsError}
            </p>
          ) : reportsUnreachable ? (
            <p className="adm-warn" role="alert" data-testid="report-history-unreachable">
              The shared folder couldn&rsquo;t be read just now.
            </p>
          ) : reports.length === 0 ? (
            <p className="adm-empty">You haven&rsquo;t filed a report yet.</p>
          ) : (
            <ul className="rpt-list">
              {reports.map((r) => (
                <li
                  key={r.id}
                  data-testid="report-row"
                  className={r.status === "resolved" ? "rpt-row is-resolved" : "rpt-row"}
                >
                  {r.unreadable ? (
                    // The tmp+replace write pattern (spec E5) makes this rare,
                    // but a torn file must render as a visible row, never a
                    // silently shortened list.
                    <p className="adm-warn">
                      This report couldn&rsquo;t be read back — the file on the
                      shared drive may be damaged.
                    </p>
                  ) : (
                    <>
                      <p className="rpt-desc">{r.description}</p>
                      {r.expected ? (
                        <p className="adm-hint">Expected: {r.expected}</p>
                      ) : null}
                      <p className="rpt-meta">
                        Filed {when(r.submitted_at)}
                        {" · "}
                        <span className="rpt-status">
                          {r.status === "resolved" ? "Resolved" : "Not resolved yet"}
                        </span>
                      </p>
                      {r.admin_note ? (
                        <p className="adm-note" data-testid="report-admin-note">
                          The administrator&rsquo;s note: {r.admin_note}
                        </p>
                      ) : null}
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}
