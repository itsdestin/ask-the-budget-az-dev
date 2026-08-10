# Budget Documents — Content Search + Format Chooser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore full-text (retrieval) search with in-app PDF provenance to the Budget Documents page, and restore the Linked-TOC vs Single-File-PDF chooser — both on top of the browse-first page rather than by reverting it.

**Architecture:** The page keeps ONE search box with two modes. Title mode filters the already-loaded corpus listing client-side (unchanged). Content mode calls the existing `POST /api/search` retrieval pipeline. Escalation between them is automatic at zero title hits after a 2000ms pause, and manual via an always-visible toggle. Content results render as one card per document with the best passage quoted as the headline; clicking a passage opens the existing `SourcePanel` PDF drawer. No backend or retrieval code changes.

**Tech Stack:** React 19 + TypeScript + Vite, `vitest` + `@testing-library/react` for webapp tests, FastAPI + pytest for the backend (untouched here), plain CSS in one `app.css`.

**Spec:** `docs/superpowers/specs/2026-08-10-budget-documents-content-search-design.md`

## Global Constraints

- **No backend changes.** `retrieval/`, `ingest/`, `chunking/`, `citation/` and `harness/system-prompt.md` are untouched, so **no eval run is required**. If a task would change any of them, stop and re-read the spec's Testing section.
- **Every non-trivial edit carries a WHY comment.** Destin is a non-developer and relies on them. Record the *evidence* that drove a choice, not just the choice.
- **Never write a misleading error message.** Surface the backend's own `detail` verbatim (the `api.ts` client already puts it in the thrown `Error`); never replace a real error with a guessed cause. Never tell a reader to "clear a filter" when no filter is set.
- **Never `dangerouslySetInnerHTML`.** Snippets are corpus text, not trusted markup. Query highlighting goes through the `highlight()` helper in Task 4, which returns runs the component renders as elements.
- **CSS is scoped under the page class.** Every rule added to `app.css` for this page starts with `.page-docs `. A `position: fixed` overlay must still render INSIDE `<main className="page-docs">` or it gets no styling at all.
- **A row with no verified URL renders unlinked, never a dead `href`.**
- **Vocabulary:** the page counts **reports**; the things inside a report are **sections**. Content results are counted in **passages** and **documents**.
- **Run before claiming any task done:** `cd webapp && npx tsc -b --noEmit && npx vitest run`.

---

## File Structure

| File | Responsibility |
|---|---|
| `webapp/src/components/DocIcons.tsx` | **Create.** The four inline SVG glyphs (doc, book, chevron, open) currently private to `Search.tsx`, so the new components can share them. |
| `webapp/src/components/ReportChooser.tsx` | **Create.** F2's modal: the two format choices, focus trap, Escape. Self-contained. |
| `webapp/src/search/contentSearch.ts` | **Create.** Pure, dependency-free helpers: rail filters → `SearchFilters`, grouping `SearchResult[]` into per-document cards, query highlighting. All unit-testable without React. |
| `webapp/src/components/PassageCard.tsx` | **Create.** F1's result card: quoted headline, identity row, "More from this document", passage tiles. |
| `webapp/src/pages/Search.tsx` | **Modify.** Page state (mode, debounce, URL sync, content fetch), layout, and both result panels. |
| `webapp/src/reportFamilies.ts` | **Modify.** Add `slugsForFamily` — the inverse of the family map, so the filter mapping has one source of truth. |
| `webapp/src/styles/app.css` | **Modify.** Recovered modal CSS + the settled card/tile/loading/toggle rules. |
| `webapp/src/search/contentSearch.test.ts` | **Create.** Unit tests for the pure helpers. |
| `webapp/src/components/ReportChooser.test.tsx` | **Create.** Focus trap, Escape, both/one/neither. |
| `webapp/src/pages/Search.content.test.tsx` | **Create.** Content-mode behaviour, kept out of the browse test file so neither grows unwieldy. |
| `webapp/src/pages/Search.test.tsx` | **Modify.** Only where the top-line report row changes (Task 3). |

---

## Task 0: Commit the built regression fixes

The four regression fixes (R1–R4) and the six mockups are already written and passing in the worktree but uncommitted. They are self-contained and nothing below depends on them being *uncommitted*.

**Files:** everything currently modified in the worktree.

- [ ] **Step 1: Verify the tree is green before committing anything**

```bash
cd webapp && npx tsc -b --noEmit && npx vitest run && cd ..
.venv/bin/python -m pytest tests/ -q
```
Expected: `tsc` silent, `570 passed`, `2167 passed, 5 skipped`.

- [ ] **Step 2: Commit the backend fix**

```bash
git add app/routes/corpus.py tests/test_corpus_documents_route.py
git commit -m "fix(corpus): list only BUDGET documents, not the shared sidecar

documents.json is one sidecar for both corpora and carries no corpus
field, so /api/corpus/documents was handing fiscal notes to the Budget
Documents page. Read membership from budget_chunks instead of guessing
from doc_type: /api/upload accepts any registered doc_type against
either corpus, so a denylist would leak."
```

- [ ] **Step 3: Commit the frontend fixes**

```bash
git add webapp/src/pages/Search.tsx webapp/src/pages/Search.test.tsx \
        webapp/src/publishers.ts webapp/src/reportFamilies.ts \
        webapp/src/styles/app.css
git rm --cached -q webapp/src/components/FilterBar.tsx webapp/src/components/ResultCard.tsx 2>/dev/null || true
git add -A webapp/src/components
git commit -m "fix(docs-page): honest empty states, report-level counts, dead code

- Empty states name only facts that are true: 'try clearing one' appears
  only when a filter is set; an empty listing names NO cause, because the
  route cannot tell an un-ingested corpus from an unreadable one.
- Counts are top-level REPORTS, derived from what renders. The old count
  was computed independently and disagreed: groupCorpus silently dropped
  families outside the curated five while still counting their documents.
  Unknown families now render and are filterable.
- Sections, not documents, for what lives inside a report.
- Deleted FilterBar, ResultCard, FILTER_BUCKETS and 259 lines of
  .page-search CSS — all orphaned by the browse rewrite."
```

- [ ] **Step 4: Commit the spec, plan and mockups**

```bash
git add docs/superpowers/specs/2026-08-10-budget-documents-content-search-design.md \
        docs/superpowers/plans/2026-08-10-budget-documents-content-search.md \
        mockups/
git commit -m "docs: content-search + format-chooser spec, plan and mockups"
```

---

## Task 1: Extract the shared glyphs

`DocIcon`, `BookIcon`, `ChevronIcon` and `OpenIcon` are private to `Search.tsx` but Tasks 2 and 6 need them. Pure move — no markup changes, so the existing tests are the regression check.

**Files:**
- Create: `webapp/src/components/DocIcons.tsx`
- Modify: `webapp/src/pages/Search.tsx:163-196` (delete the four local definitions), `:1-9` (add the import)

**Interfaces:**
- Produces: `DocIcon()`, `BookIcon()`, `ChevronIcon()`, `OpenIcon()` — all `(): JSX.Element`, no props.

- [ ] **Step 1: Create the module**

```tsx
// webapp/src/components/DocIcons.tsx
// The document-row glyphs, paths verbatim from the approved browse mockup
// (mockups/budget-documents-browse.html). Extracted from pages/Search.tsx
// 2026-08-10 so the report chooser and the passage card can draw the same
// marks — three copies of one <path> is how two of them silently drift.
//
// aria-hidden on every one: each sits beside its own text label, so an
// accessible name here would make a screen reader read the label twice.

export function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M6 2h9l5 5v15H6z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}

export function BookIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M4 4h13a2 2 0 0 1 2 2v14H6a2 2 0 0 1-2-2z" />
      <path d="M4 18a2 2 0 0 1 2-2h13" />
    </svg>
  );
}

export function ChevronIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

export function OpenIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}
```

- [ ] **Step 2: Delete the four local definitions from `Search.tsx`**

Remove the whole block from the `// ----- Glyphs -----` banner comment through the end of `OpenIcon` (currently lines 158–196), and add to the import block at the top:

```tsx
import { BookIcon, ChevronIcon, DocIcon, OpenIcon } from "../components/DocIcons";
```

- [ ] **Step 3: Verify nothing rendered differently**

```bash
cd webapp && npx tsc -b --noEmit && npx vitest run
```
Expected: `tsc` silent, `570 passed`. A pure move must not change a single assertion.

- [ ] **Step 4: Commit**

```bash
git add webapp/src/components/DocIcons.tsx webapp/src/pages/Search.tsx
git commit -m "refactor(docs-page): extract the row glyphs into components/DocIcons"
```

---

## Task 2: The report format chooser modal

**Files:**
- Create: `webapp/src/components/ReportChooser.tsx`
- Create: `webapp/src/components/ReportChooser.test.tsx`
- Modify: `webapp/src/styles/app.css` (append the recovered modal block)

**Interfaces:**
- Consumes: `BookIcon`, `DocIcon`, `OpenIcon` from Task 1; `ReportFormats` from `../reportFamilies` (`{ singleFile: string | null; linkedToc: string | null }`).
- Produces: `<ReportChooser title={string} formats={ReportFormats} onClose={() => void} />`.

- [ ] **Step 1: Write the failing tests**

```tsx
// webapp/src/components/ReportChooser.test.tsx
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

test("Tab from the last control wraps to the first — focus never escapes", () => {
  render(<ReportChooser title="FY 2027 Baseline" formats={BOTH} onClose={() => {}} />);
  const nodes = screen.getAllByRole("link");
  const close = screen.getByRole("button", { name: /close/i });
  const last = close.compareDocumentPosition(nodes[nodes.length - 1]) & Node.DOCUMENT_POSITION_FOLLOWING
    ? nodes[nodes.length - 1] : close;
  last.focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(document.activeElement).not.toBe(last);
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd webapp && npx vitest run src/components/ReportChooser.test.tsx
```
Expected: FAIL — `Failed to resolve import "./ReportChooser"`.

- [ ] **Step 3: Implement the component**

```tsx
// webapp/src/components/ReportChooser.tsx
// The report-format chooser: JLBC publishes an annual report BOTH as a
// "Linked Table of Contents" index (each agency/section its own smaller PDF)
// and as one complete "Single File PDF". Recovered 2026-08-10 from master's
// components/ResultCard.tsx — markup and copy verbatim — after the
// browse-first rewrite wired "Full report" straight to singleFile and made
// linkedToc unreachable data.
//
// WHY a modal and not two inline pills (Destin, 2026-08-10): most readers do
// not know what a "Linked Table of Contents" PDF is, and "best for jumping
// straight to one agency without downloading the whole report" has nowhere to
// live in a pill. The dialog is the only place that copy fits.
//
// It is the ONLY modal on this page — every other control is inline — so it
// owes the two things a lone dialog usually forgets: focus goes IN on open and
// is RESTORED on close, and focus cannot Tab back out to the page behind it.

import { useEffect, useRef } from "react";

import { BookIcon, DocIcon, OpenIcon } from "./DocIcons";
import type { ReportFormats } from "../reportFamilies";

/** Everything focusable the sheet can contain. Queried live on each Tab
 *  rather than cached: a one-format chooser has fewer nodes than a
 *  two-format one, and caching would trap focus on a stale list. */
const FOCUSABLE = 'a[href], button:not([disabled])';

export function ReportChooser({
  title,
  formats,
  onClose,
}: {
  title: string;
  formats: ReportFormats;
  onClose: () => void;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  // Move focus in, and put it back where it came from on close. Without the
  // restore, closing the dialog drops focus onto <body> and a keyboard user
  // has to Tab from the top of the page to get back to the report they were
  // reading.
  useEffect(() => {
    restoreTo.current = document.activeElement as HTMLElement | null;
    sheet.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    return () => restoreTo.current?.focus?.();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const nodes = sheet.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!nodes?.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      // Wrap at both ends. jsdom does not move focus on Tab, so the test for
      // this asserts the wrap, not the browser's own default step.
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="report-modal open"
      role="dialog"
      aria-modal="true"
      aria-label="Open the full report"
      // Backdrop click only — currentTarget is the backdrop, so a click that
      // started inside the sheet never closes it.
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" ref={sheet}>
        <div className="mhead">
          <span className="mic">
            <BookIcon />
          </span>
          <span className="mt">
            <b>{title}</b>
            <span>Choose how you&rsquo;d like to open it</span>
          </span>
          <button className="mx" type="button" aria-label="Close" onClick={onClose}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div className="mbody">
          {formats.linkedToc && (
            <a
              className="choice linked"
              href={formats.linkedToc}
              target="_blank"
              rel="noopener noreferrer"
              onClick={onClose}
            >
              <span className="cic">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" />
                  <path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
                </svg>
              </span>
              <span className="cc">
                <b>Linked Table of Contents</b>
                <p>An index page where each agency and section is a link that opens its own smaller PDF.</p>
                <span className="best">
                  Best for jumping straight to one agency or section without downloading the whole report.
                </span>
              </span>
              <span className="carr">
                <OpenIcon />
              </span>
            </a>
          )}
          {formats.singleFile && (
            <a
              className="choice single"
              href={formats.singleFile}
              target="_blank"
              rel="noopener noreferrer"
              onClick={onClose}
            >
              <span className="cic">
                <DocIcon />
              </span>
              <span className="cc">
                <b>Single File PDF</b>
                <p>The complete report as one document — every agency and summary in a single PDF.</p>
                <span className="best">
                  Best for reading start to finish, searching the whole report, or printing. Largest download.
                </span>
              </span>
              <span className="carr">
                <OpenIcon />
              </span>
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Append the recovered CSS to `app.css`**

Append at the end of the `.page-docs` block (immediately before the `@media (max-width:860px)` rule that closes it):

```css
/* ===== report-format chooser modal =====
   Declarations recovered verbatim 2026-08-10 from the deleted `.page-search`
   block (`git show HEAD~:webapp/src/styles/app.css`), themselves verbatim from
   the mockup's `#reportModal`. Only the scope changed — `.page-search` no
   longer exists, and an id inside a per-card component is a page-wide
   uniqueness claim it cannot keep, hence the class.
   The `.open` class is always present because React mounts it only while open. */
.page-docs .report-modal{position:fixed;inset:0;background:rgba(24,27,61,.42);display:none;align-items:center;justify-content:center;padding:20px;z-index:1000;}
.page-docs .report-modal.open{display:flex;}
.page-docs .report-modal .modal{width:100%;max-width:440px;background:var(--card);border-radius:var(--r-lg);box-shadow:0 18px 50px rgba(27,27,61,.28);overflow:hidden;animation:rmpop .16s ease;}
@keyframes rmpop{from{opacity:0;transform:translateY(8px) scale(.98);}to{opacity:1;transform:none;}}
@media (prefers-reduced-motion:reduce){.page-docs .report-modal .modal{animation:none;}}
.page-docs .report-modal .mhead{padding:18px 20px 14px;border-bottom:1px solid var(--line);display:flex;align-items:flex-start;gap:12px;}
.page-docs .report-modal .mic{flex:0 0 38px;width:38px;height:38px;border-radius:11px;background:var(--navy);color:#fff;display:grid;place-items:center;}
.page-docs .report-modal .mic svg{width:18px;height:18px;}
.page-docs .report-modal .mt{flex:1;min-width:0;}
.page-docs .report-modal .mt b{display:block;font-size:16px;color:var(--navy);font-weight:900;}
.page-docs .report-modal .mt span{display:block;font-size:13px;color:var(--ink-3);font-weight:600;margin-top:1px;}
.page-docs .report-modal .mx{flex:0 0 auto;width:30px;height:30px;border-radius:50%;border:0;background:var(--canvas);color:var(--ink-3);cursor:pointer;display:grid;place-items:center;}
.page-docs .report-modal .mx:hover{background:#eceef6;color:var(--ink);}
.page-docs .report-modal .mx svg{width:15px;height:15px;}
.page-docs .report-modal .mbody{padding:14px;display:flex;flex-direction:column;gap:12px;}
.page-docs .report-modal .choice{display:flex;gap:13px;padding:15px;border:1.5px solid var(--line);border-radius:var(--r-md);text-decoration:none;color:inherit;transition:border-color .15s,background .15s,box-shadow .15s;}
.page-docs .report-modal .choice:hover,.page-docs .report-modal .choice:focus-visible{border-color:var(--az-gold);background:#f7fbff;box-shadow:var(--shadow-sm);text-decoration:none;}
.page-docs .report-modal .choice .cic{flex:0 0 40px;width:40px;height:40px;border-radius:11px;display:grid;place-items:center;}
.page-docs .report-modal .choice.linked .cic{background:var(--az-gold-100);color:var(--az-gold-d);}
.page-docs .report-modal .choice.single .cic{background:#fbe9e7;color:#c0392b;}
.page-docs .report-modal .choice .cic svg{width:20px;height:20px;}
.page-docs .report-modal .choice .cc{flex:1;min-width:0;}
.page-docs .report-modal .choice .cc b{display:block;font-size:15px;color:var(--navy);font-weight:800;}
.page-docs .report-modal .choice .cc p{margin:5px 0 0;font-size:13px;color:var(--ink-2);font-weight:600;line-height:1.5;}
.page-docs .report-modal .choice .cc .best{display:block;margin-top:6px;font-size:12px;color:var(--ink-3);font-weight:700;}
.page-docs .report-modal .choice .carr{flex:0 0 auto;align-self:center;color:var(--ink-3);}
.page-docs .report-modal .choice:hover .carr{color:var(--az-gold-d);}
.page-docs .report-modal .choice .carr svg{width:18px;height:18px;}
```

- [ ] **Step 5: Run to verify they pass**

```bash
cd webapp && npx vitest run src/components/ReportChooser.test.tsx
```
Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/components/ReportChooser.tsx webapp/src/components/ReportChooser.test.tsx \
        webapp/src/styles/app.css
git commit -m "feat(docs-page): restore the Linked TOC vs Single File PDF chooser

Recovered from master's ResultCard, which the browse rewrite deleted after
wiring Full report straight to singleFile. Adds the focus trap and Escape
handling the original never had — it is the only modal on this page."
```

---

## Task 3: Wire the chooser into the report row

"Full report" replaces the top-line "Open" pill; the duplicate button leaves the dashed block.

**Files:**
- Modify: `webapp/src/pages/Search.tsx` — `ReportRow` (currently `:235-262`), `FamilyCard`'s two `.grp-full` anchors (currently `:323` and `:366`), and the page body (mount the modal)
- Modify: `webapp/src/styles/app.css`
- Modify: `webapp/src/pages/Search.test.tsx`

**Interfaces:**
- Consumes: `<ReportChooser>` from Task 2; `reportFormats(family, year)` from `../reportFamilies`.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing tests**

Add to `webapp/src/pages/Search.test.tsx`:

```tsx
test("the report row's own action is Full report, not a generic Open", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  const row = screen.getByText("FY 2027 Baseline").closest(".doc")!;
  expect(row).toHaveTextContent(/full report/i);
  expect(row).not.toHaveTextContent(/^Open$/);
  // …and the dashed block below no longer repeats it.
  const card = row.closest(".grp")!;
  expect(card.querySelector(".ctx")!.textContent).not.toMatch(/full report/i);
});

test("a report with BOTH formats opens the chooser instead of navigating", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // FY 2027 Baseline has both a single-file and a linked-TOC URL, so its row
  // must be a button — an interactive pill nested in an <a> is invalid markup.
  const row = screen.getByText("FY 2027 Baseline").closest(".doc")!;
  expect(row.tagName).toBe("BUTTON");
  fireEvent.click(row);
  expect(screen.getByRole("dialog", { name: /open the full report/i })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /linked table of contents/i })).toBeInTheDocument();
});

test("a report with ONE format links straight to it — no pointless chooser", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /Fiscal Year 2026:/i }));
  const row = screen.getByText("FY 2026 Annual Financial Report").closest(".doc")!;
  expect(row.tagName).toBe("A");
  fireEvent.click(row);
  expect(screen.queryByRole("dialog")).toBeNull();
});
```

**Fixture note:** `DOCS` in `Search.test.tsx` gives `afr26` a `doc_url`, and `reportFormats("Annual Financial Report", 2026)` returns no URLs, so that row falls back to `docs[0].doc_url` — one format, straight link. `FY 2027 Baseline` has both in `REPORT_FORMATS`. No fixture change needed.

- [ ] **Step 2: Run to verify they fail**

```bash
cd webapp && npx vitest run src/pages/Search.test.tsx -t "Full report"
```
Expected: FAIL — the row still renders "Open".

- [ ] **Step 3: Replace `ReportRow`**

```tsx
/** A whole-REPORT top-level row: "FY Y Family".
 *
 *  The row IS the report, so its action is the report — "Full report"
 *  REPLACES the generic "Open" pill, and the duplicate button is gone from the
 *  dashed block below (Destin, 2026-08-10).
 *
 *  THE RULE, unchanged from master: both formats -> ask which; exactly one ->
 *  go straight to it (a one-option chooser is pointless); neither -> no pill,
 *  and the row renders unlinked rather than as a dead href.
 *
 *  WHY the both-formats case is a <button> and not an <a>: the click has to
 *  open a dialog, and an interactive control nested inside a link is invalid
 *  markup. `.doc.rowbtn` carries UA resets only, so it looks identical to the
 *  anchors beside it. */
function ReportRow({
  year,
  family,
  docs,
  onChoose,
}: {
  year: number;
  family: string;
  docs: api.CorpusDocument[];
  onChoose: () => void;
}) {
  const fy = year === 0 ? null : year;
  const title = familyTitle(family, fy);
  // A report family's documents share one publisher in this corpus, so the
  // chip reads the first document's — same posture as the mockup.
  const publisher = docs[0]?.publisher ?? "";
  const { singleFile, linkedToc } = reportFormats(family, fy);
  const both = Boolean(singleFile && linkedToc);
  const href = singleFile ?? linkedToc ?? docs[0]?.doc_url ?? null;
  const body = (
    <>
      <PubChip publisher={publisher} />
      <div className="doc-main">
        <span className="doc-title">{title}</span>
      </div>
      {(both || href) && (
        <span className="doc-pill is-full">
          <BookIcon /> Full report
        </span>
      )}
    </>
  );
  if (both) {
    return (
      <button type="button" className="doc rowbtn" onClick={onChoose}>
        {body}
      </button>
    );
  }
  return href ? (
    <a className="doc" href={href} target="_blank" rel="noopener noreferrer">
      {body}
    </a>
  ) : (
    <div className="doc doc-unlinked">{body}</div>
  );
}
```

- [ ] **Step 4: Delete both `.grp-full` anchors from `FamilyCard`**

Remove these two blocks (the idle branch and the searching branch) entirely:

```tsx
            {singleFile && (
              <a className="grp-full" href={singleFile} target="_blank" rel="noopener noreferrer">
                <BookIcon /> Full report
              </a>
            )}
```

Then delete the now-unused `const { singleFile } = reportFormats(...)` line at the top of `FamilyCard`, and thread `onChoose` down: `FamilyCard` gains an `onChoose: () => void` prop and passes it to `<ReportRow>`; `YearCard` gains the same prop and passes `() => onChoose(year, f.family)` per family.

- [ ] **Step 5: Mount the modal in the page body**

In `Search()`, add the state and render the modal as the LAST child of `<main className="page-docs">`:

```tsx
  // Which report's format chooser is open, or null. WHY it lives on the page
  // and not inside the card: `.report-modal` is `position:fixed`, and every
  // rule for it is scoped under `.page-docs` — mounted outside this <main> it
  // gets NO styling and paints as an unstyled block. (Hit exactly once, in
  // mockups/report-format-chooser.html.)
  const [chooser, setChooser] = useState<{ year: number; family: string } | null>(null);
```

```tsx
      {chooser && (
        <ReportChooser
          title={familyTitle(chooser.family, chooser.year === 0 ? null : chooser.year)}
          formats={reportFormats(chooser.family, chooser.year === 0 ? null : chooser.year)}
          onClose={() => setChooser(null)}
        />
      )}
```

- [ ] **Step 6: Add the two new CSS rules**

Append inside the `.page-docs` block:

```css
/* The report row's own action. It REPLACES the generic "Open" pill, so it
   takes the gold fill the old `.grp-full` button carried — the row's action is
   the whole report, and a canvas-grey pill would read as secondary to the
   "Browse sections" control below it. */
.page-docs .doc-pill.is-full{background:var(--az-gold);border-color:var(--az-gold);color:#fff;}
.page-docs .doc:hover .doc-pill.is-full{background:var(--az-gold-d);border-color:var(--az-gold-d);color:#fff;}
/* UA resets ONLY — a <button> row (the both-formats case) must look identical
   to the <a> rows beside it. Same shape as the fiscal-notes page's own
   "button adaptations" block. */
.page-docs .doc.rowbtn{width:100%;text-align:left;font-family:inherit;background:transparent;border:0;cursor:pointer;}
```

- [ ] **Step 7: Fix the one pre-existing test this changes**

`test("full-report links appear only where a hand-verified URL exists")` asserts a `link` named `/full report/i` with the single-file href. FY 2027 Baseline now has BOTH formats, so it is a button. Replace that test's body with:

```tsx
test("full-report actions appear only where a hand-verified URL exists", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // FY 2027 Baseline has both formats — a chooser button, not a link.
  expect(screen.getByText("FY 2027 Baseline").closest(".doc")!).toHaveTextContent(/full report/i);
  // FY 2026's Budget Bill has neither format AND no doc_url: no pill at all.
  fireEvent.click(screen.getByRole("button", { name: /Fiscal Year 2026:/i }));
  const bill = screen.getByText("FY 2026 Budget Bill").closest(".doc")!;
  expect(bill).not.toHaveTextContent(/full report/i);
  expect(bill).toHaveClass("doc-unlinked");
});
```

- [ ] **Step 8: Run the full suite**

```bash
cd webapp && npx tsc -b --noEmit && npx vitest run
```
Expected: `tsc` silent, all tests pass.

- [ ] **Step 9: Commit**

```bash
git add webapp/src/pages/Search.tsx webapp/src/pages/Search.test.tsx webapp/src/styles/app.css
git commit -m "feat(docs-page): Full report replaces Open on the report row

The top-line row IS the report, so its action is the report; the duplicate
button leaves the dashed block. Both formats -> the chooser (a <button>,
because an interactive pill inside an <a> is invalid); one -> straight link;
neither -> unlinked row."
```

---

## Task 4: The pure content-search helpers

No React. Everything here is a function with an input and an output, so it is cheap to test exhaustively before any UI exists.

**Files:**
- Modify: `webapp/src/reportFamilies.ts` (add `slugsForFamily`)
- Create: `webapp/src/search/contentSearch.ts`
- Create: `webapp/src/search/contentSearch.test.ts`

**Interfaces:**
- Produces, and Tasks 5–7 depend on these exact signatures:
  - `slugsForFamily(family: string): string[]`
  - `toSearchFilters(types: ReadonlySet<string>, years: ReadonlySet<number>): SearchFilters`
  - `interface PassageDoc { doc_id: string; doc_title: string; publisher: string; doc_url: string | null; passages: SearchResult[] }`
  - `groupPassages(results: SearchResult[]): PassageDoc[]`
  - `highlight(text: string, query: string): { text: string; hit: boolean }[]`

- [ ] **Step 1: Write the failing tests**

```ts
// webapp/src/search/contentSearch.test.ts
import type { SearchResult } from "../api";
import { groupPassages, highlight, toSearchFilters } from "./contentSearch";
import { slugsForFamily } from "../reportFamilies";

function hit(over: Partial<SearchResult>): SearchResult {
  return {
    chunk_id: "c1", doc_id: "d1", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "text", page: 1, score: 1, doc_type: "baseline-per-agency",
    fiscal_year: 2027, publisher: "jlbc", agencies: [], doc_url: null,
    doc_meta: null, ...over,
  };
}

test("a family maps to every doc_type slug that belongs to it", () => {
  expect(slugsForFamily("Baseline").sort())
    .toEqual(["baseline-cross-cut", "baseline-per-agency"]);
  expect(slugsForFamily("Annual Financial Report")).toEqual(["afr"]);
});

test("an unknown family maps to itself — familyOf's own contract", () => {
  // familyOf returns the raw slug for an unrecognised doc_type, so that slug
  // IS the family name and filtering on it must still reach the backend.
  expect(slugsForFamily("some-new-doc-type")).toEqual(["some-new-doc-type"]);
});

test("rail filters become backend filters, expanding families to slugs", () => {
  expect(toSearchFilters(new Set(["Baseline"]), new Set([2027]))).toEqual({
    doc_type: ["baseline-per-agency", "baseline-cross-cut"],
    fiscal_year: [2027],
  });
});

test("no filters means an empty object, never empty arrays", () => {
  // The backend treats an explicit [] as a filter that matches nothing; only
  // an absent key means "any".
  expect(toSearchFilters(new Set(), new Set())).toEqual({});
});

test("the 'fiscal year unknown' bucket is never sent as a real year", () => {
  // Year 0 is this page's own bucket for documents with no fiscal_year. The
  // backend has no such value; sending it would filter everything out.
  expect(toSearchFilters(new Set(), new Set([0]))).toEqual({});
  expect(toSearchFilters(new Set(), new Set([0, 2027]))).toEqual({ fiscal_year: [2027] });
});

test("passages collapse to one entry per document, best passage first", () => {
  const groups = groupPassages([
    hit({ chunk_id: "a", doc_id: "d1", score: 0.2 }),
    hit({ chunk_id: "b", doc_id: "d2", score: 0.9, doc_title: "Other" }),
    hit({ chunk_id: "c", doc_id: "d1", score: 0.7 }),
  ]);
  expect(groups.map((g) => g.doc_id)).toEqual(["d2", "d1"]);
  expect(groups[1].passages.map((p) => p.chunk_id)).toEqual(["c", "a"]);
});

test("one document never yields two cards", () => {
  const groups = groupPassages([
    hit({ chunk_id: "a", doc_id: "d1" }),
    hit({ chunk_id: "b", doc_id: "d1" }),
    hit({ chunk_id: "c", doc_id: "d1" }),
  ]);
  expect(groups).toHaveLength(1);
  expect(groups[0].passages).toHaveLength(3);
});

test("highlight splits a snippet into matched and unmatched runs", () => {
  expect(highlight("The child care subsidy rose", "child care")).toEqual([
    { text: "The ", hit: false },
    { text: "child care", hit: true },
    { text: " subsidy rose", hit: false },
  ]);
});

test("highlight is case-insensitive but preserves the ORIGINAL casing", () => {
  expect(highlight("AHCCCS funding", "ahcccs")).toEqual([
    { text: "AHCCCS", hit: true },
    { text: " funding", hit: false },
  ]);
});

test("highlight with no match, or an empty query, returns one plain run", () => {
  expect(highlight("nothing here", "zzz")).toEqual([{ text: "nothing here", hit: false }]);
  expect(highlight("nothing here", "   ")).toEqual([{ text: "nothing here", hit: false }]);
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd webapp && npx vitest run src/search/contentSearch.test.ts
```
Expected: FAIL — `Failed to resolve import "./contentSearch"`.

- [ ] **Step 3: Add `slugsForFamily` to `reportFamilies.ts`**

Immediately after `familyOf`:

```ts
/** Every doc_type slug that belongs to a family — the inverse of `familyOf`.
 *
 *  Derived from FAMILY_OF_DOC_TYPE rather than written out a second time: two
 *  hand-maintained lists of the same slugs is exactly how a filter silently
 *  stops matching a doc_type someone added to only one of them.
 *
 *  A family with no curated slugs maps to ITSELF, because `familyOf` returns
 *  the raw slug for an unrecognised doc_type — so for those, the family name
 *  and the slug are the same string. */
export function slugsForFamily(family: string): string[] {
  const slugs = Object.entries(FAMILY_OF_DOC_TYPE)
    .filter(([, name]) => name === family)
    .map(([slug]) => slug);
  return slugs.length ? slugs : [family];
}
```

- [ ] **Step 4: Create `contentSearch.ts`**

```ts
// webapp/src/search/contentSearch.ts
// Pure helpers for the Budget Documents page's CONTENT search mode — the
// retrieval-backed half. No React, no fetch: everything here is input ->
// output so it can be tested exhaustively without mounting a page.
//
// Content mode calls the existing POST /api/search. Nothing in retrieval/
// changes; this module only translates between the page's vocabulary (report
// FAMILIES, a "fiscal year unknown" bucket) and the API's (doc_type SLUGS,
// real fiscal years).

import type { SearchFilters, SearchResult } from "../api";
import { slugsForFamily } from "../reportFamilies";

/** Translate the rail's two multi-selects into the API's filter object.
 *
 *  Two translations, each load-bearing:
 *
 *  1. The rail holds FAMILY names ("Baseline"); the API wants doc_type SLUGS
 *     ("baseline-per-agency", "baseline-cross-cut"). One family is many slugs.
 *  2. Year 0 is this page's bucket for documents whose fiscal_year is null. It
 *     is not a fiscal year the backend has ever heard of, so it is dropped —
 *     sending it would filter every result out.
 *
 *  An emptied dimension is OMITTED, never sent as `[]`: the backend reads an
 *  explicit empty list as "match nothing", while an absent key means "any". */
export function toSearchFilters(
  types: ReadonlySet<string>,
  years: ReadonlySet<number>,
): SearchFilters {
  const filters: SearchFilters = {};
  if (types.size) {
    const slugs = [...types].flatMap(slugsForFamily);
    if (slugs.length) filters.doc_type = slugs;
  }
  if (years.size) {
    const real = [...years].filter((y) => y !== 0);
    if (real.length) filters.fiscal_year = real;
  }
  return filters;
}

/** One document's worth of matching passages — the unit the result card
 *  renders. ONE card per document: two documents from the same report in the
 *  same year are two cards, but one document is never two cards. */
export interface PassageDoc {
  doc_id: string;
  doc_title: string;
  publisher: string;
  /** The document's own source PDF, or null when unknown. */
  doc_url: string | null;
  /** Best passage first. */
  passages: SearchResult[];
}

/** Collapse a flat result list into one entry per document.
 *
 *  ONE posture for both orderings — passages within a document, and documents
 *  against each other — rather than trusting the provider's insertion order
 *  for groups while re-sorting passages. A provider that returns rows
 *  ungrouped, or a future one that re-ranks, then still produces
 *  best-document-first, which is the only order this page claims to show. */
export function groupPassages(results: SearchResult[]): PassageDoc[] {
  const byDoc = new Map<string, PassageDoc>();
  for (const r of results) {
    let group = byDoc.get(r.doc_id);
    if (!group) {
      group = {
        doc_id: r.doc_id,
        doc_title: r.doc_title,
        publisher: r.publisher,
        doc_url: r.doc_url,
        passages: [],
      };
      byDoc.set(r.doc_id, group);
    }
    group.passages.push(r);
  }
  const groups = [...byDoc.values()];
  for (const g of groups) g.passages.sort((a, b) => b.score - a.score);
  groups.sort((a, b) => b.passages[0].score - a.passages[0].score);
  return groups;
}

/** Split a snippet into matched / unmatched runs for the query term.
 *
 *  WHY this returns runs instead of an HTML string: the snippet is corpus
 *  text, and building `<mark>` markup from it would mean
 *  dangerouslySetInnerHTML on data this app does not control. The component
 *  renders these runs as real elements instead.
 *
 *  Case-insensitive matching, but each run carries the ORIGINAL casing — an
 *  analyst reading "AHCCCS" must not be shown "ahcccs" because that is what
 *  they typed. */
export function highlight(text: string, query: string): { text: string; hit: boolean }[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [{ text, hit: false }];
  const runs: { text: string; hit: boolean }[] = [];
  const haystack = text.toLowerCase();
  let i = 0;
  while (i < text.length) {
    const at = haystack.indexOf(needle, i);
    if (at === -1) {
      runs.push({ text: text.slice(i), hit: false });
      break;
    }
    if (at > i) runs.push({ text: text.slice(i, at), hit: false });
    runs.push({ text: text.slice(at, at + needle.length), hit: true });
    i = at + needle.length;
  }
  return runs.length ? runs : [{ text, hit: false }];
}
```

- [ ] **Step 5: Run to verify they pass**

```bash
cd webapp && npx vitest run src/search/contentSearch.test.ts
```
Expected: `10 passed`.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/search/contentSearch.ts webapp/src/search/contentSearch.test.ts \
        webapp/src/reportFamilies.ts
git commit -m "feat(docs-page): pure helpers for content search

Family->slug filter mapping (derived from FAMILY_OF_DOC_TYPE, not a second
hand-maintained list), passage grouping, and query highlighting that returns
runs rather than HTML so no corpus text ever reaches innerHTML."
```

---

## Task 5: Mode state, URL sync, and the content fetch

No new UI in this task — the page still renders title results only. This wires the machinery and pins it with tests.

**Files:**
- Modify: `webapp/src/pages/Search.tsx`
- Create: `webapp/src/pages/Search.content.test.tsx`

**Interfaces:**
- Consumes: `toSearchFilters`, `groupPassages` from Task 4.
- Produces (used by Tasks 6–7): page-local `mode: "titles" | "contents"`, `content: ContentPhase`, `setMode(m)`, `retry()`.

**Design notes, decided in the spec:**
- **All URL writes use `replace: true`.** Keystroke-level history entries are noise; the goals that matter (shareable links, correct restore on reload, no identical-query dead end) are all met by replace. Walking individual searches with Back was a nice-to-have and is deliberately not built.
- **Editing the query resets to title mode.** A new query is a new search, and title mode is the cheap default; escalation re-arms and fires again if titles return nothing.

- [ ] **Step 1: Write the failing tests**

```tsx
// webapp/src/pages/Search.content.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Search } from "./Search";
import * as api from "../api";

// Content (retrieval) mode. The browse/title half lives in Search.test.tsx;
// splitting them keeps either file readable.

const DOCS: api.CorpusDocument[] = [
  { doc_id: "b27-ahcccs", title: "FY 2027 Baseline — AHCCCS", publisher: "jlbc",
    doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/axs.pdf" },
  { doc_id: "afr26", title: "FY 2026 Annual Financial Report", publisher: "agao",
    doc_type: "afr", fiscal_year: 2026, doc_url: "https://x/afr26.pdf" },
];

const HITS: api.SearchResult[] = [
  { chunk_id: "c1", doc_id: "b27-ahcccs", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "The FY 2027 Baseline includes $89,432,700 for child care subsidy assistance.",
    page: 142, score: 0.9, doc_type: "baseline-per-agency", fiscal_year: 2027,
    publisher: "jlbc", agencies: [], doc_url: "https://x/axs.pdf", doc_meta: null },
  { chunk_id: "c2", doc_id: "b27-ahcccs", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "The child care waiting list contained 6,218 children.",
    page: 143, score: 0.5, doc_type: "baseline-per-agency", fiscal_year: 2027,
    publisher: "jlbc", agencies: [], doc_url: "https://x/axs.pdf", doc_meta: null },
];

function mount(entry = "/search", hits = HITS) {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  const search = vi.spyOn(api, "search").mockResolvedValue({
    results: hits, total: hits.length, provider: "test",
  });
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Search />
    </MemoryRouter>,
  );
  return search;
}

const box = () => screen.getByLabelText(/filter documents by agency or keyword/i);

test("no title match escalates to content search after the pause", async () => {
  vi.useFakeTimers();
  const search = mount();
  await vi.waitFor(() => expect(screen.getByText(/Fiscal Year 2027/)).toBeInTheDocument());
  fireEvent.change(box(), { target: { value: "child care subsidy" } });
  expect(search).not.toHaveBeenCalled();       // not yet — the pause has not elapsed
  await vi.advanceTimersByTimeAsync(2000);
  expect(search).toHaveBeenCalledWith("child care subsidy", {}, "budget");
  vi.useRealTimers();
});

test("a query that DOES match a title never escalates on its own", async () => {
  vi.useFakeTimers();
  const search = mount();
  await vi.waitFor(() => expect(screen.getByText(/Fiscal Year 2027/)).toBeInTheDocument());
  fireEvent.change(box(), { target: { value: "ahcccs" } });
  await vi.advanceTimersByTimeAsync(5000);
  expect(search).not.toHaveBeenCalled();
  vi.useRealTimers();
});

test("the rail's filters reach the backend as doc_type SLUGS", async () => {
  vi.useFakeTimers();
  const search = mount();
  await vi.waitFor(() => expect(screen.getByText(/Fiscal Year 2027/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: /document type/i }));
  fireEvent.click(screen.getByRole("button", { name: /^Baseline/ }));
  fireEvent.change(box(), { target: { value: "child care subsidy" } });
  await vi.advanceTimersByTimeAsync(2000);
  expect(search).toHaveBeenCalledWith(
    "child care subsidy",
    { doc_type: ["baseline-per-agency", "baseline-cross-cut"] },
    "budget",
  );
  vi.useRealTimers();
});

test("?q= and ?in=contents restore a content search on load", async () => {
  const search = mount("/search?q=child%20care&in=contents");
  await waitFor(() => expect(search).toHaveBeenCalledWith("child care", {}, "budget"));
});

test("the box writes ?q= so a search can be linked", async () => {
  mount();
  await screen.findByText(/Fiscal Year 2027/);
  fireEvent.change(box(), { target: { value: "ahcccs" } });
  await waitFor(() => expect(window.location.search).toContain("q=ahcccs"));
});

test("a failed content search surfaces the backend's own detail", async () => {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  vi.spyOn(api, "search").mockRejectedValue(new Error("search: query is empty"));
  render(
    <MemoryRouter initialEntries={["/search?q=zzz&in=contents"]}>
      <Search />
    </MemoryRouter>,
  );
  expect(await screen.findByText(/search: query is empty/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd webapp && npx vitest run src/pages/Search.content.test.tsx
```
Expected: FAIL — `api.search` is never called.

- [ ] **Step 3: Add the mode + content state to `Search()`**

Replace the existing `const [params] = useSearchParams();` / `urlQuery` / `useEffect(() => setQuery(urlQuery), [urlQuery]);` block with:

```tsx
/** Which half of the search the page is showing. */
type Mode = "titles" | "contents";

/** The content (retrieval) request's state. One value, so loading / error /
 *  ready can never be true at the same time. */
type ContentPhase =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; results: api.SearchResult[] }
  | { kind: "error"; message: string };

/** How long the box must be quiet, with ZERO title matches, before content
 *  search fires on its own. Long enough that it never fires mid-word; short
 *  enough that it feels like the page answering rather than the user waiting. */
const ESCALATE_MS = 2000;
```

Inside `Search()`:

```tsx
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(() => (params.get("q") ?? "").trim());
  const [mode, setMode] = useState<Mode>(() =>
    params.get("in") === "contents" ? "contents" : "titles",
  );
  const [content, setContent] = useState<ContentPhase>({ kind: "idle" });
  // Bumped to re-run an identical content query. WHY it exists: the fetch
  // effect keys off (mode, query, filters); pressing Retry after a failure
  // changes none of them, so without this the button would appear to do
  // nothing — the exact dead end master's own `attempt` counter existed for.
  const [contentAttempt, setContentAttempt] = useState(0);

  // --- URL <-> state, one direction at a time -------------------------------
  // `lastWritten` is what stops the two effects below from fighting: the write
  // effect records the string it put in the URL, and the read effect ignores
  // any URL it recognises as its own. Anything else is an OUTSIDE navigation
  // (Home's hero, a pasted link, Back) and is read into state.
  //
  // Every write is `replace: true`. Keystroke-level history entries are noise;
  // shareable links, correct restore on reload, and killing the identical-query
  // dead end are all satisfied without them (Destin, 2026-08-10).
  const lastWritten = useRef<string | null>(null);

  useEffect(() => {
    const next = new URLSearchParams();
    if (query) next.set("q", query);
    if (mode === "contents") next.set("in", "contents");
    const str = next.toString();
    if (str === lastWritten.current) return;
    lastWritten.current = str;
    setParams(next, { replace: true });
  }, [query, mode, setParams]);

  useEffect(() => {
    const str = params.toString();
    if (str === lastWritten.current) return;
    lastWritten.current = str;
    setQuery((params.get("q") ?? "").trim());
    setMode(params.get("in") === "contents" ? "contents" : "titles");
  }, [params]);
```

Delete the old one-way `useEffect(() => setQuery(urlQuery), [urlQuery]);` and every remaining reference to `urlQuery`.

- [ ] **Step 4: Add the escalation and fetch effects**

Place these directly after `const searching = q !== "";` and its neighbours, and after `visibleGroups` is computed (the escalation needs the title-hit count):

```tsx
  // How many documents the TITLE filter matched. Zero is what arms escalation.
  const titleHits = useMemo(
    () => (searching ? docs.filter((d) => passesFilters(d, types, years) && queryHit(d, q)).length : 0),
    [docs, types, years, q, searching],
  );

  // Automatic escalation. A natural-language question essentially never
  // substring-matches a document title, while an agency name almost always
  // does — so "zero title hits" is an honest proxy for "this was a question
  // about CONTENT". Only fires from title mode, only with a query, only at
  // zero hits, and only after the box goes quiet.
  useEffect(() => {
    if (mode !== "titles" || !searching || titleHits > 0) return;
    // Nothing to escalate to until the listing has loaded — a corpus that has
    // not arrived yet has zero title hits for every query.
    if (phase.kind !== "ready") return;
    const timer = setTimeout(() => setMode("contents"), ESCALATE_MS);
    return () => clearTimeout(timer);
  }, [mode, searching, titleHits, phase.kind]);

  // The content request itself. `ignore` is the stale-response guard: if the
  // query or the filters change while a request is in flight, React runs this
  // cleanup first, so the older (slower) answer returns here and does nothing
  // instead of painting over the newer one.
  useEffect(() => {
    if (mode !== "contents" || !searching) {
      setContent({ kind: "idle" });
      return;
    }
    let ignore = false;
    setContent({ kind: "loading" });
    api.search(q, toSearchFilters(types, years), "budget").then(
      (res) => {
        if (!ignore) setContent({ kind: "ready", results: res.results });
      },
      (err: unknown) => {
        // The api client already carries the backend's own `detail`; show it
        // verbatim rather than guessing at a cause.
        if (!ignore)
          setContent({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          });
      },
    );
    return () => {
      ignore = true;
    };
  }, [mode, q, types, years, searching, contentAttempt]);

  const passageDocs = useMemo(
    () => (content.kind === "ready" ? groupPassages(content.results) : []),
    [content],
  );
```

- [ ] **Step 5: Reset to title mode when the query changes**

Change the rail input's `onChange` and the clear button:

```tsx
                  onChange={(e) => {
                    // A new query is a new search, and titles are the cheap
                    // default — so editing the box always returns to title
                    // mode and re-arms escalation. Staying in content mode
                    // would fire a retrieval request on every keystroke.
                    setQuery(e.target.value);
                    setMode("titles");
                  }}
```

```tsx
  const clearQuery = () => {
    setQuery("");
    setMode("titles");
    box.current?.focus();
  };
```

- [ ] **Step 6: Add the imports**

```tsx
import { groupPassages, toSearchFilters } from "../search/contentSearch";
```

- [ ] **Step 7: Render the error so its test can see it**

Inside the `searching ?` branch's `<section className="yg">`, before the tiles, add:

```tsx
                {content.kind === "error" && (
                  <p className="empty">
                    <span className="err">{content.message}</span>{" "}
                    <button type="button" className="grp-more" onClick={() => setContentAttempt((a) => a + 1)}>
                      Retry
                    </button>
                  </p>
                )}
```

- [ ] **Step 8: Run the tests**

```bash
cd webapp && npx tsc -b --noEmit && npx vitest run
```
Expected: `tsc` silent; `Search.content.test.tsx` `6 passed`; every other suite still passing.

- [ ] **Step 9: Commit**

```bash
git add webapp/src/pages/Search.tsx webapp/src/pages/Search.content.test.tsx
git commit -m "feat(docs-page): content-search mode, URL state and escalation

Escalates to POST /api/search 2000ms after the box goes quiet with zero
title matches; filters reach the backend as doc_type slugs. ?q= and
?in=contents round-trip, which also kills the identical-query dead end the
rewrite reintroduced when it dropped master's attempt counter."
```

---

## Task 6: The passage card

**Files:**
- Create: `webapp/src/components/PassageCard.tsx`
- Modify: `webapp/src/styles/app.css`

**Interfaces:**
- Consumes: `PassageDoc`, `highlight` from Task 4; `DocIcon`/`ChevronIcon` from Task 1; `publisherLabel` from `../publishers`.
- Produces: `<PassageCard doc={PassageDoc} query={string} trayOpen={boolean} onToggleTray={() => void} onOpenPassage={(chunkId: string) => void} />`

- [ ] **Step 1: Create the component**

```tsx
// webapp/src/components/PassageCard.tsx
// ONE content-search result: one card per DOCUMENT (Destin, 2026-08-10).
// Two documents from the same report in the same fiscal year are two cards;
// one document is never two cards.
//
// The headline row is the best matching PASSAGE, quoted — not the document
// title. WHY: the reader escalated to content search because they had a
// question, and the sentence that answers it is the result. A document title
// tells them which book to open, which is what title mode already did.
//
// The dashed block carries the document's identity and exactly ONE action,
// "More from this document". No "Open document", no "Full report" — the
// format chooser belongs to the browse card, not this one.

import { publisherLabel } from "../publishers";
import { ChevronIcon } from "./DocIcons";
import { highlight, type PassageDoc } from "../search/contentSearch";
import type { SearchResult } from "../api";

/** The quoted passage, with the query term marked.
 *
 *  Runs come from `highlight()` and are rendered as ELEMENTS — the snippet is
 *  corpus text, so building markup from it and setting innerHTML would be
 *  handing untrusted content to the DOM. */
function Quote({ text, query }: { text: string; query: string }) {
  return (
    <span className="doc-quote">
      {highlight(text, query).map((run, i) =>
        run.hit ? <mark key={i}>{run.text}</mark> : <span key={i}>{run.text}</span>,
      )}
    </span>
  );
}

/** One passage row. It is a real <button>: the href would be a placeholder,
 *  the handler is what opens the source, and provenance is the one path that
 *  must not require a pointing device. The page pill carries the arrow that
 *  says so (the A1 affordance). */
function PassageRow({
  passage,
  query,
  onOpen,
}: {
  passage: SearchResult;
  query: string;
  onOpen: (chunkId: string) => void;
}) {
  return (
    <button type="button" className="doc quoterow" onClick={() => onOpen(passage.chunk_id)}>
      <div className="doc-main">
        <Quote text={passage.snippet} query={query} />
      </div>
      <span className="doc-pill">
        {passage.page === null ? "no page" : `p. ${passage.page}`}
        <span className="go" aria-hidden="true">
          →
        </span>
      </span>
    </button>
  );
}

export function PassageCard({
  doc,
  query,
  trayOpen,
  onToggleTray,
  onOpenPassage,
}: {
  doc: PassageDoc;
  query: string;
  trayOpen: boolean;
  onToggleTray: () => void;
  onOpenPassage: (chunkId: string) => void;
}) {
  const [best, ...rest] = doc.passages;
  return (
    <article className="grp">
      <button type="button" className="doc quoterow" onClick={() => onOpenPassage(best.chunk_id)}>
        <span className="doc-pub">{publisherLabel(doc.publisher)}</span>
        <div className="doc-main">
          <Quote text={best.snippet} query={query} />
        </div>
        <span className="doc-pill">
          {best.page === null ? "no page" : `p. ${best.page}`}
          <span className="go" aria-hidden="true">
            →
          </span>
        </span>
      </button>
      <div className="ctx">
        <div className="ctx-row">
          <span className="doc-pub">{publisherLabel(doc.publisher)}</span>
          <span className="badge">{doc.doc_title}</span>
          <span className="spacer" />
          {rest.length > 0 && (
            <button
              type="button"
              className={trayOpen ? "grp-more open" : "grp-more"}
              aria-expanded={trayOpen}
              onClick={onToggleTray}
            >
              More from this document <ChevronIcon />
            </button>
          )}
        </div>
        {trayOpen && rest.length > 0 && (
          <div className="tray open">
            {rest.map((p) => (
              <PassageRow key={p.chunk_id} passage={p} query={query} onOpen={onOpenPassage} />
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
```

Note the import list: **no `DocIcon`**. The identity row deliberately carries
no glyph before the document title (Destin, 2026-08-10), so importing one
would be an unused import and `npm run build` would fail on it.

- [ ] **Step 2: Add the card CSS**

Append inside the `.page-docs` block:

```css
/* ===== content-search result card =====
   The snippet is the card's HEADLINE, so it needs a multi-line reading style
   rather than `.doc-title`'s single-line 15.5px/700 navy. `align-items:
   flex-start` is what stops the publisher chip and the page pill from
   centring against a three-line quote. */
.page-docs .quoterow{align-items:flex-start;cursor:pointer;width:100%;text-align:left;font-family:inherit;background:transparent;border:0;}
.page-docs .quoterow .doc-pub{margin-top:3px;}
.page-docs .quoterow .doc-pill{margin-top:1px;}
.page-docs .doc-quote{display:block;font-size:14px;font-weight:600;color:var(--ink);line-height:1.55;}
.page-docs .doc-quote mark{background:var(--az-gold-100);color:var(--az-gold-d);border-radius:3px;padding:0 3px;font-weight:800;}
.page-docs .tray .doc-quote{font-size:13.5px;}
/* The A1 affordance: the page pill grows an arrow and lights gold, the same
   cue the browse rows' "Open" pill already carries. :focus-visible is listed
   beside :hover because the row is reachable by keyboard and the cue must not
   be mouse-only. */
.page-docs .quoterow .doc-pill .go{display:inline-block;transition:transform .14s;}
.page-docs .quoterow:hover .doc-pill,.page-docs .quoterow:focus-visible .doc-pill{border-color:var(--az-gold);color:var(--az-gold-d);background:var(--az-gold-100);}
.page-docs .quoterow:hover .doc-pill .go{transform:translateX(2px);}
/* Expanded passages: white tiles on the dashed block's tint, and NO border-top
   on the tray — the identity row and the tiles are one continuous surface
   (Destin, 2026-08-10). Spacing dialled in on sliders the same day:
   10 / 5 / 12 / 14 / 10 / 14.
   NOTE the `.open` in the selector. The base rule is
   `.page-docs .ctx .tray.open{display:block}` — one class MORE specific than
   `.page-docs .ctx .tray` — so a plain `display:flex` here LOSES, the tray
   stays block-laid-out, and `gap` is silently ignored. */
.page-docs .ctx-row{padding-bottom:10px;}
.page-docs .ctx .tray.open{padding:0 14px 12px;display:flex;flex-direction:column;gap:5px;}
.page-docs .ctx .tray .doc{background:#fff;border:1px solid var(--line);border-radius:var(--r-sm);padding:10px 14px;box-shadow:var(--shadow-sm);}
.page-docs .ctx .tray .doc:hover{border-color:var(--az-gold);background:#fff;}
```

- [ ] **Step 3: Verify it compiles (no test yet — Task 7 mounts it)**

```bash
cd webapp && npx tsc -b --noEmit && npx vitest run
```
Expected: `tsc` silent, existing tests unchanged.

- [ ] **Step 4: Commit**

```bash
git add webapp/src/components/PassageCard.tsx webapp/src/styles/app.css
git commit -m "feat(docs-page): the content-search passage card

One card per document, best passage quoted as the headline with the query
term marked. Highlighting renders runs as elements — no innerHTML on
corpus text."
```

---

## Task 7: Render content mode — header, toggle, empty states, loading

**Files:**
- Modify: `webapp/src/pages/Search.tsx`
- Modify: `webapp/src/pages/Search.content.test.tsx`
- Modify: `webapp/src/styles/app.css`

**Interfaces:**
- Consumes: `<PassageCard>` (Task 6), `mode`/`content`/`passageDocs`/`setMode` (Task 5).

- [ ] **Step 1: Write the failing tests**

Append to `webapp/src/pages/Search.content.test.tsx`:

```tsx
test("content results render one card per document with the passage quoted", async () => {
  mount("/search?q=child%20care&in=contents");
  expect(await screen.findByText(/89,432,700/)).toBeInTheDocument();
  // Two passages, ONE document, therefore ONE card.
  expect(document.querySelectorAll(".grp")).toHaveLength(1);
  expect(screen.getByText("p. 142")).toBeInTheDocument();
});

test("the query term is marked inside the quote", async () => {
  mount("/search?q=child%20care&in=contents");
  await screen.findByText(/89,432,700/);
  expect(document.querySelector("mark")).toHaveTextContent("child care");
});

test("the header names which search produced the list", async () => {
  mount("/search?q=child%20care&in=contents");
  expect(await screen.findByText(/searching document contents/i)).toBeInTheDocument();
});

test("More from this document reveals the remaining passages", async () => {
  mount("/search?q=child%20care&in=contents");
  await screen.findByText(/89,432,700/);
  expect(screen.queryByText(/6,218 children/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /more from this document/i }));
  expect(screen.getByText(/6,218 children/)).toBeInTheDocument();
});

test("the toggle switches modes and is present on BOTH sides", async () => {
  mount("/search?q=child%20care&in=contents");
  await screen.findByText(/89,432,700/);
  fireEvent.click(screen.getByRole("button", { name: /back to title matches/i }));
  expect(await screen.findByText(/searching document titles/i)).toBeInTheDocument();
  // No title matches for this query — but the way back must still be there.
  expect(screen.getByRole("button", { name: /search document contents/i })).toBeInTheDocument();
});

test("content search finding nothing says so, and does not blame filters", async () => {
  mount("/search?q=zzqx&in=contents", []);
  expect(await screen.findByText(/no passages inside the ingested documents mention/i))
    .toBeInTheDocument();
  expect(screen.queryByText(/clearing/i)).toBeNull();
});

test("the toggle is hidden while the request is in flight", async () => {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  vi.spyOn(api, "search").mockReturnValue(new Promise(() => {})); // never settles
  render(
    <MemoryRouter initialEntries={["/search?q=child%20care&in=contents"]}>
      <Search />
    </MemoryRouter>,
  );
  expect(await screen.findByText(/searching document contents/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /back to title matches/i })).toBeNull();
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd webapp && npx vitest run src/pages/Search.content.test.tsx
```
Expected: FAIL — no passage cards render.

- [ ] **Step 3: Replace the `searching ?` branch of the results column**

```tsx
            ) : searching ? (
              <>
                <section className="yg">
                  <div className="yg-head-static">
                    <div className="yg-ttl">
                      {/* The header names the MODE. Without it there is no way
                          to tell which of the two searches produced the list. */}
                      <span className="yg-yr">
                        Results{" "}
                        <span className="yg-mode">
                          (searching document {mode === "contents" ? "contents" : "titles"})
                        </span>
                      </span>
                      <span className="yg-meta">
                        {mode === "contents"
                          ? `${content.kind === "ready" ? content.results.length : 0} passage${
                              content.kind === "ready" && content.results.length === 1 ? "" : "s"
                            } · ${passageDocs.length} document${
                              passageDocs.length === 1 ? "" : "s"
                            } matching “${q}”`
                          : `${searchTiles.length} report${
                              searchTiles.length === 1 ? "" : "s"
                            } matching “${q}”`}
                      </span>
                    </div>
                  </div>

                  {mode === "contents" ? (
                    content.kind === "loading" ? (
                      <div className="docload" role="status">
                        <span className="spin" aria-hidden="true" />
                        <span>
                          Searching document contents
                          <span className="dots" aria-hidden="true" />
                          <span className="sub">
                            This may take a moment — reading inside every ingested PDF.
                          </span>
                        </span>
                      </div>
                    ) : content.kind === "error" ? (
                      <p className="empty">
                        <span className="err">{content.message}</span>{" "}
                        <button
                          type="button"
                          className="grp-more"
                          onClick={() => setContentAttempt((a) => a + 1)}
                        >
                          Retry
                        </button>
                      </p>
                    ) : passageDocs.length === 0 ? (
                      // Names what was searched — the text INSIDE the
                      // documents — so an empty answer never reads as "the
                      // corpus says nothing about this" when only titles were
                      // checked. And no filter advice unless a filter is set.
                      <p className="empty">
                        No passages inside the ingested documents mention “{q}”
                        {hasFilters ? " with those filters. Try clearing a filter." : "."}
                      </p>
                    ) : (
                      passageDocs.map((d) => (
                        <PassageCard
                          key={d.doc_id}
                          doc={d}
                          query={q}
                          trayOpen={openTrays.has(d.doc_id)}
                          onToggleTray={() => toggleTray(d.doc_id)}
                          onOpenPassage={setOpenPassage}
                        />
                      ))
                    )
                  ) : searchTiles.length === 0 ? (
                    <p className="empty">
                      {hasFilters
                        ? `No document titles match “${q}” with those filters — try clearing one.`
                        : `No document titles match “${q}”.`}
                    </p>
                  ) : (
                    searchTiles.map(({ year, family }) => (
                      <FamilyCard
                        key={`${year}|${family.family}`}
                        year={year}
                        group={family}
                        query={q}
                        trayOpen={openTrays.has(`${year}|${family.family}`)}
                        onToggleTray={() => toggleTray(`${year}|${family.family}`)}
                        onChoose={() => setChooser({ year, family: family.family })}
                      />
                    ))
                  )}
                </section>

                {/* The toggle. ALWAYS shown once the box has text — including
                    on both empty states, so neither is ever a dead end. Hidden
                    ONLY while a request is in flight: there is nothing to
                    toggle to while the answer is pending, and offering it
                    invites a click that cancels work nobody asked to start. */}
                {!(mode === "contents" && content.kind === "loading") && (
                  <div className="allbar">
                    <button
                      type="button"
                      className={mode === "contents" ? "allbtn on" : "allbtn"}
                      aria-pressed={mode === "contents"}
                      onClick={() => setMode(mode === "contents" ? "titles" : "contents")}
                    >
                      <span className="all-off">
                        <SearchIcon /> Search document contents
                      </span>
                      <span className="all-on">↩ Back to title matches</span>
                    </button>
                  </div>
                )}
              </>
            ) : visibleGroups.length === 0 ? (
```

- [ ] **Step 4: Add the passage-drawer state and the import**

```tsx
import { PassageCard } from "../components/PassageCard";
```

```tsx
  // The chunk whose source drawer is open, or null. Task 8 renders it; this
  // task only needs somewhere for a passage click to land.
  const [openPassage, setOpenPassage] = useState<string | null>(null);
```

- [ ] **Step 5: Add the mode-label, toggle-face and loading CSS**

Append inside the `.page-docs` block:

```css
/* The header's mode qualifier — lighter and smaller than the "Results" word
   it follows, so the heading still reads as one thing. */
.page-docs .yg-mode{font-size:13px;font-weight:700;color:var(--ink-3);margin-left:7px;}
/* The toggle's two faces, lifted from `.page-fiscal-notes .all-off`/`.all-on`
   — the same control this one mirrors. */
.page-docs .all-off,.page-docs .all-on{display:inline-flex;align-items:center;gap:9px;}
.page-docs .all-on{display:none;}
.page-docs .allbtn.on{color:var(--navy);border-color:var(--navy-100);background:var(--navy-100);}
.page-docs .allbtn.on .all-off{display:none;}
.page-docs .allbtn.on .all-on{display:inline-flex;}
.page-docs .allbtn svg{width:16px;height:16px;flex:0 0 auto;}
/* The escalation line. The spinner is the only genuinely new primitive on this
   page; the rolling ellipsis is a content animation, so reduced-motion gets a
   static "…" rather than nothing (an ellipsis that never appears would make a
   finished search look unfinished). */
.page-docs .docload{display:flex;align-items:flex-start;gap:12px;padding:20px 22px;font-size:14px;font-weight:700;color:var(--ink-2);}
.page-docs .spin{flex:0 0 auto;width:17px;height:17px;margin-top:2px;border:2.5px solid var(--az-gold-100);border-top-color:var(--az-gold);border-radius:50%;animation:docspin .7s linear infinite;}
@keyframes docspin{to{transform:rotate(360deg);}}
.page-docs .dots::after{content:"";animation:docdots 1.4s steps(4,end) infinite;}
@keyframes docdots{0%{content:"";}25%{content:".";}50%{content:"..";}75%{content:"...";}}
.page-docs .docload .sub{display:block;font-size:12.5px;font-weight:600;color:var(--ink-3);margin-top:3px;}
@media (prefers-reduced-motion:reduce){
  .page-docs .spin{animation:none;}
  .page-docs .dots::after{animation:none;content:"…";}
}
```

- [ ] **Step 6: Update the status line for content mode**

Replace the `phase.kind === "ready" &&` expression in `.docstatus`:

```tsx
          {phase.kind === "ready" &&
            (mode === "contents" && searching
              ? content.kind === "ready"
                ? `${content.results.length} passage${content.results.length === 1 ? "" : "s"} in ${passageDocs.length} document${passageDocs.length === 1 ? "" : "s"}, matching “${q}”.`
                : ""
              : searching
                ? `${reportCount} report${reportCount === 1 ? "" : "s"} in ${yearScope}, matching “${q}”.`
                : `${reportCount} report${reportCount === 1 ? "" : "s"}, across ${yearScope}.`)}
```

- [ ] **Step 7: Run the tests**

```bash
cd webapp && npx tsc -b --noEmit && npx vitest run
```
Expected: `tsc` silent, all suites pass.

- [ ] **Step 8: Commit**

```bash
git add webapp/src/pages/Search.tsx webapp/src/pages/Search.content.test.tsx webapp/src/styles/app.css
git commit -m "feat(docs-page): render content results, the mode toggle and its states

Header names which search produced the list; the toggle is present on both
empty states and hidden only in flight; each empty state names what was
actually searched."
```

---

## Task 8: Re-wire the source drawer

The last deleted piece. `SourcePanel` still exists and still works — the rewrite only removed its wiring and its test.

**Files:**
- Modify: `webapp/src/pages/Search.tsx`
- Create: `webapp/src/pdf/__tests__/search-source-panel.test.tsx`

**Interfaces:**
- Consumes: `openPassage` (Task 7), `passageDocs` (Task 5).
- `SourcePanel` props: `{ chunkId: string; corpus?: string; docTitle: string; fiscalYear?: number | null; onClose(): void }`.

- [ ] **Step 1: Write the failing tests**

```tsx
// webapp/src/pdf/__tests__/search-source-panel.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Search } from "../../pages/Search";
import * as api from "../../api";

// Restores the coverage deleted with the browse rewrite. Provenance is the
// point of this page: a passage that cannot be opened back to its own PDF
// page is a quote with no source.

const DOCS: api.CorpusDocument[] = [
  { doc_id: "b27", title: "FY 2027 Baseline — AHCCCS", publisher: "jlbc",
    doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/axs.pdf" },
];

const HITS: api.SearchResult[] = [
  { chunk_id: "chunk-142", doc_id: "b27", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "Child care subsidy assistance rose.", page: 142, score: 0.9,
    doc_type: "baseline-per-agency", fiscal_year: 2027, publisher: "jlbc",
    agencies: [], doc_url: "https://x/axs.pdf", doc_meta: null },
];

function mount() {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  vi.spyOn(api, "search").mockResolvedValue({ results: HITS, total: 1, provider: "test" });
  vi.spyOn(api, "chunk").mockResolvedValue({
    chunk_id: "chunk-142", doc_id: "b27", page: 142, bbox: null,
    text: "Child care subsidy assistance rose.", source_format: "pdf",
    pdf_unavailable_reason: null,
  });
  render(
    <MemoryRouter initialEntries={["/search?q=child%20care&in=contents"]}>
      <Search />
    </MemoryRouter>,
  );
}

test("clicking a passage opens the source drawer for THAT chunk", async () => {
  mount();
  fireEvent.click(await screen.findByText(/Child care subsidy assistance rose/));
  expect(await screen.findByRole("complementary", { name: /source passage/i }))
    .toBeInTheDocument();
  await waitFor(() => expect(api.chunk).toHaveBeenCalledWith("chunk-142", "budget"));
});

test("the drawer opens from the KEYBOARD — provenance is not mouse-only", async () => {
  mount();
  const row = (await screen.findByText(/Child care subsidy assistance rose/)).closest("button")!;
  row.focus();
  fireEvent.click(row); // a real <button> activates on Enter/Space via click
  expect(await screen.findByRole("complementary", { name: /source passage/i }))
    .toBeInTheDocument();
});

test("switching modes closes the drawer", async () => {
  mount();
  fireEvent.click(await screen.findByText(/Child care subsidy assistance rose/));
  await screen.findByRole("complementary", { name: /source passage/i });
  fireEvent.click(screen.getByRole("button", { name: /back to title matches/i }));
  await waitFor(() =>
    expect(screen.queryByRole("complementary", { name: /source passage/i })).toBeNull(),
  );
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd webapp && npx vitest run src/pdf/__tests__/search-source-panel.test.tsx
```
Expected: FAIL — no `complementary` region.

- [ ] **Step 3: Render the drawer**

Add the import:

```tsx
import { SourcePanel } from "../pdf/SourcePanel";
```

Add, immediately before the `{chooser && ...}` block at the end of `<main className="page-docs">`:

```tsx
      {/* Source drawer. It overlays the page rather than taking a column, so
          the results layout above is untouched. Like the chooser, it MUST
          render inside this <main>: `.pdf-drawer` is position:fixed and every
          rule for it is page-class scoped. */}
      {openPassage && (
        <SourcePanel
          // Keyed on the chunk so switching passages remounts, rather than
          // showing the previous page while the next one loads.
          key={openPassage.chunkId}
          chunkId={openPassage.chunkId}
          docTitle={openPassage.docTitle}
          fiscalYear={openPassage.fiscalYear}
          onClose={() => setOpenPassage(null)}
        />
      )}
```

- [ ] **Step 4: Widen the drawer state to carry the title**

`SourcePanel` needs the display title, and the route deliberately does not return a second one (see `app/routes/pdf.py`'s `get_chunk`). Replace Task 7's `openPassage` state and change `onOpenPassage` to resolve it from the results:

```tsx
  // The passage whose source is open, or null. Holds the display title
  // alongside the id because the row that was clicked already knows it —
  // app/routes/pdf.py's get_chunk deliberately does not return a second,
  // conflicting title.
  const [openPassage, setOpenPassage] = useState<{
    chunkId: string;
    docTitle: string;
    fiscalYear: number | null;
  } | null>(null);

  const openPassageById = (chunkId: string) => {
    const hit =
      content.kind === "ready" ? content.results.find((r) => r.chunk_id === chunkId) : undefined;
    setOpenPassage({
      chunkId,
      docTitle: hit?.doc_title ?? "",
      fiscalYear: hit?.fiscal_year ?? null,
    });
  };
```

and pass `onOpenPassage={openPassageById}` to `<PassageCard>`.

- [ ] **Step 5: Close the drawer whenever the result set changes**

```tsx
  // A new query, a new mode or a new filter means a new result set; leaving
  // the drawer open would keep a passage from the PREVIOUS search on screen
  // next to results that no longer contain it.
  useEffect(() => setOpenPassage(null), [q, mode, types, years]);
```

- [ ] **Step 6: Run the tests**

```bash
cd webapp && npx tsc -b --noEmit && npx vitest run
```
Expected: `tsc` silent, all suites pass including the three new ones.

- [ ] **Step 7: Full verification**

```bash
cd webapp && npm run build && cd ..
.venv/bin/python -m pytest tests/ -q
```
Expected: `built in …`, `2167 passed, 5 skipped`.

- [ ] **Step 8: Commit**

```bash
git add webapp/src/pages/Search.tsx webapp/src/pdf/__tests__/search-source-panel.test.tsx
git commit -m "feat(docs-page): re-wire the source drawer to content results

Restores the in-app PDF page + highlight the rewrite unwired, and the test
it deleted with it. The passage rows are real buttons, so the provenance
path works from the keyboard."
```

---

## Self-Review

**Spec coverage.** D1 replace-not-append → Task 7 Step 3. D2 always-visible toggle + hidden in flight → Task 7 Steps 1, 3. D3 mode in the header → Task 7 Step 3. D4 filters to the backend → Tasks 4, 5. D5 passage-first card → Task 6. D6 source drawer → Task 8. D7 arrow pill + keyboard → Tasks 6 (CSS, `<button>` rows), 8 (test). D8 Full report replaces Open → Task 3. D9 both/one/neither → Task 3 Step 3. D10 modal + focus trap → Task 2. D11 URL state → Task 5. R1–R4 → Task 0. Spacing → Task 6 Step 2. Loading state → Task 7. Empty states → Task 7. All four spec guards plus the two "(done)" ones are covered.

**Placeholder scan.** No TBD/TODO. Every code step carries the actual code a step needs, and no step says "similar to Task N".

**Type consistency.** `PassageDoc` is defined once in Task 4 and consumed unchanged in Tasks 6–7. `highlight()` returns `{ text, hit }[]` in both its definition and its use. `toSearchFilters(types, years)` takes the same two sets everywhere. `onOpenPassage: (chunkId: string) => void` in Task 6 matches `openPassageById` in Task 8. `ReportChooser`'s props match its call site in Task 3. `slugsForFamily` is defined in Task 4 Step 3 and used in Task 4 Step 4.

**One known ordering wrinkle:** Task 7 introduces `openPassage` as a `string | null` and Task 8 widens it to an object. That is deliberate — Task 7 is testable without the drawer, and widening is a two-line change — but an implementer working Task 8 out of order must apply Step 4 before Step 3 compiles.
