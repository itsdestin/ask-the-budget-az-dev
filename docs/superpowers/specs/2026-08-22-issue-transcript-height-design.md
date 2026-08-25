# Issue-inbox transcript gets a bounded scroll region

**Date:** 2026-08-22 · **Scope:** one CSS rule change. No code, copy, storage or route changes.

## Problem (STATUS provenance)

STATUS.md, "Admin extensions" → "Standing caveat — nobody has looked at it", item 3:
*"A long attached conversation in the issue inbox. The transcript viewer has no
`max-height`, so it makes an arbitrarily tall card."* An analyst can attach a whole
AI-Mode conversation to an issue report (a deliberate E3 feature, with consent copy);
the admin inbox renders every line of it, so one long chat makes that report's card —
and the whole Issues panel — hundreds of screens tall. The admin scrolls the PAGE to
get past one report, which breaks the house rule that content scrolls inside its own
container, never the page.

## Evidence

- `webapp/src/admin/IssuesPanel.tsx:63–79` — `Conversation({transcript})` renders
  `<ol className="adm-convo" data-testid="admin-issue-transcript">`, one `<li>` per
  spoken line. Used at `IssuesPanel.tsx:151` inside `ReportRow`.
- `webapp/src/styles/app.css:2936–2940` — the `.adm-convo` rules. No `max-height`,
  no `overflow`.
- House precedents for a bounded list inside a card (all `max-height` + `overflow-y:auto`):
  `.page-fiscal-notes .yscroll` **330px** (app.css:478; 178px compact variant at 483),
  `.pdf-cited-text` 220px (:1690), `.chat-cite-quote` 96px (:1220),
  `.adm-select-menu` min(60vh,420px) (:2752), `.chat-tool-group-expansion` 50vh (:1363).

## Design

Add to the existing `.adm-convo` rule (SKETCH — final form set at implementation):

```css
.adm-convo{ … existing … max-height:330px;overflow-y:auto;padding-right:2px;}
```

- **330px** matches `.yscroll`, the closest analog — a scrollable list of rows inside
  a card on a page with other content below it. It shows roughly 5–7 exchange lines,
  enough to read the shape of a conversation; the prompt's 320–420px band brackets it,
  and reusing the house number beats inventing a sixth one. `padding-right:2px` is
  `.yscroll`'s own scrollbar clearance, copied for the same reason.
- **No fade, no "N more lines" copy, no collapse/expand.** The stylesheet's per-edge
  mask-image fade (app.css:2560–2569) exists ONLY on the ask-bar textarea, and its own
  comment says why: that surface removed its scrollbar, so the fade replaced it as the
  affordance. Every plain bounded scroller in this stylesheet keeps the scrollbar and
  nothing else — the scrollbar IS the "there is more" signal. Adding a fade here would
  also mean `mask-image` on a scroller, the exact property class the AI-redesign
  tooltip-clipping guard (comment at app.css:~737) warns against.
- Short transcripts are unaffected: `max-height` only binds when content exceeds it.

## Exact files to change

1. `webapp/src/styles/app.css` — the `.adm-convo` rule (~line 2936). **The only change.**
2. Optionally `webapp/src/admin/IssuesPanel.test.tsx` (or wherever the panel's specs
   live) — pin the container contract (below). No `.tsx` component change.

## Test plan, with its honest limits

**jsdom applies no stylesheet, so no vitest spec can observe `max-height` taking
effect.** What CAN be pinned: the transcript renders as `data-testid=
"admin-issue-transcript"` with class `adm-convo` (the hook the CSS binds to), and a
long transcript still renders all its lines into the DOM (bounding is visual, not
truncation — no line is dropped). A stylesheet-source assertion (the `.adm-convo` rule
contains `max-height` and `overflow-y`) is the strongest honest guard available and
matches this repo's existing css-contract-test pattern; note it pins text, not paint.

**The rendering itself remains for Destin's browser pass:** open `/admin` → Issue
reports → expand a report with a long attached conversation → the card stays a bounded
height, the transcript scrolls inside itself with a visible scrollbar, and the page
does not grow with the transcript. Also glance at a report with a 2-line transcript
(no scrollbar, no wasted empty space).

## UX consequences, plain English

The admin's inbox stays skimmable: a report with a huge attached chat takes the same
space as any other report, and the chat scrolls in its own window. Cost: the admin now
scrolls twice (page, then transcript) to read a long chat end-to-end — the same trade
every other bounded panel here makes, and nested-scroll capture is mild at 330px.

## Risks / what NOT to do

- **Do not** touch the report form, issue storage (`app/issue_reports.py`), or routes
  (`app/routes/issues.py`) — this is a display containment fix only.
- **Do not** add a fade/mask, a collapse control, or any new copy (see Design).
- **Do not** truncate the data or the DOM — every line must remain reachable by scroll;
  an admin reads these to judge a report.
- Adjacent gap, noted not fixed: `.adm-sub` (description/expected) is also unbounded,
  and `app/routes/issues.py` applies NO length cap to either field (verified — only a
  non-empty check at :57–58), so a pasted wall of text can still make a tall card.
  Out of scope here; a follow-up would decide between a display bound and a server cap.
