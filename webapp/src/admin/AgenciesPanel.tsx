import { useEffect, useState } from "react";
import * as api from "../api";
import { CollapsibleCard } from "./Card";

// Agencies the office added, for the upload page's agency picker.
//
// WHY THIS EXISTS AND THE ALIAS PANEL NEXT DOOR DOES NOT COVER IT. That one
// teaches SEARCH new words for an agency the app already knows about. This
// one is for an agency the app does NOT know about — created, merged or
// renamed by the Legislature since the shipped 157-agency catalog was
// built. Without it, a budget request from a new agency has no correct name
// to be filed under, and the person uploading it has no way to say so.
//
// 🔴 THE STAKES ARE DELIBERATELY LOWER HERE THAN NEXT DOOR, and the copy
// says so rather than implying otherwise. A bad alias silently sends
// searches to the wrong agency. A name added here only decides what one
// uploaded document is CALLED — visible on the search page the moment
// anybody looks, and correctable by removing the entry.
//
// Every mutation re-reads the server's list rather than patching a local
// copy: the server is what de-duplicates (case- and spacing-insensitively,
// against BOTH sources), so a locally appended row could show an admin an
// agency that was actually refused.

export function AgenciesPanel() {
  const [rows, setRows] = useState<api.AgencyOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");

  async function reload() {
    try {
      setRows(await api.agencies());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  async function add() {
    const typed = name.trim();
    if (!typed) return;
    setError(null);
    setBusy(true);
    try {
      await api.addAgency(typed);
      setName("");
      await reload();
    } catch (e) {
      // The server's own sentence, verbatim — it is the one that knows
      // whether this name ships with the app, duplicates one already added,
      // or is too long to be a title.
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(canonicalId: string) {
    setError(null);
    setBusy(true);
    try {
      await api.removeAgency(canonicalId);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const office = (rows ?? []).filter((r) => r.source === "office");
  const shipped = (rows ?? []).filter((r) => r.source === "catalog").length;

  return (
    <CollapsibleCard
      title="Agencies"
      testId="admin-agencies"
      hint={
        rows === null
          ? "Loading…"
          : office.length === 0
            ? `${shipped} agencies ship with the app`
            : `${shipped} ship with the app, ${office.length} added here`
      }
    >
      <p className="adm-note">
        These are the agencies someone can choose from when they upload an
        agency’s budget request. The {shipped} that ship with the app cover
        every agency in the state budget as of 2026 — add one only when the
        Legislature creates or renames an agency and it is missing from the
        list.
      </p>

      {error && (
        <p className="adm-note">
          <span className="err">{error}</span>
        </p>
      )}

      {office.length > 0 && (
        <ul className="adm-agency-list" data-testid="office-agencies">
          {office.map((row) => (
            <li key={row.canonical_id}>
              <span className="adm-agency-name">{row.name}</span>
              <button
                type="button"
                className="fchip"
                disabled={busy}
                onClick={() => void remove(row.canonical_id)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="adm-agency-add">
        <label>
          Agency name
          <input
            type="text"
            value={name}
            placeholder="e.g. Office of Broadband"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="allbtn"
          disabled={busy || !name.trim()}
          onClick={() => void add()}
        >
          Add
        </button>
      </div>

      {/* Removing is not undoing. Said plainly because the opposite is the
          natural assumption, and an admin who expects a removal to fix a
          document's title will otherwise go looking for the change and not
          find it. */}
      <p className="adm-note">
        Removing an agency stops it being offered. Documents already uploaded
        under it keep the name they were given.
      </p>
    </CollapsibleCard>
  );
}
