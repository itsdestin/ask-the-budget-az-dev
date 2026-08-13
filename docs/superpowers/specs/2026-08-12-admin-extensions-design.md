# Admin extensions — aliases, office guidance, issue reports

**Date:** 2026-08-12
**Status:** Approved design (brainstormed with Destin)
**Scope:** Three admin-surface features (E1–E3) plus one recorded future
direction (E4). Implementation plan to follow.

## Why

Three needs surfaced from office use:

1. The office's own acronyms ("DOR", "ADE") should improve Budget Documents
   filtering and retrieval agency-linking without a developer editing
   `samples/entity-catalog.yaml` and re-shipping.
2. The AI Mode agent's domain guidance should be tunable over time by the
   administrator — the same kind of "this doc beats that doc for X
   questions" prose the shipped prompt already carries.
3. Analysts need a way to report problems that doesn't vanish into a void,
   and the admin needs one place to see them.

A fourth wish — an admin "repair agent" that uses the configured API key to
fix the app or data when things go haywire — is deliberately deferred and
recorded as a future direction only (E4).

## Ground truth this design is built on

- The approved aliases live in `samples/entity-catalog.yaml`, a **committed
  repo file** the office bundle ships read-only. Admin editing therefore
  requires an overlay on the shared data dir, never edits to the catalog.
- Five safety stoplists in `retrieval/query_agency.py`
  (`SUPPRESSED_ALIASES`, `AMBIGUOUS_ALIASES`, `AMBIGUOUS_PHRASES`,
  `AMBIGUOUS_AGENCIES`, `CURATED_ALIAS_AGENCIES`) exist because bad aliases
  caused real shipped defects (`for` → Forestry hard-filtered 14 of 47 eval
  queries). They stay in code, unexposed.
- `harness/system-prompt.md` is a 1,213-line template with hand-rolled
  `{{#when}}`/`{{NAME}}` syntax, coupled constants, and an S22
  prompt-caching requirement that the rendered prompt be a pure function of
  (corpus, tier) within a conversation. Free-form editing of it is out.
- Doc-preference knowledge ("AFR > approps Actual column, always") is
  conveyed today as **prose in the prompt**, so an admin-authored prose
  block is the native extension mechanism.
- The data dir already holds shared per-office JSON with an established
  pattern (`notices.json`, `fiscal-notes-directory.json`, `jobs/`):
  mtime-checked read cache, tmp+`os.replace` atomic writes,
  degrade-on-corrupt reads, raise-on-write-failure.
- `retrieval/` and `app/search_terms.py` must not import `harness/`
  (settings) — a layering line this design keeps.

## Decisions

| # | Decision |
|---|---|
| E1 | Alias management: admin adds/removes acronym → agency mappings and may disable shipped aliases. **Admin aliases resolve at WEAK confidence only** (ranking preference, never a hard filter). Stoplists and per-alias strength are not exposed. |
| E2 | Prompt tuning: **additions block only.** The shipped prompt stays fixed; the admin writes an "Office guidance" markdown block injected into a designated `{{OFFICE_GUIDANCE}}` slot with a fixed conflicts-lose preamble. |
| E3 | Issue reports: lightweight lifecycle — every report is `unresolved` until the admin flips it to `resolved`, with an optional admin note. Analysts see their own reports and statuses. Transcript attachment is opt-in per report. |
| E4 | Admin repair agent: **future direction only.** Recorded, not designed. |
| E5 | Storage: purpose-built files per concern on the shared data dir — `office-aliases.json`, `office-guidance.md`, `issue-reports/` — following the existing shared-JSON pattern. Not `settings.json` (wrong edit rhythm, and it would force `retrieval/` to import `harness/`), not a generic office-config store (YAGNI). |
| E6 | Surface: everything lives on the single `/admin` page, reorganized into function groups of collapsible sections. Analyst-facing pieces (report form, own-report list) get a "Report an issue" entry in the top-right tools menu, visible to everyone. |

## E1 — Alias management ("Search language")

**Data — `<data_dir>/office-aliases.json`:**

```json
{
  "added": [
    {"alias": "dor", "canonical_id": "agency:rev",
     "added_by": "djones", "added_at": "2026-08-12T17:00:00Z"}
  ],
  "disabled": ["colleges"]
}
```

- `added`: admin's alias → agency mappings, with who/when for audit.
- `disabled`: shipped-alias strings the admin switched off (escape hatch
  for a shipped alias that misfires for this office).
- Nothing else. No strength field — strength is not admin-choosable.

**Merge points (two consumers, one overlay reader):**

- `retrieval/query_agency.py`: the resolution ladder gains one overlay
  step. Admin aliases resolve at **`Confidence.WEAK` only** — the same
  penalty/preference posture the shipped ranking takes, so a bad alias can
  cost ranking but can never silently delete the right answer. Disabled
  shipped aliases are removed from the alias tier before resolution.
- `app/search_terms.py` (Budget Documents filter box) reads the same
  overlay so typed acronyms work there too.
- The committed catalog and `tests/test_query_agency.py`'s pinning test are
  untouched: that test pins the *committed* set; the overlay is a separate,
  separately-tested layer.

**Validation on save (server-side, plain-English rejection reasons):**

- Reject an alias present in `SUPPRESSED_ALIASES` or `AMBIGUOUS_ALIASES`
  (known-toxic words, with measurements behind them).
- Reject an alias that collides with a *different* agency's existing name,
  slug, or alias.
- Reject an unknown `canonical_id`.
- Warn-but-allow on aliases of ≤2 characters.

**UI — "Search language" section (Search & documents group):** table of
admin aliases (alias, agency, added-by, date, remove), an add row with a
searchable agency picker over the 157-agency catalog, and a collapsed
sub-list of the ~10 shipped aliases with disable toggles. Copy states the
honest limitation: aliases apply to *queries* immediately; documents
already in the corpus were stamped without them, so this improves typed
searches, not the corpus-side stamping gap (known re-ingest follow-up,
out of scope).

## E2 — Office guidance (prompt additions)

**Data — `<data_dir>/office-guidance.md`:** plain markdown, size-capped at
8 KB (~2,000 tokens) so a runaway paste cannot silently inflate every
request's token bill. The UI shows a size meter. Every save preserves the
previous version as `office-guidance.md.bak` — one-step undo.

**Injection:** `harness/system-prompt.md` gains one `{{OFFICE_GUIDANCE}}`
slot in the domain-guidance region (near the doc-type routing table and
accuracy hierarchy — the kind of content the block will hold).
`harness/prompt.py` substitutes the file's contents wrapped in a fixed
preamble:

> The office administrator added the guidance below. It supplements the
> rules above; where it conflicts with citation, refusal, or tool rules,
> those rules win.

Empty or missing file → the slot renders to nothing, byte-identical to
today's prompt.

**Prompt-cache safety:** the existing per-session memoization
(`harness/session.py::_system_prompt_text`) already snapshots the prompt
at conversation start, so an admin edit never changes a live
conversation's cache prefix (the S22 purity requirement holds with no new
mechanism). Edits take effect on new conversations, and the UI says so.

**UI — "AI guidance" section (AI Mode group):** textarea with
save/discard, last-edited-by/when line, and two pieces of copy: "Changes
apply to new conversations" and "This text shapes AI answers for the
whole office. After editing, ask a few test questions to check the
effect." (These edits bypass the eval harness; the honest mitigation is a
spot-check instruction, not a pretend gate.)

## E3 — Issue reports

**Data — `<data_dir>/issue-reports/<id>.json`,** one file per report (the
`jobs/` pattern; the directory is the index, no shared index file to
corrupt):

```json
{
  "id": "...", "version": 1,
  "submitted_by": "asmith", "submitted_at": "...",
  "page": "/search", "app_version": "...",
  "description": "...", "expected": "...",
  "status": "unresolved",
  "admin_note": null, "resolved_by": null, "resolved_at": null,
  "transcript": null
}
```

**Transcript attach:** offered only when filing from the AI Mode page with
an open conversation. Unchecked-by-default checkbox: *"Attach this
conversation — the administrator will be able to read everything in it."*
On submit, the analyst's own server process reads that conversation's
local transcript and embeds it in the report JSON. The local transcript
becomes share-readable only by this explicit act — Invariant 7's spirit
holds because the analyst is the one publishing it.

**API:**

- `POST /api/issues` — any user (the analyst's door).
- `GET /api/issues` — admin sees all; a non-admin caller gets only their
  own reports, filtered server-side by username.
- `PATCH /api/issues/{id}` — admin only: flip status, set the note.

Writes are tmp+replace; a corrupt report file renders as a visible
"unreadable report" row, never a blanked list.

**Analyst UI:** "Report an issue" in the top-right tools menu, visible to
everyone. The page holds the form (what happened / what you expected;
the auto-captured context shown *to* the analyst so nothing is collected
invisibly; the transcript checkbox when applicable) and, below it, their
own past reports with status — a report visibly exists after submission
and visibly flips to resolved, with the admin's note when present.

**Admin UI:** "Issue reports" section in the Needs-attention group, header
badged with the unresolved count. List sorted unresolved-first then
newest; each row expands to the full report (transcript viewer when
attached), a resolve toggle, and the optional note. The existing
"Needs a look" notices panel is not involved — reports are their own
channel, not system notices.

## The reorganized `/admin` page

Function groups, each a heading with collapsible sections (existing
`Card`/`CollapsibleCard` primitives; unopened sections stay collapsed so
the page reads as a table of contents):

1. **Needs attention** — Notices (as today) + Issue reports (new).
2. **AI Mode** — provider/key/tiers/limits (today's ProviderPanel) +
   Office guidance (new).
3. **Search & documents** — corpus health/backups (today's CorpusPanel) +
   Search language (new).
4. **Spending** — today's CostsPanel.
5. **Access & files** — today's AdvancedPanel.

The SaveBar keeps governing settings drafts only. The three new features
save independently — each is its own file with its own save action — so an
alias edit never rides along with a half-finished settings draft.

## Error handling (uniform posture)

- Every new file **read** degrades: missing → empty; corrupt aliases or
  guidance → empty with the corrupt/`.bak` copy preserved; corrupt report
  → visible unreadable row.
- Every **write** raises loudly to the UI.
- A share outage mid-session surfaces as the request's error, never a
  silent fallback.

## Testing

- **Mechanism in pytest:** overlay merge; WEAK-only confidence; disabled
  shipped aliases; every validation rejection; the template slot empty
  and filled; the byte-identical-when-absent property; report CRUD;
  non-admin filtering; transcript embed. All against fake files — nothing
  opens a real LanceDB or loads ONNX weights.
- **Guard test** in the spirit of `test_query_understanding_eval_safety.py`:
  **no overlay alias may ever resolve at EXACT/hard-filter confidence** —
  pinned structurally, not per-instance.
- **Vitest:** report form, own-report list, admin inbox, new admin
  sections, tools-menu entry.
- **Eval:** the overlay touches `retrieval/`, so the eval runs once on the
  branch with a representative overlay fixture loaded, proving an admin
  alias cannot move ground-truth queries. Results committed per the
  CLAUDE.md rule.

## E4 — Future direction: admin repair agent (not designed here)

Recorded intent: when things go seriously wrong, the admin could use the
already-configured OpenRouter key to run a maintenance agent against the
app or data structure. Preconditions any future design must carry: its
own visible spend accounting, hard confirmation gates on any write to the
corpus or settings, and a design pass of its own. Nothing in E1–E3 blocks
or prejudges it.

## Out of scope

- Corpus-side agency stamping (the 103-agencies-without-aliases ingest
  gap) — separate re-ingest decision.
- Editing stoplists, per-alias strength, or the shipped prompt body.
- Issue-report threads, categories, priorities, assignment.
- Any automated action on report contents (Invariant 4).
