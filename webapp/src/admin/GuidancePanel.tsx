import { useEffect, useState } from "react";
import * as api from "../api";
import { CollapsibleCard } from "./Card";
import { count, when } from "./format";

// The office's own guidance for AI answers (spec E2).
//
// Self-contained on purpose: it fetches its own text and saves it with its
// own button, and it is NOT part of the page's settings draft. The settings
// draft is saved as a whole by the save bar, so if this box rode along, an
// edit here would be written by a save an admin made for some unrelated
// reason — and a half-finished spending-limit edit would be written by a save
// they made for this box.
//
// Two sentences on this panel are not decoration:
//
//  * "Changes apply to new conversations" — a conversation snapshots the
//    instructions it started with, so an admin who edits mid-chat and then
//    tests in that same chat sees no change and concludes it is broken.
//  * "ask a few test questions" — these edits do not pass through any
//    automatic checking, so a spot-check is the only check that exists. A
//    pretend approval step here would be worse than saying so.

/** Above this share of the cap, say so in words. The cap protects the bill:
 *  every request carries this text, so a runaway paste costs money on every
 *  question the whole office asks. */
const NEARLY_FULL = 0.9;

export function GuidancePanel() {
  const [saved, setSaved] = useState<api.AdminGuidance | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .adminGuidance()
      .then((g) => {
        if (cancelled) return;
        setSaved(g);
        setText(g.text);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function save() {
    setError(null);
    setOk(false);
    setBusy(true);
    try {
      // The server's copy is what everyone's answers will actually use — it
      // trims, and it may refuse. Reading it back is the only way the box
      // and the file on the share can't disagree.
      const next = await api.saveAdminGuidance(text);
      setSaved(next);
      setText(next.text);
      setOk(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // Fix: this IS a byte count (the cap the server enforces is a byte cap,
  // and its refusal already says "byte limit"). Pasted curly quotes and em
  // dashes are 3 bytes each, so labelling this "characters" made the number
  // visibly disagree with what an admin counted by eye — say "bytes" so the
  // meter agrees with the backend instead of contradicting it.
  const used = new TextEncoder().encode(text).length;
  const max = saved?.max_bytes ?? 0;
  const nearlyFull = max > 0 && used > max * NEARLY_FULL;
  const dirty = saved !== null && text !== saved.text;

  return (
    <section
      className="card adm-panel"
      aria-labelledby="adm-guidance-h"
      data-testid="admin-guidance"
    >
      <h2 id="adm-guidance-h">AI guidance</h2>

      {error && !saved ? (
        <p className="adm-warn" role="alert">
          {error}
        </p>
      ) : null}

      {saved ? (
        <CollapsibleCard
          title="Office guidance for AI answers"
          hint={
            saved.edited_by
              ? `last edited by ${saved.edited_by} · ${when(saved.edited_at)}`
              : "nothing written yet"
          }
          testId="admin-guidance-card"
        >
          <p className="adm-hint">
            This text shapes AI answers for the whole office. After editing, ask
            a few test questions to check the effect — nothing here is checked
            automatically. Changes apply to new conversations, not to ones
            already open.
          </p>

          <label className="adm-field" htmlFor="adm-guidance-text">
            <span>Office guidance</span>
            <textarea
              id="adm-guidance-text"
              className="adm-textarea"
              rows={10}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                // Fix: typing after a save left "Saved. New conversations
                // will use it." on screen beside unsaved text — clear it the
                // moment the text no longer matches what was saved.
                setOk(false);
              }}
            />
          </label>

          <div className="adm-meter" aria-hidden="true">
            <span
              className={nearlyFull ? "is-warn" : undefined}
              style={{ width: `${max > 0 ? Math.min(100, (used / max) * 100) : 0}%` }}
            />
          </div>
          <p
            className={nearlyFull ? "adm-hint is-warn" : "adm-hint"}
            data-testid="admin-guidance-size"
          >
            {count(used)} / {count(max)} bytes
            {nearlyFull ? " — close to the limit." : ""}
          </p>

          {error ? (
            <p className="adm-warn" role="alert">
              {error}
            </p>
          ) : null}
          {ok ? (
            <p className="adm-ok" role="status">
              Saved. New conversations will use it.
            </p>
          ) : null}

          <p className="adm-actions">
            <button
              type="button"
              className="adm-btn"
              onClick={save}
              disabled={!dirty || busy}
            >
              Save guidance
            </button>
            {dirty ? (
              <button
                type="button"
                className="adm-link"
                onClick={() => {
                  setText(saved.text);
                  setError(null);
                  setOk(false);
                }}
              >
                Discard changes
              </button>
            ) : null}
          </p>
        </CollapsibleCard>
      ) : error ? null : (
        <p className="adm-empty">Loading…</p>
      )}
    </section>
  );
}
