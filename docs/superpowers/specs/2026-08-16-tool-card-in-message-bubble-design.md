# Tool card in the message bubble — design

**Date:** 2026-08-16
**Rendered options this was approved from:**
[`assets/2026-08-16-tool-card-mockup/options.html`](assets/2026-08-16-tool-card-mockup/options.html)
— a static page built with the app's real tokens, spacing and row geometry,
showing today's layout, the three containment options, and the edge cases.
Committed because the decision below is a *visual* one and the prose
description of it is not sufficient evidence of what was agreed.
**Scope:** `webapp/` only — the AI Mode chat renderer. Nothing under
`retrieval/`, `ingest/`, `chunking/`, `citation/` or
`harness/system-prompt.md` is touched, so the CLAUDE.md eval rule does not
apply and no eval run is required. See Gates.

---

## The problem

An assistant turn is a flat, arrival-ordered list of blocks —
`AssistantBlock` in `webapp/src/chat/chat-types.ts:16` — alternating prose
and tool calls as the model produces them. `AssistantTurnBubble.tsx:163-172`
walks that list and renders each piece where it falls: every text block
becomes its own `.chat-bubble`, every run of consecutive tool calls becomes a
`.chat-tool` or `.chat-tool-group` **sibling** sitting between the bubbles.

Two consequences the analyst sees:

1. **Tool rows are separate cards floating above the answer**, competing with
   it for the eye rather than annotating it.
2. **Grouping only fires on adjacent calls.** The segmentation loop starts a
   new segment at every text block, so a turn that searches, writes a
   sentence, then searches again produces two independent single-call rows —
   the "searched, searched" stack. Today's `ToolGroup` cannot reach it.

## The change in one sentence

A run of tool calls stops being a sibling of the answer and becomes the first
child **inside** the bubble that follows it, rendered as one self-contained
collapsible card.

---

## Decisions

### TC1 — A tool run attaches DOWNWARD, to the bubble that follows it

Not upward, and **not hoisted to the top of the turn**. The card sits above
the prose it produced, so reading order is preserved: an answer that searched,
wrote a paragraph, searched again and wrote more renders as two bubbles, each
wearing its own card.

Rejected: collecting every tool call in the turn into one card at the very
top. It reads tidier on a single-round answer and lies on a multi-round one —
the second round's searches would appear to have happened before the first
round's prose.

### TC2 — Containment is a card in the bubble's padding, not a header bar

The bubble keeps its existing `padding: 10px 16px` and its radius. The tool
card renders as the first element inside that padding: its own 1px border,
its own `--r-sm` corners, `--canvas` fill (the existing `.chat-tool.is-inset`
treatment), with white gutter on all four sides and a 10px gap below it before
the prose starts.

It must read as an object **in** the message, never as a title bar **on** it.
Explicitly rejected: a flush strip taking the bubble's top corners and
spanning edge to edge. Also rejected: a tinted band across the bubble top with
the card floating inside it — expanded, that stacks three surface tones (grey
band, white card, grey child rows) and reads busy.

Approved from a rendered comparison of all three, 2026-08-16.

### TC3 — Header wording is past tense, coalesced, with no corpus name

| run | label | detail line (`↳`) |
|---|---|---|
| one search, settled | `Searched` | the query (today's per-tool summary) |
| two searches, settled | `Searched ×2` | *(none)* |
| searches + a document | `Searched ×3, wrote a document` | *(none)* |
| any call still running | `Searching ×2` | `1 of 2 done` |

The corpus name is deliberately absent. It is fixed for the whole
conversation and already stated by the corpus picker and the composer
placeholder; repeating it on every answer restates what the interface shows.

**A settled multi-call run carries no detail line at all.** Today it reads
`all complete`. That has to go with the failure signalling in TC9: a card that
says `all complete` while suppressing `1 failed` would be making a false
positive claim, which is worse than the noise it was meant to remove. Silence
claims nothing. Progress while running is kept, because that is information
the analyst is actively waiting on.

A past-tense label map is added beside the existing present-tense one in
`tool-display.ts`. The existing `toolDisplayLabel` ("Search corpus", "Write
document") stays as-is — it still names the child rows inside the expansion,
where present-tense-imperative is the right register for "here is the call
that was made".

### TC4 — Tense follows the run's state

While **any** call in the run is still running, the label uses the present
participle (`Searching`, `Searching ×2`). Once every call has settled it
becomes past tense. "Searched" over a call still in flight is a false
statement about a live process, and this app's whole posture is that the
interface does not overclaim.

### TC5 — A run of one renders the same card, and expands in one click

Today a lone call renders a bare `ToolCard` and expanding it shows that call's
detail immediately. That must not become two clicks.

So: the card component renders for runs of any size (n ≥ 1), but its expanded
content differs.

- **n = 1** — expanding shows that call's `ToolBody` directly. The header
  carries the single call's own summary (the query), so nothing today's row
  showed is lost.
- **n ≥ 2** — expanding shows one inset `ToolCard` row per call, each
  independently expandable, exactly as `ToolGroup` does now.

### TC6 — A run with no bubble after it renders standalone

Two situations produce this and both must stay visible:

- **Mid-turn, before the answer starts arriving.** During a search no text
  block exists yet, so there is nothing to nest inside. The card renders on
  its own — which is what preserves the live "it is working" feedback the
  analyst has today.
- **A turn that ends on a tool call** — the model exhausting its step budget,
  or a final call that failed.

Consequence, accepted: when the answer begins streaming, the standalone card
is absorbed into the bubble that forms beneath it. That is a small one-time
settle. The alternative — withholding the card until prose exists — would
leave the analyst watching a blank screen through a multi-second search, which
is worse.

### TC7 — Cite tools stay invisible and still do not break a run

Unchanged from `AssistantTurnBubble.tsx:54-58` and the ruling recorded above
it. `cite` / `cite_batch` blocks are skipped rather than treated as segment
boundaries, so `retrieve, cite, retrieve` remains one run of two searches. The
chips are those tools' user-visible surface.

### TC8 — The expanded area is capped and scrolls

The expanded body has no height limit today. Nested inside an answer bubble, a
search that returned 15 passages would push the prose far down the page — the
analyst opens a card to check a source and loses the answer they were reading.

The card's expanded region as a whole — the child-row list for n ≥ 2, or the
single tool body for n = 1 — is capped at `max-height: 50vh` with
`overflow-y: auto`. The cap sits on the card's expansion container, not on
each child, so opening several child rows inside one card still cannot exceed
it. The collapsed card is one row, unchanged.

### TC9 — The collapsed card carries NO failure signal

**A failed tool call no longer reddens the card, and no longer reports itself
in the collapsed row.** No red border, no red label or glyph, no `N failed`
detail line, no count.

The reasoning is that the signal is not actionable and not, on its own, bad
news. The model retries a failed call itself, so a red row usually marks a
transient step in work that then succeeded. There is nothing the analyst can
do with it, and alarming them about a self-correcting event costs trust in
every other warning the app raises.

**Demoted, not deleted.** The failure remains fully visible inside the
expansion: the individual call keeps its `.chat-tool.is-failed` treatment and
its error body, exactly as now. The audit trail is intact for anyone who opens
the card; it simply stops shouting at people who did not ask.

**What this deliberately does NOT touch.** Citation failure is a different
mechanism and stays loud. `cite` / `cite_batch` never render as tool rows at
all (TC7) — a failed citation surfaces as a struck-through red-X chip with the
server's reason in its tooltip. Core Invariant 2 lives there and is unaffected
by anything in this design. Likewise a whole-turn failure still surfaces
through the chat error state and `SystemHealthBanner`, which are the right
places for "the thing you asked for did not happen".

**Consequence for the CSS.** `.chat-tool-group.is-failed` and the
child-combinator rule at `app.css:1294` are deleted rather than moved. That
rule existed because as a descendant selector it reddened the labels of
successful children inside an expanded group; with no group-level tint at all,
the defect it guarded against is structurally impossible. Its contract test is
re-pointed at the stronger property — the card's header never carries a
failure tint under any state — rather than deleted.

### TC9a — Accepted risk, stated plainly

A search that fails and is **not** retried leaves the model answering on less
evidence than it should have, and the collapsed card will look ordinary. Two
things already cover that and neither depends on a red row: an answer the
model cannot ground is refused rather than fabricated (Core Invariant 3), and
every figure in an answer is either linked to a source chunk or visibly
uncited. The card was never the mechanism for catching a thin answer, and the
expansion still records exactly what happened.

### TC10 — Nested, the card fills the bubble's content box

`.chat-tool` currently carries `max-width: 65ch` so a standalone row can never
be wider than the prose it supports. Inside a bubble that constraint is
already satisfied by the parent, so the nested card is `width: 100%` of the
bubble's content box. The standalone form keeps its `max-width`.

### TC11 — Citation rendering is untouched

The card is inserted before `CitedMarkdownContent` inside the same bubble
element. Chip numbering, `blockData` inline-tag extraction, the figure
annotation and its character offsets all index the answer **text**, not the
DOM, so none of them can be disturbed by a sibling element appearing above the
markdown. The implementation must nonetheless verify this rather than assume
it.

### TC12 — Accessibility parity

The card's header stays a `<button>` with `aria-expanded`. Its `aria-label`
carries the coalesced breakdown as `ToolGroup.tsx:58` does now, and for n = 1
also carries the call's summary — so a screen-reader user gets the query,
which is the single most useful thing on the row.

**The aria-label tracks the visible text exactly**, which under TC3 and TC9
means it carries the progress detail while running and nothing after, and
never the word "failed". A screen-reader user must not be told about a
transient failure the sighted user is deliberately not being alarmed by — the
two surfaces have to agree, or the suppression is only cosmetic.

---

## Components

| File | Change |
|---|---|
| `webapp/src/chat/AssistantTurnBubble.tsx` | Segmentation changes from a flat list to pairs: each text segment carries the tool run that preceded it. A trailing run with no text renders standalone. |
| `webapp/src/chat/ToolGroup.tsx` | Renders for n ≥ 1; past/present-tense labels; n = 1 expands to `ToolBody` directly; accepts a `nested` flag for the in-bubble variant. |
| `webapp/src/chat/ToolCard.tsx` | Unchanged in behaviour — still the child row renderer and still what `ToolBody` hangs off. |
| `webapp/src/chat/tool-display.ts` | New past-tense / present-participle label map beside the existing one. |
| `webapp/src/styles/app.css` | Nested-card rules, the 50vh expansion cap, the width change. |

Boundaries stay where they are: `tool-display.ts` owns wording, `ToolGroup`
owns the run's shape and state, `ToolCard`/`ToolBody` own a single call,
`AssistantTurnBubble` owns pairing runs to bubbles. Nothing new crosses those
lines.

---

## Data flow

Unchanged upstream. `chat-reducer.ts` still appends blocks in arrival order;
nothing about the reducer, the SSE translation, or `history-rehydrate.ts`
moves. This is a rendering change over the same state, which is what keeps a
rehydrated past conversation rendering identically to a live one.

---

## Error handling

Every failure path already present still runs and still reaches the DOM: a
tool block flipped to `failed` by `TOOL_RESULT`, a still-running block failed
by `failOpenTools` on `TURN_ERROR` / `CONNECTION_LOST`, and the synthesized
`(unknown)` block for a result with no matching use. TC6 guarantees a run
always renders somewhere; TC9 changes only how loudly a failed member of that
run announces itself in the collapsed state, never whether it is recorded.

The one interaction worth naming: `failOpenTools` marks **every** open call
failed when the connection drops, so under TC9 a dropped connection no longer
paints the card red. That is correct rather than a loss — a dropped connection
is a whole-turn failure and belongs in the chat error state and
`SystemHealthBanner`, which is where it already goes and where the analyst can
actually act on it.

The `max_steps` notice and the stop-reason line stay **outside** every bubble,
unchanged — a system notice must not be mistakable for something the model
said.

---

## Testing

Mechanism in vitest; appearance by looking.

**Updated:** `assistant-turn-bubble.test.tsx:119` currently asserts a lone
call renders as a bare non-grouped card — that expectation inverts.
`tool-group.test.tsx` asserts the `1 failed` / `all complete` suffixes and the
failed-group tint; both expectations invert under TC3 and TC9.
`chat-css-contract.test.ts:435` pins the failed-group tint scope — re-pointed
at the stronger property that the card header never carries a failure tint in
any state, rather than deleted. Its other existing pins (24/8 turn rhythm, the
deleted `.chat-tool + .chat-tool` rule) must still pass unchanged.

**New:**
- a run of tool calls renders as a descendant of the following `.chat-bubble`,
  not as its sibling;
- a run with no following text renders standalone;
- a two-round turn produces two bubbles each carrying its own card, and no
  card at the top of the turn;
- n = 1 expands straight to the tool body — verified by mutation, since a
  two-click regression would otherwise pass every count-based assertion;
- tense flips with run state;
- the coalesced label and the aria-label agree;
- **a run containing a failed call renders a collapsed card indistinguishable
  from an all-successful one** — no tint class, no failure word in the visible
  text or the aria-label;
- **and that same failed call IS present once the card is expanded**, carrying
  its own failed treatment. Both halves are needed: the first alone is
  satisfied by dropping the call on the floor, which is the outcome TC9 is
  most at risk of drifting into.

**Not covered by any of it:** how it looks. jsdom applies no stylesheet, and
this repo has now shipped four UI defects green under thousands of passing
specs. A browser pass is a required gate, not a nicety — see below.

---

## Gates

1. `vitest`, `tsc -b`, `npm run build`, `pytest` — all clean.
2. **No eval run.** Nothing on the retrieval, ingest, chunking, citation or
   system-prompt path is touched.
3. **A browser pass on a running server**, checking: a single-search answer;
   a two-search answer; a two-round answer (card above each round's prose, no
   card hoisted to the top); expanding a search that returned many passages
   (the answer must remain reachable); a turn containing a failed call —
   confirming the collapsed card looks ordinary AND that the failure is there
   on expanding it; and the mid-search state before prose arrives, including
   the settle as the bubble forms.

⚠ `uvicorn` runs without `--reload`. This change is webapp-only, so a `npm run
build` is enough — but if anything Python-side is touched during
implementation, the server needs a restart.

---

## Out of scope

- The corpus name anywhere in the card (TC3).
- Any change to citation chips, the figure annotation, or the PDF panel.
- The `AiModePanel` corpus prop being threaded down to `ChatThread`; nothing
  in this design needs it.

> **⚠ AMENDED 2026-08-16.** "Any change to what a tool's expanded body shows"
> was out of scope and is now IN scope — see Part 2 below. The product owner
> opened the finished card, found the expanded body unreadable, and asked for
> it before merge. TC1–TC12 are unaffected.

---

# Part 2 — what the card SAYS (TC13–TC22)

Added 2026-08-16 after the product owner reviewed the built card. Part 1 moved
the card to the right place; this part makes its contents legible to a fiscal
analyst who does not know what a "chunk" is.

Approved from a rendered comparison:
[`assets/2026-08-16-tool-card-mockup/tool-cards-v2.html`](assets/2026-08-16-tool-card-mockup/tool-cards-v2.html).

## The audit that scoped this

Six tools are registered; **two never draw a card** — `cite` and `cite_batch`
are suppressed by TC7 because the citation chips are their surface. So four
reach an analyst:

| Tool | Icon today | Expanded body today |
|---|---|---|
| `retrieve` | hand-built magnifier that closes into a blob at 12px | scores, rank numbers, pipeline counters,every result printing its own heading twice |
| `list_filter_values` | three stacked bars — fine | works, but labelled `agency_canonical_id` and lists raw slugs with chunk counts |
| `create_document` | download tray | **genuinely fine** — title, download link, markdown preview |
| `document_guide` | **none — the fallback square** | **none — `RawFallbackView`, i.e. raw JSON** |

`document_guide` had never been styled at all. It runs immediately before the
assistant writes a document, so it appears in exactly the conversations that
end in a memo the analyst sends under their own name.

## Decisions

### TC13 — the collapsed card reads as a sentence

`Searched for "State Aviation Fund balance FY2025"`, not `Searched ↳ query`.
The verb stays **bold** so the row is still scannable down a long
conversation; the rest is normal weight. The row keeps its existing
single-line ellipsis truncation, so length is not a risk.

| case | header |
|---|---|
| one search | `Searched for “…”` |
| three searches | `Searched for “…” and 2 more` |
| in flight | `Searching for “…”…` |
| searches + a document | `Searched for “…” and 2 more, then wrote a document` |

**The first query stays visible at every run size.** The rejected alternative
led with the count (`Searched 3 times, starting with “…”`), which pushes the
one informative part toward the truncation.

TC3's rules survive unchanged underneath this: no corpus name, past tense once
settled and present participle while running (TC4), and **no failure signal**
(TC9) — a failed call changes no word of this header.

### TC14 — per-tool phrasing lives in `tool-display.ts`

Each tool needs its own preposition; the component must not assemble English.

| tool | phrase |
|---|---|
| `retrieve` | Searched for *“{query}”* |
| `list_filter_values` | Checked *which agencies the corpus covers* (per field) |
| `create_document` | Wrote the document *“{title}”* |
| `document_guide` | Checked the house style *for a research memo* |

An unregistered tool falls back to the bare name plus its first string
argument, as today — a legible degradation, not a blank row.

### TC15 — one line-drawn icon set, and `document_guide` gets one

The tool glyphs are currently pixel art on a 12×12 grid, matching the mascot.
**That is deliberately abandoned for these rows**, on this evidence: the
magnifier's ring closes into an illegible blob at rendered size, and the app
already owns a magnifier — `components/SearchIcon.tsx`, drawn from the
approved design mockup and used in four places on Home and Budget Documents.
The tool row was the only place in the app drawing a second one.

So: four icons, drawn in that same stroked style — magnifier, funnel, page,
book. `document_guide` gains the book and stops falling through to the square.
The mascot keeps its pixel art; this is chrome, and the rest of the app's
chrome is already lines.

### TC16 — search results group by DOCUMENT, not by passage

The unit becomes the document, which is how an analyst thinks about a source.
Each document shows its title, publisher, fiscal year, one snippet from its
strongest passage, and its pages as chips. Measured on the reported screenshot:
five near-identical rows become two blocks.

### TC17 — no scores, no rank numbers, no pipeline counters

`score 1.260` is a raw cross-encoder logit on roughly a −10..10 scale. It is
not a percentage and not a confidence, and rendering it beside a dollar figure
invites reading it as one. **Budget Documents already removed its relevance
number and bar for exactly this reason**; order carries the ranking. The
`N chunks · top score · (bm25 / dense / fused)` line goes with them.

### TC18 — strip the repeated heading out of the passage text

A passage's stored text begins with its own section heading, and the view also
renders that heading above it as a breadcrumb, so ~3 lines of every result are
the line above it repeated. Strip the prefix when it matches. The breadcrumb
itself reduces to the **leaf** heading; the full ancestor path is noise at this
size.

### TC19 — filters read as English

`DOC_TYPE: AFR` becomes *Annual Financial Reports*. The app already publishes
the mapping at `GET /api/document-types`, so this is wiring, not new data. A
value with no known label falls back to the raw string rather than vanishing.

### TC20 — `document_guide` gets a real view, and it must not overclaim

A plain sentence naming the report type, then the rules in readable form.

**It must state that the guidance is advice, not enforcement.** Nothing
validates the finished document against the guide (spec
`2026-08-13-document-guide-design.md` G6 — no code rewrites the model's
numbers, deliberately, because that would be editing figures the analyst is
about to send). A card that displayed house rules without saying so would
imply a check that does not exist.

### TC21 — `list_filter_values` shows names, not codes

`agency:ahcccs — 4,812 chunks` becomes `AHCCCS`. The field label becomes a
sentence (*which agencies the corpus covers*) rather than the column name.
Chunk counts are dropped from the analyst-facing list — they are a corpus
statistic, not an answer.

> ⚠ Known upstream defect, NOT fixed here: STATUS.md records that
> `list_filter_values` emits raw ids with no logical grouping, so duplicate
> catalog ids for one agency (Child Safety is 4 live ids) appear as separate
> agencies. Displaying names instead of codes makes that duplication **more**
> visible, not less — two rows both reading "Child Safety". That is a corpus
> fix with its own spec, and this work must not paper over it by silently
> de-duplicating names.

### TC22 — the card is the SAME WIDTH standalone and nested

Today it is not, and the jump is large. Measured on the shipped stylesheet:

- `.chat-bubble` sets `font-size: 14px` and `max-width: 65ch`, so its `ch`
  resolves at 14px, and a card nested inside it loses a further 32px of side
  padding plus 2px of border.
- `.chat-tool-group` standalone also says `max-width: 65ch`, but it inherits
  the document's 16px, so its `ch` is a **larger unit**.

The standalone card is therefore roughly 100px wider, and it visibly shrinks
the instant an answer arrives and it moves inside the bubble — on top of the
remount already recorded in Part 1. Both forms must state the same measure and
render at the same pixel width; the mechanism is the implementer's, but the
acceptance test is a browser measurement of the two, not a reading of the CSS.

## Out of scope for Part 2

- `create_document`'s expanded view, which is already good. It gets the new
  icon and the new header sentence and nothing else.
- The card's open-state reset when a standalone card becomes nested (Part 1's
  carried Minor). Still a separate decision.
- Grouping duplicate agency ids — see the warning under TC21.
- Any change to what `retrieve` returns. Every field these views show already
  arrives with the result.
