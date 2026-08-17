# Whole-report links: a durable path for new book editions

**Date:** 2026-08-16
**Status:** Approved by Destin, not built
**Decisions:** R1–R13

---

## The problem, and the evidence

The Budget Documents page shows a **"Full report"** button on a report row when
it has a hand-verified URL for the whole book. On 2026-08-16 that list held
**three** editions, so the FY 2027 Appropriations Report rendered with no button
beside a Baseline that had one. It was filled out to **39 editions / 72 URLs**
the same day (see STATUS.md, *"Full report now covers every book edition in the
corpus"*).

**That fix does not prevent the next occurrence.** Nothing tells anybody a new
edition needs an entry, and adding one means editing
`webapp/src/reportFamilies.ts` and rebuilding the app. JLBC publishes roughly
two editions a year, forever, and **a non-developer successor cannot perform
that step at all** — which contradicts the project's stated goal of being
maintainable by whoever inherits it.

**The information already passes through the building.**
`ingest/book_discovery.py`'s `EditionPlan` carries `single_file_url` and
`linked_toc_url`; `plan_edition()` fills both, from the committed catalog on a
hit or from a HEAD-verified candidate ladder (`_TOC_LADDERS`,
`_SINGLE_LADDERS`) on a miss. That ladder is exactly how the FY 2027
Appropriations Report was discovered on 2026-07-31. Both URLs are then
**discarded** — nothing persists them, and the webapp's table is maintained by
hand and separately.

So this is not a missing lookup. It is a missing hand-off.

### Why a live URL is not sufficient evidence

A 200 response says an address resolves. It does not say the file is the
edition claimed, and both cheap sources fail in ways only a look exposes:

- **The vendored site index** files slideshows and single chapters under the
  bare report title. "FY 2021 Appropriations Report" is also
  `21H-Sfullappropspres.pdf`; "FY 2014 Appropriations Report" is also
  `14AR/384.pdf`.
- **The probe ladder's own last rung is year-less.** `_TOC_LADDERS["approps"]`
  ends at `https://www.azjlbc.gov/budget/apprpttoc.pdf`, a rolling address JLBC
  republishes each cycle. Verified 2026-08-16: it currently serves the **FY
  2023** table of contents. Probing FY 2028 before `28ar/` exists would return
  a live, plausible, wrong-year link. `_apply_rolling_guard` already defends the
  *chapters* against this; the whole-report link is not covered.

Hence a human approval step, and hence the year check in R6.

---

## Decisions

### R1 — One owner for the link table, and it is not the webapp

Two files, one schema, merged server-side:

| File | Committed? | Holds |
|---|---|---|
| `data/report-formats.json` | yes, ships in the bundle | the 39 verified editions as of 2026-08-16 |
| `<data_dir>/report-formats.json` | no, lives on the share | the admin's approvals |

```json
{
  "version": 1,
  "editions": {
    "Baseline:2027": {
      "single_file": "https://www.azjlbc.gov/budget/27baselinesinglefile.pdf",
      "linked_toc":  "https://www.azjlbc.gov/budget/27baselinelinks.pdf"
    },
    "Appropriations Report:2005": {
      "single_file": null,
      "linked_toc":  "https://www.azjlbc.gov/05app/apprpttoc.pdf"
    }
  }
}
```

**`null` means "JLBC published no such format"; an absent edition key means
"nobody has answered for this edition yet".** These are different states and the
UI treats them differently — the first is settled, the second is pending. The
distinction already exists in today's table (Approps FY2005–FY2010 carry a null
single file) and must survive the move.

**An overlay entry replaces its baseline entry wholesale**, not field by field.
The unit the admin acts on is an edition, and a field-level merge creates states
nobody chose (half this year's answer, half last year's).

`webapp/src/reportFamilies.ts` keeps `familyOf` / `slugsForFamily` /
`familyTitle` and **loses its URL table entirely**. It becomes a consumer.

> **WHY the move, stated plainly because it is the costliest part of this
> change.** Adding an approval overlay while leaving the shipped table in
> TypeScript would give two files the same job in two languages, with the merge
> living in one of them. This repo's history records that shape producing silent
> drift at least four times (`_DOC_TYPES` vs the registry, `Upload.tsx`'s
> publisher map, three drifted `documents.json` readers, two "is the queue
> stalled?" implementations). Paying it once now is cheaper than discovering it
> in a year.

### R2 — Family names come from `store/book_family.py`, verbatim

The two strings are `"Baseline"` and `"Appropriations Report"`. `section_of()`
already returns them and `webapp/src/reportFamilies.ts::familyOf` already
displays them. A typo'd family produces a button that never appears, which is
indistinguishable from an uncurated year, so it must never pass silently — but
the two files fail differently on purpose:

- **the committed `data/report-formats.json`** is held to it by a test, so a bad
  family cannot be committed at all (R11);
- **the overlay on the share** drops the bad row and records a reason the admin
  panel shows, because a hand-edited file on a network drive must not be able to
  take the page down.

### R3 — Detection is a SCAN of the corpus, not a hook on ingest

The pending list is computed as:

> every `(family, fiscal_year)` pair in the corpus whose family is a book
> family, minus every edition key present in the merged table.

**Not an ingest hook**, deliberately. A scan also catches editions added by a
bulk backfill, added on a machine nobody opened the app on, and added before
this feature existed. A hook catches only books that arrived the one expected
way, and the FY 2027 gap is proof that books arrive other ways.

The corpus side of that pair is derived exactly as the browse page derives it —
`section_of(doc_type, source_url)` first, `doc_type` second — so the pending
list and the page can never disagree about what an edition is.

### R4 — Candidate URLs come from `ingest/book_discovery.plan_edition`

No second probe ladder. `plan_edition` is called read-only; nothing under
`ingest/` is modified.

### R5 — Probing is cached 12 hours and degrades honestly offline

**The scan itself is per-request and free** — it reads `documents.json` and the
merged table, both already cached, and touches no network. Only the candidate
URL lookup for a *pending* edition probes, and that answer is cached at
`<data_dir>/book-format-probe.json`, mirroring `app/routes/books_missing.py`
(`CACHE_TTL_SECONDS`, `online: false`, last-good answer, plain-English reason).

So a fully-answered corpus — the normal state — costs zero requests, and the
probe only runs on the rare occasion something is genuinely pending.

This app is verified to cold-start with WiFi disconnected; a panel that renders
"nothing to add" because the network is down is a confident wrong answer.

### R6 — A candidate URL that does not name its own fiscal year is FLAGGED, not refused

JLBC's filenames carry the year (`19AR/FY2019AppropRpt.pdf`,
`26baseline/26baselinesinglefile.pdf`). A candidate whose path contains neither
the two-digit nor the four-digit year is shown with a warning next to it —
*"this address doesn't mention FY 2028; open it before approving"* — because
that is the exact shape the rolling `/budget/` rung produces.

**Flagged, not blocked**, and the same rule applies to a URL the admin types:
one legitimate case already exists (`budget/apprpttoc.pdf` is genuinely FY2023's
contents), so a hard block would make a real edition unapprovable. The shipped
`data/report-formats.json` is held to the stricter rule in R11.

### R7 — Nothing reaches the analyst until it is approved

An unanswered edition renders with no "Full report" control, which is exactly
today's behaviour for an uncurated year. There is no provisional or
auto-published state.

### R8 — Three outcomes per format, one Approve per edition

Per format: **keep the candidate**, **use a different link** (paste a URL), or
**none published** (writes `null`). Then one **Approve** for the edition, which
writes the whole key. **Not now** writes nothing and the card returns next time.

An edition where both formats are marked "none published" is refused: that is
indistinguishable from having no entry, so it would silently re-appear as
pending forever.

### R9 — The card shows the address, the file size, and whether it responded

**Not the page count.** Size comes from the same `HEAD` the candidate check
already performs; a page count requires downloading the file, which is up to
50 MB per format on an admin page load.

Each format gets an **"Open to check ↗"** link that opens the real PDF in a new
tab. That is the evidence — the file itself, not a rendering of it.

> **Accepted risk, recorded because it was raised and chosen anyway.** Nothing
> forces the admin to open either link before approving, so a wrong link can be
> approved by an admin who does not look. The mitigations are the R6 year
> warning and the size (a 0.2 MB "book" or a 47 MB "table of contents" is
> visibly wrong). Alternatives offering stronger evidence — a rendered cover
> image, or the first line of extracted text — were presented and declined in
> favour of the simplest card.

### R10 — Writes are admin-gated, atomic, and loud on failure

`require_admin`, tmp + `os.replace`, and a failed save **raises** so it reaches
the admin's screen. Read paths degrade to the committed baseline on a bad or
unreachable overlay; the write path does not degrade. This mirrors
`store/office_aliases.py`, which exists for the same reason and was reviewed
into this posture.

### R11 — The guards move to Python with the data

The four checks added to `webapp/src/reportFamilies.test.ts` on 2026-08-16 move
to pytest against `data/report-formats.json`:

1. every key is a known family and a four-digit year;
2. **every URL names its own fiscal year** — the load-bearing one, because
   copying a row and forgetting to change the URL yields a live, downloadable,
   *wrong* report behind the button, which no reachability check can detect.
   One documented exemption: `https://www.azjlbc.gov/budget/apprpttoc.pdf`;
3. every URL is an `https://www.azjlbc.gov/….pdf`;
4. every edition offers at least one format.

Checks 1, 2 and 4 also run against the **overlay** at load time, as tolerant
validation: a bad row is dropped with a reason rather than 500-ing the page.
Check 3 does not — an admin correcting a link may legitimately reach another
host.

### R12 — `scripts/verify_report_formats.py` reads the merged table

It currently regex-parses the TypeScript file. It reads
`store.report_formats.load()` instead, which also makes it check the admin's
approvals rather than only the shipped set.

### R13 — Non-goals

- **Watching approved links for later breakage.** Left to R12's script, run on
  demand. An automatic checker would have to tell "JLBC removed this file" from
  "this machine has no internet", and the office is deliberately offline-capable;
  a panel that cries wolf is one nobody reads.
- **Publishers other than JLBC.** The AFR, Executive Budget and Budget Bill are
  single-document reports and already get their link from the existing
  lone-document fallback in `Search.tsx::resolveFullReportAction`. Unchanged.
- **Fiscal notes.** Different corpus, different surface.
- **Repairing the 21 mis-minted book doc_ids.** Out of scope here as everywhere
  else; family is read from `source_url`, never from the doc_id.

---

## Surfaces

| Endpoint | Gate | Purpose |
|---|---|---|
| `GET /api/admin/book-formats` | admin | `{approved, pending, online, error}` — the panel's whole state |
| `PUT /api/admin/book-formats` | admin | write one edition; body `{family, fiscal_year, single_file, linked_toc}`, each URL a string or `null` |
| `POST /api/admin/book-formats/check` | admin | body `{url}` → `{ok, status, bytes, names_its_year}` for the "use a different link" field |
| `GET /api/corpus/documents` | none | gains a `report_formats` key carrying the merged table |

The edition is named in the PUT **body, not the path**: one family is
`"Appropriations Report"`, and putting a string with a space and a
percent-encoding requirement into a URL path is a decoding bug waiting to
happen on a route whose whole job is writing a permanent record.

Folding the public read into the corpus response rather than adding a second
public endpoint: the browse page already fetches that document list and needs
both together, so a separate call would let documents render a frame before
their buttons.

| Module | Role |
|---|---|
| `store/report_formats.py` | load, merge, validate, save. mtime-stamped cache, same shape as `store/office_aliases.py` |
| `app/routes/book_formats.py` | the pending scan, the probe cache, the two admin routes |
| `webapp/src/pages/upload/ReportLinkRow.tsx` | the "Full report link" row inside the Baseline Book and Appropriations Report cards on `/upload`, admin-only. World-changed 2026-08-16: this moved out of `/admin` (the `webapp/src/admin/ReportLinksPanel.tsx` card is deleted), because JLBC publishes FY2028 in one sitting with adding documents — two pages for one event was the half you forgot. See STATUS.md "The R7 deviation is RESOLVED — the whole thing moved to `/upload`" |
| `webapp/src/reportFamilies.ts` | loses `REPORT_FORMATS`; `reportFormats()` becomes a lookup into API-supplied data |

---

## Testing and gates

`pytest`, `vitest`, `tsc -b`, `npm run build`. **No eval run**: nothing under
`retrieval/`, `chunking/`, `citation/` or `harness/system-prompt.md` is touched,
and `ingest/book_discovery.py` is imported read-only, not modified.

Guards that must exist, each verified failing before it is trusted:

- the R6 year warning fires on `budget/apprpttoc.pdf` probed for a later year;
- an unapproved edition renders **no** button on the browse page;
- an edition marked `null` / URL renders a **direct link**, not the chooser;
- a corrupt or absent overlay leaves the committed baseline intact and serving;
- a failed save reaches the caller rather than being swallowed;
- `PUT` refuses an edition with both formats `null`.

### Acceptance — the panel is EMPTY on day one, and that must not be mistaken for working

All 39 editions in the corpus are already answered, so a healthy install shows
**nothing**, which is also what a completely broken feature shows. Acceptance
therefore requires, in a scratch data dir symlinking the corpus read-only:

1. remove one edition from the merged table, reload the book card on `/upload`
   (admin session), and confirm the "Full report link" row appears with that
   edition's real candidate URLs;
2. press **Approve**, and confirm the button appears on the Budget Documents
   page for that edition and opens the chooser at the right two files;
3. use **"use a different link"** with a deliberately wrong-year URL and confirm
   the R6 warning renders;
4. mark one format **none published** and confirm the row becomes a direct link
   with no chooser;
5. disconnect the network and confirm the panel says it could not reach
   azjlbc.gov rather than reporting nothing to add.

Steps 1–4 are the reason this spec exists; step 5 is the one that has been got
wrong elsewhere in this app.

---

## Risks

| Risk | Standing |
|---|---|
| An admin approves without opening either link | Accepted (R9). Mitigated by the year warning and the size. |
| The rolling `/budget/` rung offers a prior year's TOC | Detected by R6's warning, which is the specific defence against it. |
| The overlay file is hand-edited on the share and malformed | Tolerant load (R11) drops bad rows with a reason; the committed baseline keeps serving. |
| Moving the table breaks the browse page's button | Covered by the existing `Search.test.tsx` suite, which asserts button/chooser/no-button per family and is not being rewritten — only its data source changes. |
| Two machines approve different links at once | Last write wins. Acceptable: the value is one URL chosen from a two-item list, and the loser re-appears as approved-with-the-other-URL, visible on the same panel. |
