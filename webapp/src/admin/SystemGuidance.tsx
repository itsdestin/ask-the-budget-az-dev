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
//
// `data-quoted` therefore marks EXACTLY the quoted text and nothing else:
// each section's <pre> and, via CollapsibleCard's `quotedTitle`, each
// section's heading. It used to wrap whole cards (review, 2026-08-12),
// which quietly exempted the app's own chrome — the "written by your
// office" hint, the card's Show/Hide label — and would have exempted
// anything added to a card later.
//
// WHAT THIS WINDOW MUST NOT IMPLY. The sections are grouped by subject,
// not shown in the order the assistant reads them, and the office's own
// group is shown last for findability. Left unsaid, that reads as "my
// guidance is the assistant's final instruction", which is precisely
// backwards: the slot sits mid-template and the refusal rules — which
// outrank the office block by its own preamble — render after it. Hence
// GUIDANCE_POSITION_NOTE below, pinned by a spec here and by
// test_the_office_block_really_does_render_mid_prompt in
// tests/test_admin_tuning_routes.py.

/** Said wherever the office's own guidance is shown. Plain office English,
 *  no hedging: an admin who believes their words come last will write them
 *  as overrides, and they are not. */
const GUIDANCE_POSITION_NOTE =
  "Where this actually sits: your guidance is shown at the end of this " +
  "list, but the assistant does not read it last. Several sections come " +
  "after it — including the rules on when the assistant must refuse to " +
  "answer. Where your words disagree with the rules on citing sources, " +
  "refusing, or looking things up, those rules win.";

/** The one size sentence, worded for whichever state the office is in.
 *
 *  The total is the RENDERED instructions, so once anything is saved the
 *  office's own guidance is already inside that number — saying it "is
 *  added to this" at that point double-counts (review, 2026-08-12). */
function sizeLine(data: api.AdminPrompt, maxBytes: number | null): string {
  const total = `${count(data.total_lines)} lines in all — ${bytes(data.total_bytes)}`;
  const cap = maxBytes ? bytes(maxBytes) : null;
  if (data.office_guidance_present) {
    return cap
      ? `${total}, your office's own guidance included. You can write up to ${cap} of it.`
      : `${total}, your office's own guidance included.`;
  }
  return cap
    ? `${total}. Your office has not written any guidance yet; what you write in the box is added to this, up to ${cap}.`
    : `${total}. Your office has not written any guidance yet.`;
}

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
            {sizeLine(data, maxBytes)}
          </p>
        ) : null}

        {!data && !error ? <p className="adm-empty">Loading…</p> : null}

        {/* Everything above the first heading. One line today — the
            document's own title — and the assistant reads it, so a window
            captioned "everything the assistant is told" shows it. It was
            dropped on the floor until the 2026-08-12 review. */}
        {data?.lead ? (
          <div className="adm-sysg-group" data-testid="sysg-lead">
            <h3 className="adm-sysg-label">How the instructions open</h3>
            <pre className="adm-sysg-text" data-quoted="true">
              {data.lead}
            </pre>
          </div>
        ) : null}

        {data?.groups.map((group) => (
          <div className="adm-sysg-group" key={group.label}>
            {/* h3, not h4: the section cards below are h3s, so an h4 here
                made the window's outline run backwards. */}
            <h3 className="adm-sysg-label" data-testid="sysg-group-label">
              {group.label}
            </h3>
            {group.sections.some((s) => s.is_office_guidance) ? (
              <p className="adm-hint" data-testid="sysg-position">
                {GUIDANCE_POSITION_NOTE}
              </p>
            ) : null}
            {/* Index in the key because the server deliberately keeps two
                sections that share a heading (app/routes/tuning.py's
                `_grouped` filters rather than looks up) — a heading-only
                key would collide on exactly the case it protects. */}
            {group.sections.map((section, i) => (
              <SectionCard key={`${i}-${section.heading}`} section={section} />
            ))}
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
      // Verbatim, so exempt from the plain-English guard — but ONLY the
      // heading text is, not this card's hint or its Show/Hide label.
      quotedTitle
      // The one thing an admin must be able to tell apart: their own words
      // from the shipped ones. Said on the closed row, so it is visible
      // while scanning rather than only after opening. App copy, therefore
      // NOT exempt.
      hint={section.is_office_guidance ? "written by your office" : undefined}
      testId={section.is_office_guidance ? "sysg-mine" : "sysg-section"}
    >
      {section.text ? (
        <pre className="adm-sysg-text" data-quoted="true">
          {section.text}
        </pre>
      ) : null}
      {section.subsections.map((sub, i) => (
        <div className="adm-sysg-sub" key={`${i}-${sub.heading}`}>
          <CollapsibleCard title={sub.heading} quotedTitle>
            <pre className="adm-sysg-text" data-quoted="true">
              {sub.text}
            </pre>
          </CollapsibleCard>
        </div>
      ))}
    </CollapsibleCard>
  );
}
