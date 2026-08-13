import { useEffect, useState } from "react";
import * as api from "../api";
import { Modal } from "../components/Modal";
import { CollapsibleCard } from "./Card";
import { bytes, count } from "./format";

// "See System Guidance" — a read-only window onto everything the assistant
// is already told (Destin, 2026-08-12).
//
// WHY IT EXISTS: the office guidance box beside it was being written blind.
// The shipped instructions run to roughly 1,170 lines nobody in the office
// has ever seen, so guidance written without them duplicates them,
// contradicts them, or spends the whole 8,192-byte allowance restating
// something already said at length.
//
// WHY A WINDOW AND NOT A PANEL SECTION (Destin's call): this is somebody
// else's text, and it is much longer than anything else on the page.
// Inline, it would push the box an admin actually came to type in below
// the fold. One button, one window, nothing else on the panel.
//
// READ-ONLY, and it says so out loud. There is no writer for this in
// api.ts and no route behind it — harness/system-prompt.md is wired to
// citation discipline and refusal thresholds the eval suite measures.
//
// THE QUOTED TEXT IS VERBATIM, INCLUDING ITS HEADINGS. One shipped
// heading really is "What this corpus contains", which is a word this
// app keeps off its own pages. It stays as written here: the entire point
// of the window is to show exactly what the assistant reads, and a
// friendlier relabelling would make it lie about the one thing it exists
// to reveal. Everything the APP says — the title, the switch, the group
// labels, the size line — is plain office English, and the spec in
// SystemGuidance.test.tsx checks that with the window open.

/** The two sets of documents, worded as the rest of the app words them
 *  (see pages/Ai.tsx's picker). The wire names are what the route takes. */
const DOC_SETS = [
  { key: "budget", label: "Budget documents" },
  { key: "fiscal_notes", label: "Fiscal notes" },
];

export function SystemGuidanceModal({
  maxBytes,
  onClose,
}: {
  /** How much the office is allowed to add, from the guidance read. Null
   *  when that read failed — the two are independent, and one being down
   *  must not stop an admin reading the other. */
  maxBytes: number | null;
  onClose: () => void;
}) {
  const [corpus, setCorpus] = useState(DOC_SETS[0].key);
  const [data, setData] = useState<api.AdminPrompt | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Cleared, not left showing the other set's sections: a switch that
    // leaves the old text under the new label is worse than a blank moment.
    setData(null);
    setError(null);
    api
      .adminPrompt(corpus)
      .then((d) => !cancelled && setData(d))
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [corpus]);

  return (
    <Modal label="System guidance" sheetClassName="is-wide" onClose={onClose}>
      <div className="mhead">
        <span className="mt">
          <b>System guidance</b>
          <span>
            Everything the assistant is told. You can read this, but not change
            it.
          </span>
        </span>
        <button className="mx" type="button" aria-label="Close" onClick={onClose}>
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            aria-hidden="true"
          >
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        </button>
      </div>

      <div className="mbody">
        {/* Not role="tablist": there are no tab panels here, just two
            versions of one list. A pressed button says what it is. */}
        <div className="adm-tabs" role="group" aria-label="Which documents">
          {DOC_SETS.map((set) => (
            <button
              key={set.key}
              type="button"
              className={corpus === set.key ? "adm-tab is-on" : "adm-tab"}
              aria-pressed={corpus === set.key}
              onClick={() => setCorpus(set.key)}
            >
              {set.label}
            </button>
          ))}
        </div>

        {error ? (
          <p className="adm-warn" role="alert">
            {error}
          </p>
        ) : null}

        {data ? (
          <p className="adm-hint" data-testid="sysg-size">
            {count(data.total_lines)} lines in all — {bytes(data.total_bytes)}.
            {maxBytes
              ? ` What your office writes in the guidance box is added to this, up to ${bytes(maxBytes)}.`
              : ""}
            {data.office_guidance_present
              ? ""
              : " Your office has not written any guidance yet."}
          </p>
        ) : null}

        {!data && !error ? <p className="adm-empty">Loading…</p> : null}

        {data?.groups.map((group) => (
          <div className="adm-sysg-group" key={group.label}>
            <h4 className="adm-sysg-label" data-testid="sysg-group-label">
              {group.label}
            </h4>
            {/* `data-quoted` marks the assistant's OWN words, headings
                included. The jargon spec strips these before checking the
                app's vocabulary — see the note at the top of this file. */}
            <div data-quoted="true">
              {group.sections.map((section) => (
                <SectionCard key={section.heading} section={section} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}

function SectionCard({ section }: { section: api.PromptSection }) {
  return (
    <CollapsibleCard
      title={section.heading}
      // The one thing an admin must be able to tell apart: their own words
      // from the shipped ones. Said on the closed row, so it is visible
      // while scanning rather than only after opening.
      hint={section.is_office_guidance ? "written by your office" : undefined}
      testId={section.is_office_guidance ? "sysg-mine" : "sysg-section"}
    >
      {section.text ? <pre className="adm-sysg-text">{section.text}</pre> : null}
      {section.subsections.map((sub) => (
        <div className="adm-sysg-sub" key={sub.heading}>
          <CollapsibleCard title={sub.heading}>
            <pre className="adm-sysg-text">{sub.text}</pre>
          </CollapsibleCard>
        </div>
      ))}
    </CollapsibleCard>
  );
}
