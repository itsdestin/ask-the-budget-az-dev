# Project Status

**Last updated:** 2026-08-23

This file is the single source of truth for what's shipped, what's
open, and what's blocked. The phase plans under `docs/superpowers/`
remain as the historical record of design intent — but those plans
have NOT been updated as features shipped, so use this file (not the
plans) to understand current state.

`CLAUDE.md` auto-imports this file via `@STATUS.md`, so every Claude
Code session sees the latest contents in context. **Do not duplicate
status info into CLAUDE.md** — every duplication is a future drift
source. When something ships, update only this file.

---

## Phase summary

| Phase | Status | Notes |
|---|---|---|
| Phase 0 — Investigation | ✓ Done (2026-05-06) | Findings memo + chunk-shape + data-model docs |
| Phase 1a — Ingest + chunking | ✓ Done on slice (2026-05-06), volume ingest substantially complete (2026-05-12) | 382 docs / 7,755 chunks; missing older FYs + a few in-cycle gaps |
| Phase 1b — Storage + retrieval | ✓ Done (slice 2026-05-07, volume-validated implicitly, WS8 eval harness shipped 2026-05-22) | Hybrid pipeline live and serving 7K+ chunks; eval harness baseline: recall@5 86%, recall@20 100% on 34-query set |
| Phase 1c — Synthesis + UI | ⬛ Superseded by Standalone consolidation (Plans 1–4) | The MCP/sidecar/Next.js stack it shipped is retired; faithfulness verifier (WS3) + audit log (WS5) remain unbuilt and carry forward |
| Volume ingest / S20 backfill | ✓ **Done (2026-08-02)** | Every ingestable JLBC book edition is in the corpus — 38 editions, 7 failures all azjlbc.gov 404s. Corpus 77,574 budget chunks / 7,434 documents. See Plan 7 Task 5 below |
| Phase 2 — Companion + verify-mode | 🔴 Not started | Defers until v1 demonstrates internal value |
| Standalone consolidation — Plan 1 (storage + retrieval) | ✓ Shipped (2026-07-30) | Postgres/pgvector/ParadeDB → embedded LanceDB; Voyage → local ONNX models. See the section below |
| Standalone consolidation — Plan 2 (app server + search UI) | ✓ Shipped (2026-07-30) | New `app/` (port 9300) + `webapp/` SPA: home, budget search (real corpus), fiscal notes directory. See the section below |
| Standalone consolidation — Plan 3 (ingest) | ✓ Shipped (2026-07-31) | GUI upload → background queue → LanceDB; fiscal-note refresh; Add-a-JLBC-book. Postgres/Docker now needed for NOTHING. See the section below |
| Standalone consolidation — Plan 4 (AI Mode) | ✓ Shipped (2026-07-31) | In-process OpenRouter tool loop; MCP and YouCoded dropped. Cited chat + PDF viewer on both corpora, Standard/Deep-Research tiers, per-user spend ledger. See the section below |
| Standalone consolidation — Plan 5 (admin + packaging + deletion) | 🟡 **Tracks 1–4 done, 5–6 open** (2026-08-01) | 20 of 27 tasks. Tracks 1–2 (1–13, Session A): admin identity + gate, settings API, OpenRouter catalog, model fallback, corpus health/restore, Admin + Settings pages, per-machine data dir, health ladder, lockout recovery. Track 3 (14–17, Session B): the Windows bundle. **Track 4 (18–20) shipped 2026-08-01** — `web/`, `mcp-server/`, `db/` and the dead `retrieval/` modules are DELETED (~36,000 lines), one `documents.json` reader, four ingest defects fixed, and all three of Session B's orphaned app-side asks built. **Track 5 (handbook, 21–23) and Track 6 (gates, 24–27) remain.** See the Track 4 section below |
| Standalone consolidation — Plan 6 (document types) | ⬛ **Superseded 2026-08-11** by the document-types re-scope | Plan 6's scope was replaced by a new spec (T1–T14) split into Plans A/B/C (see the rows below). **Plan A shipped 2026-08-11**, **Plan B shipped 2026-08-13**, **Plan C merged `ed59c29` 2026-08-16** — all three written and built |
| Document types — **Plan A** (registry + upload rows) | ✓ **Backend shipped 2026-08-11; upload UI reworked + browser-approved in Plan C (`ed59c29`, 2026-08-16)** | T1/T2/T3/T4/T9. One YAML registry is now the single source of truth for extraction, doc_id identity, the upload API, the model's filter enum and the upload UI. Two new types; found a collision that would have left 1 document of 78. The Upload page's original shape was rejected and subsequently redesigned by Destin in Plan C's browser pass — see the historical note below and the Plan C section |
| Document types — Plan **C** (book panel T10 + queue T13 + upload-page rework) | ✅ **Merged `ed59c29`, 2026-08-16** | C = upload-page surfaces (T10 book panel, T13 queue bounding). See the **Plan C** row below and its section. Plan **B shipped 2026-08-13** — see its own row and section |
| Standalone consolidation — Plan 7 (batch extraction) | ✓ Shipped (2026-08-02) | Batch MinerU (~4x), the backfill, recency re-calibration. Three defect fixes not in any plan. See the Plan 7 section below |
| Citation linking (post-hoc linker) | ⬛ **Superseded 2026-08-11** by attested linking | Shipped 2026-08-02, then found to overclaim: 34.2% of linked figures matched >1 document and were resolved by document authority. That ranking is now DELETED. Section kept as the historical record of the defect |
| **Attested citation linking** | ✅ **Shipped and VERIFIED LIVE** (2026-08-11) | The model tags each figure, the system verifies the tag. False-link rate down 13–15×; 100% coverage on a captured live turn, 44 figures linked by tag. Six defects found by browser testing — see the section below. The 31-query Layer 2 baseline still has not been run |
| AI Mode UI redesign | ✓ Shipped (2026-08-02) | One column, floating chrome, tools menu. Six defects found by review that left the suite green |
| Query understanding | ✓ Shipped (2026-08-03) | Agency / doc-type / JLBC-shorthand parsing. recall@5 73.81% → 88.10%, recall@15 and @20 100%. Agency is a PREFERENCE, not a filter — a measured deviation from spec Q2 |
| Budget Documents highlighting + book sections | ✓ **Shipped (2026-08-11)**, one browser check outstanding | Query highlighting marked NOTHING (measured 0 of 200 cards); now 96.5%. 647 documents rendering under raw slugs (`s-pdf`, `bd-pdf`) fold into the books they are sections of. See the section below |
| AI Mode chat history | ✓ Shipped (2026-08-03), **reviewed and hardened 2026-08-11** | Per-device transcripts, browse/search/resume past chats, auto-naming, collapsible rail. Local disk only — never the share. A second review found ELEVEN defects, four of them silent data loss; all fixed. See the section below |
| **Corpus identity — names + agency labels** | ✅ **Shipped 2026-08-16**, one browser check outstanding | Titles naming a different agency 284 → 4; duplicate titles 218 → 0; doc_ids contradicting their source 22 → 0; documents labelled with an agency they never mention 1,072 → 171. Layer 1 eval unchanged through all four corpus passes. The audit's stated root cause was wrong — see the section below |
| JLBC memo formatting for generated reports | ✓ **Shipped (2026-08-13)**, unverified in real Word | `create_document` renders a JLBC memo — letterhead, DATE/TO/FROM/SUBJECT block, house typography — instead of Word's stock styling. Nine plan-code defects found during execution, two of them tests that proved nothing. See the section below |
| AI Mode persistent conversation | ✓ **Shipped, browser-tested, merged `28567f0`** (2026-08-11) | "+ New chat" shows a row at once; the conversation survives a tab switch and keeps streaming. 742 vitest / `tsc -b` clean. Destin tested and accepted; browser testing found a two-rows-look-selected defect, fixed. Four Minors carried, and P5 (close-tab-still-aborts) is still unwatched. See the section below |
| **Plan C — book panel + queue (T10/T13) + the upload-page rework** | ✅ **MERGED `ed59c29`, 2026-08-16** | The panel shows only what is missing, not 7,104 rows of history (**3.13 MB → 0.008 MB per poll, 391×**, 7,118 file reads → 14). Book panel offers only missing editions (62 offered / **0** addable → 1 offered / 1 addable). Three rounds of UI rework with Destin at the screen (title field removed, agency picker added, ingest-switch bypass fixed). Merged `ed59c29` — the merge itself found and fixed two cross-branch defects a clean merge hid (see `707b890`). See "Plan C" below |
| **Corpus navigation** (map, spread, coverage, echo) | ✓ **Shipped, both gates passed, merged `2dc295f`** (2026-08-12) | N1–N7 + N11. A corpus inventory in the prompt, `spread` retrieval, `year_coverage`, inferred-filter echo. **G-N1: Layer 1 identical to a same-hour control. G-N2: `key_fact_rate` 0.463 → 0.685 against a real control**, every citation metric up, input tokens down 41%. Full 31-query run not yet run. See the section below |
| Document guide for generated reports | ✓ **Shipped (2026-08-13)**, merged `f91b68f` | A sixth tool, `document_guide(report_type)`, hands the model JLBC's house style and one of three report shapes only when it is about to write a document. **Advisory and unenforced** — nothing validates what the model then writes. Five plan-code defects found during execution, two of them tests that proved nothing. **Nobody has watched a real document produced under it.** See the section below |
| **Admin extensions** (E1–E3, E6) | ✓ **Merged `b108d13`, gates green, NOT yet browser-verified** (2026-08-13) | Admin-editable alias overlay for search, admin-authored office guidance in the AI prompt, a read-only "See System Guidance" window over the shipped instructions, analyst issue reports with an admin inbox, `/admin` regrouped. 2660 pytest / 834 vitest / `tsc -b` / `npm run build` all clean; E1 eval gate passed with the overlay proven live. Destin opened the app and approved the merge, but three surfaces are still unwitnessed — see the section below |
| **Plan B — resilient processing** (T5–T8, T12) | ✓ **Shipped** (2026-08-13) | A document that extracts to almost nothing is now detected, retried with another extractor, and held out of search if every method fails — instead of being written and reported `live`. Coverage floor **calibrated at 0.10 across all 7,434 documents**. 2798 pytest / 859 vitest / `tsc -b` clean, Layer 1 eval unmoved. **The acceptance run did NOT go as planned and found two real things — read the section below before building on this** |
| ⬛ Corpus identity consistency (I1–I14) | **SUPERSEDED — it is BUILT** | This row described the problem before the work. See the phase row above and the shipped section below. Two of its figures were measured WRONG: the 721 mis-labels were a fuzzy-matcher defect, not the three corrupted catalog names; and only 25 of the 137 titles carried a bullet |
| FY2027 Appropriations Report ingest | ✓ **Done + verified (2026-08-16)** | 140/140 live, 0 failures, 2,336 passages, 0 duplicate ids corpus-wide, 4.61 chunks/page. Corpus now **83,016 budget chunks / 7,566 documents**. Its titles are wrong — that is the identity defect above, not an ingest failure |
| **Whole-report links become data + an admin approval screen** | ✓ **Shipped (2026-08-16)**, acceptance walk RUN, **rendering seen in a browser** | R1–R13. The 39-edition "Full report" URL table moves out of the JS bundle into `data/report-formats.json` merged with an admin overlay on the share; three admin routes scan the corpus for unanswered editions, probe candidates live and approve them. **Adding a fiscal year is now a click, not a rebuild.** **Moved 2026-08-16: the approval screen is no longer on `/admin`** — it is a "Full report link" row inside the two JLBC book cards on the Upload page, admin-only, which resolves the R7 deviation. The plan's own code was wrong three times, each caught by measurement — a refactor that would have downloaded whole PDFs on a 404, an offline branch that was dead code, and an offline check that poisoned a 12-hour cache. The moved row's chip then had to learn to report EVERY outstanding link state, not just the waiting ones. 3232 pytest / 1142 vitest. **Nobody has seen the moved row in a browser.** See the section below |
| **Tool cards — placement, then legibility** (TC1–TC22) | ✓ **Shipped 2026-08-16**, browser-approved | A run of tool calls moved out of the space above an answer and INTO the bubble that follows it, then its contents were rewritten for an analyst who does not know what a "chunk" is. **A tool that had never been styled at all was found in the audit.** 1063 vitest / 3151 pytest / build clean, **no eval** (nothing on the retrieval, ingest, chunking, citation or prompt path). Review caught a card that stated a **falsehood** on screen. See the section below |
| **Citation highlight locate** (spec L1–L4) | ✓ **Shipped + browser-approved 2026-08-18** | 44% of correctly linked figure chips rendered "couldn't pinpoint" or the wrong page (measured on a live run). Narrative chunks now store a union bbox + per-paragraph line map; a locate endpoint resolves a cited value to exact PDF rects at click time; the viewer trusts it and falls back to the old chain otherwise; load failures are a recoverable panel with Open document + Retry. The browser pass caught ONE defect the suite missed — a vertical mirror — fixed in `1423734`. See the section below |
| **Consolidated eval pipeline** | ✅ **Shipped — merged to master (2026-08-18), 3265 pytest green** | Replaced the smoke/full/dr-probe Layer-2 organization with three `set:`s (quick 45 / deep 3 / refusal 5; **multi deferred**), a tokens/turns-to-accurate headline (wall-clock dropped), a `document_correctness` doc-type axis, a tool-error ledger, an over-time archive, a free corpus-verification script, and a **resumable judge** (partial writes + resume-skip). 53 queries, all **solvable** (0 presence misses). **deepseek-v4-flash-0731 full-45 quick rerun: 0.711 accurate (32/45), $0.21 — beats glm-5.2 (0.667) at ~1/10 cost.** Report bundle auto-opens at end of every run. See "Consolidated eval pipeline" below |
| **Product rename — JLBC Search** | ✅ **Shipped (2026-08-18), all suites + Layer 1 gate green** | Every user-facing and internal reference to "JLBC Insight" / "Ask the Budget AZ" became **JLBC Search** — SPA title, home hero, repair/health screens, launcher, installers, shortcuts, bundle names, state dirs (`%LOCALAPPDATA%\JLBC-Search`), OpenRouter `X-Title`, system-prompt lead, QUICKSTART + PREVIEW-BRIEFING, pyproject/package names. Old MCP-namespaced tool aliases kept in `citation-extract` so saved transcripts still render. Historical docs/plans/specs untouched (record of design intent). 3299 pytest / 1149 vitest / tsc / build green; **Layer 1 eval identical to baseline** (recall@5 85.71%, @15 97.62%, @20 100.00%, refusal 60%). "JLBC Agentic Search" (memo footer) deliberately kept per Destin's call. See "Product rename" section below |
| **One-click diagnostic → verification + repair** | ✅ **Rewritten (2026-08-18)**, 3304 pytest green | The old USB diagnostic only wrote a REPORT. The replacement (`packaging/diag/diag.pyw` + `diag.cmd` + new `RUN-DIAGNOSTIC.cmd`) copies the server log (redacted), **compares the network/share copy of the corpus against the USB seed** file-by-file (missing + half-copied files, plain-english verdict), then **offers to repair** — copy the missing files from USB and re-verify with the app's own `ChunkStore` open-check (the exact health-ladder rung). Root cause of the flash-and-close also fixed: every `.cmd` in the repo was LF-only; new/rewritten ones are CRLF. Verified end-to-end against the live corpus (7,932-file manifest; repair closed a 7,930-file gap and the open-check then passed at 83,197 passages). Ships on the USB only — `packaging/` is excluded from the bundle by design. `tests/test_diag_tool.py` pins the manifest/compare/copy logic. See the section below |
| **Fund identity repair** (catalog + stamps + the analyst's fund list) | ✅ **Built and APPLIED to the corpus 2026-08-23**, evals identical before/after, awaiting Destin's review | Branch `fund-identity` off `easy-wins`. 17 truncated fund names restored, 50 non-fund catalog rows removed, fund stamping bounded to word edges, and 9,454 + 776 junk stamps nulled on both corpora with a verified snapshot + reversal records. Fund list: 187 ids/49 codes → **154 funds, all named**. See "Fund identity repair" below |
| **Easy-wins batch — five small fixes** | ✅ **Built 2026-08-22, all gates green, awaiting Destin's review + browser pass** | Branch `easy-wins`. Five open STATUS items closed: fund names on the filter-values card, tool card survives the answer arriving, the books panel tells offline from nothing-missing (and stops caching the poisoned answer), the chat nickname appears without a click, the issue-inbox transcript is bounded. Plus the uv.lock rename fallout committed. Each item: agent-drafted spec → independent review → implementation → per-task review; final whole-branch review clean. pytest 3323 / vitest 1158 / tsc / build green; no eval owed (nothing on an eval-gated path). See "Easy-wins batch" below |
| **Central user roster** | 🟡 **Code complete, gates green, browser-verified 2026-08-25/26 — 3 Important defects still open, merge pending a fix pass** | Branch `user-roster`. One roster file per person now records who has opened the app, so admin dropdowns (spending limit, hand-over-admin) show real people instead of a typed username a typo could silently misdirect. G-U1 (Layer 1 eval), G-U2 (case-fold + hand-over + recovery) and G-U3 (unreadable roster) all executed live and passed. The People panel and hand-over picker render exactly as the approved mockup. **Final review found three Important defects not yet fixed as of this commit** — see "Central user roster" below before treating this as finished |

## Fund identity repair — catalog, stamps, and the analyst's fund list (2026-08-23)

Branch `fund-identity` (off `easy-wins`). Spec:
`docs/superpowers/specs/2026-08-23-fund-identity-repair-design.md` (with the
independent review's amendments, which govern). **The corpus was written**
— restore point `backups/lancedb-20260825T200430Z.zip` (CRC-verified before
the write), reversal records
`<data_dir>/fund-unstamp-reversal-{budget_chunks,fiscal_note_chunks}-2026-08-25T2005Z.json`.

Destin's directive: *"fix this more robustly so it works the way a typical
JLBC analyst would expect."* The easy-wins allowlist had stopped wrong NAMES;
the fund dimension still did not BEHAVE — 49 raw codes in the model's fund
list, "funds" that were schedule rows and agency names, and 7,000+ chunks
stamped by a substring bug.

### Three defect classes, all measured corpus-wide and re-derived by review

| class | what it was | how it was told apart |
|---|---|---|
| **Truncated names** | the s18 catalog parser cut 17 real fund names mid-phrase (`Department of Education Empowerment` → `… Scholarship Account`, `Special Employee Health Insurance` → `… Trust Fund`) | *recovery coverage* (share of the id's own stamped chunks containing the full continuation) and *dominance* of one recovered form, or a corpus-wide count (`Motor Vehicle Liability Insurance Enforcement Fund` ×235 vs bare ×2) |
| **Junk rows** | 50 catalog entries that were never funds: 25 `Total -`/`SUBTOTAL` schedule rows, 11 agency names, 11 FY-2026 budget-adjustment lines, one line item, and severed fragments (`Account`, `Block Grant`, `Species Fund`) | their "recoveries" are column collisions (`Child Safety, Department of` + the `General Fund` cell beside it); coverage low, dominant form not a fund |
| **Severed tails** | short `X Fund` entries that are really the tail of a longer fund | the word BEFORE `X Fund` in the id's own text: `Corrections/Podiatry/Recycling/Telecommunications/AHCCCS Fund` are real (bare form dominates 201/75/60/73/120); `Species Fund` is not — 16 of 18 chunks print *Game, Non-Game, Fish and Endangered Species Fund* |

**Mechanism, both halves:** parser truncation at build, and
`chunking/entity_stamper.py::_scan_for_names` matching fund names as plain
casefolded substrings with no word boundary — how `Account` stamped 5,238
chunks across 143 agencies from inside "Account**ing**".

### What shipped

- **`data/fund-catalog.yaml` repaired in place** (227 → 177) by
  `scripts/repair_fund_catalog.py`: 17 renames (each row's evidence in the
  spec), two variants that are full names rather than truncated prefixes,
  50 deletions. The delete rule IS the display allowlist
  (`funds/names.py::_looks_like_a_fund_name`, `grant` now an allowed tail),
  so catalog and screen cannot disagree about what a fund name is; two ids
  are hand-pinned because they pass the shape (`fund:block-grant`,
  `fund:species`). `scripts/build_fund_catalog.py` applies the same filter
  so a regeneration cannot resurrect the junk, and warns that it would lose
  the renames. `tests/test_fund_catalog_shape.py` guards all of it.
- **Fund stamping requires word edges.** A switch on `_scan_for_names`,
  taken by the FUND path only — the agency table path shares the function
  and was calibrated by the 2026-08-16 relabel, so it is pinned unchanged
  (`tests/test_entity_stamper_fund_boundaries.py`; the 206 existing
  stamper/relabel tests untouched).
- **`funds/unstamp.py`** nulled every stamp whose fund no longer exists, on
  BOTH corpora (the review found fiscal notes carried 752 of them — the
  spec had assumed none). It keeps `identity/relabel.py`'s five
  disciplines (lock, CRC-verified snapshot, batched writes, id-set + column
  verification, tmp+rename reversal carrying the full old `fund_mentions`
  list) **and one the precedent lacks:** it rebuilds the full-text index and
  optimizes after writing, because the ingest contract says re-added rows
  are invisible to BM25 until then. `identity/relabel.py` does not do this
  — a follow-up worth a look.

### Measured, before → after

| | before | after |
|---|---|---|
| catalog entries | 227 | **177**, every one passing the fund-name shape |
| budget chunks carrying a fund stamp | 23,628 on 187 ids | **16,301 on 154 ids** |
| stamped ids with no displayable name | 49 | **0** |
| `fund_mentions` entries pointing at a deleted id | 4,636 | **0** |
| fiscal-note chunks carrying a fund stamp | 1,071 (654 of them `Account`) | **319 on 51 ids, all named** |
| top of the fund list | `Account` ×5,238 | `Long Term Care System Fund` ×751 |

Rows rewritten: 9,454 budget + 776 fiscal-note; dry-run and apply counts
identical; verification passed on every touched row plus 200 untouched
per table.

**Layer 1 eval, control discipline:** run on the UNMODIFIED corpus minutes
before the write (`eval/results/2026-08-25T2003Z-bd58ee2`) and again after
(`…T2007Z-e461747`), same machine, same 47-query set: **recall@5 85.71% /
@15 97.62% / @20 100% / refusal 60% both times** — identical, as expected
(fund is a hard filter only when asked for; no eval query asks and no
ranking constant reads it). **A third run after the full-text index
rebuild (`…T2009Z-e461747`) is identical too** — so the keyword leg lost
nothing to the rewrite. All three result files are committed.

### What the analyst sees now

"What funds can you filter by?" lists ~154 real funds, every one by name;
no codes, no `Total -` rows, no agencies. A fund filter has no junk value
left to return.

### ⏸ Known residuals (recorded, not fixed)

- ~9 "Juvenile Corrections Fund" mentions still stamp as `fund:corrections`
  — a word-boundary rule cannot separate a real fund whose name CONTAINS
  another real fund's name; only a catalog entry for the longer fund would.
- `RetrieveView` still echoes a fund FILTER ARGUMENT as an uppercased raw
  code (the model's own chosen id) — honest, not a name; needs the server
  to echo names beside filter arguments.
- Saved AI-Mode transcripts are unaffected (retrieve JSON carries no fund
  id); an old `list_filter_values` card keeps whatever junk it captured.
- The fund stamps that REMAIN were never audited for accuracy (right name
  for the id; is the id right for the passage?) — the same per-id
  read-the-chunks method the agency audit used, if it is ever done.
- Nobody has looked at the fund list in a browser after this pass.

---

## Central user roster (2026-08-25/26)

Branch `user-roster` (off `easy-wins`, base `a1a1eb6`). Spec:
`docs/superpowers/specs/2026-08-25-central-user-roster-design.md` (U0–U16,
gates G-U0–G-U3). Plan: `docs/superpowers/plans/2026-08-25-central-user-roster.md`
(11 tasks). Mockup:
`docs/superpowers/specs/assets/2026-08-25-user-roster-mockup/people-panel.html`.

### The problem, as measured

The app had never recorded that a person exists. Every request just asked
Windows "who is running me right now" and forgot the answer immediately —
nothing on the share, in the corpus, or in settings remembered anyone.
Five admin screens needed a username and **three made the administrator
type it by hand**, after first asking the person what Windows called them:
who can open Admin, each person's spending limit, and the no-limit list.
Typing it wrong didn't error — it saved cleanly and matched nobody,
silently. Two of those screens compared usernames **exactly**, so `dmoss`
and `DMOSS` were two different people to the app — and Windows itself
doesn't keep the casing stable (`%USERNAME%` reflects how someone typed
their name at THAT logon), so the same analyst could arrive as `DMOSS` one
day and `dmoss` the next and silently split their own spending history.
Real names existed (`machine_config.json`'s `display_names`) but were
stranded on each person's own PC, which is the direct cause of "go ask
them their username" — the admin had no way to see anyone's real name.
And underneath all of it, **four separate places in the code each decided
"who is this?" on their own** (`app/identity.py::current_user`, plus a
private copy in each of `ingest/jobs.py`, `ingest/claim.py` and
`ingest/lock.py`) — three of the four ignored the `JLBC_USER` override and
fell back to the literal string `"unknown"`, so an uploaded document could
be stamped with a different name than that same person's AI Mode usage.

### What shipped

- **U0 — one identity rule.** A single case-folding comparison
  (`users/whoami.py::same_person`, backed by Python's `casefold()`) is now
  the ONLY thing anywhere in the app that decides whether two usernames
  are the same person. `harness/settings.py` (spend limits, exemptions,
  the admin seat) and `app/identity.py` (the admin gate) both route
  through it. An AST-based source guard scopes WHERE the fold may be
  used, the same discipline Invariant 7 already uses for the data-dir
  allowlist — folding is confined to username-handling packages so it
  can't quietly leak into, say, a document-id comparison.
- **A shared roster, one small file per person.** `users/registry.py`
  writes `<data_dir>/users/<folded-username>.json` — first seen, last
  seen, and a typed display name if the person or an admin set one.
  Single-writer per file (mirrors the fund-identity and identity-repair
  work's locking discipline), reads are cached, and every request that
  hits `GET /api/me` touches its own roster row in the background so
  opening the app is what registers you — no separate "sign up" step.
- **`hidden_users` joins `user_limits`/`exempt_users` in `settings.json`.**
  Hiding someone takes them off the People table; their past spending
  still counts and nothing is deleted.
- **The People panel — built to the approved mockup, not a redesign.**
  `GET /api/admin/users` joins the roster, this month's ledger and the
  settings limits into ONE payload so the three sources can't disagree on
  screen. One table: name (or "No name yet") with the raw username in
  small type beneath, last seen, spend this month (sortable, defaults
  highest-first), a monthly-limit dropdown per row, one **Hide** pill per
  row — never bare link text, a standing rule this branch also finished
  enforcing everywhere else on `/admin` (Task 10: `.adm-link` is gone from
  the whole page). Hidden people collapse to one line under the table
  ("N person(s) hidden (…) · Show").
- **The hand-over-admin picker.** The old free-text box is now a dropdown
  of real people who have opened the app (the current admin and anyone
  hidden are left out of the list). It falls back to the old typed box,
  with a plain sentence saying why, whenever the roster can't be read.
- **A stored limit/exempt/hidden key matching nobody in the roster is left
  alone** (U14) — not shown, not deleted, not warned about. It costs
  nothing unless that person ever opens the app, at which point their row
  shows the limit already set.

### Two mockup rejections, and what they changed (G-U0, 2026-08-25)

Destin rejected the first two drawn versions of the People panel on sight,
before any code was written:

1. **Three separate tables** (active people / people no longer seen /
   orphaned limit rows) sharing one sortable-table component — "too
   complicated."
2. **One table with a Status column, a "show hidden" tick box, and a
   flagged orphan-limit box** — same verdict, over the stray-limit notice
   specifically.

What shipped is the third version he approved ("okay this is fine"): one
plain table with no Status column, no tick box, and no orphan notice —
a stored limit for someone who never shows up simply doesn't render
(U14). Hidden people are one collapsed line, not a second table.

### Plan-code defects found by execution (not by the reviewers reading it)

Same pattern this project keeps recording — a plan's prose held, its
sketched code and its first-pass implementation didn't, every time:

- **A hash-of-original scheme would have defeated the whole feature**,
  caught at spec review before any code existed: the first draft's U2 said
  to append a hash to a sanitised username whenever sanitising changed
  anything, which gives `DMOSS` and `dmoss` two DIFFERENT roster files —
  exactly the split U0 exists to close. Fixed in the spec before Task 1
  started (case-fold the filename, keep the observed spelling inside).
- **The casefold guard's first version would have scanned unrelated
  packages** for `.casefold(` calls, which is far broader than "does
  identity comparison use the one blessed function" — narrowed to the
  username-handling packages only (Task 1).
- **The partial-save docstring said something the code didn't do.**
  `PUT /api/me/display-name` writes the local machine file, then the
  shared roster; the docstring, the spec and the test all claimed a
  roster-write failure still returned the just-typed name. It returns
  whatever `display_name()` resolves at that moment, which reads the
  roster FIRST — so a failed roster write means the response shows the
  OLD name, not the new one. Docstring, spec and test corrected to say
  that, rather than the code being bent to match a promise nobody had
  checked (Task 4, fix `50bb853`).
- **A comment claiming an import cycle was false** and was deleted rather
  than carried forward unexamined (Task 4, same fix commit).
- **Column-sort headings were tagged as action pills**, which meant the
  Task 7/9/10 "every action is a pill, click Hide/Show only" test guard
  would have clicked a SORT heading during its own check. Headings are no
  longer tagged `adm-btn`; the pill-clicking guard is scoped to actual
  actions and checks a Show pill is really there before clicking it away.
- **The hand-over picker's first version claimed "nobody else has opened
  the app yet" on every load** — the loading state and a failed fetch both
  look identical to a genuinely empty roster to that check, so the
  message was wrong on every fresh page load and stayed wrong forever if
  the fetch failed. Fixed to show "Checking who has opened the app…"
  while loading and fall back to the typed box (with the failure reason)
  when the fetch errors, instead of asserting a false "nobody" (Task 9,
  fix `b3a3fe8`).

### Gates — G-U1, G-U2, G-U3, all executed live, not just asserted

**Suites (commit `b3a3fe8`):** pytest **3407 passed / 5 skipped**; vitest
**1187 passed (97 files)**; `tsc -b` and `npm run build` both exit 0.

**G-U1 — Layer 1 eval, same-day control.** `ingest/` was touched (the
`same_person` swap), which is the CLAUDE.md rule for re-running the eval.
Both runs against the same corpus, same 47-query set, minutes apart: a
CONTROL on unmodified `master`
(`eval/results/2026-08-26T0235Z-a1a1eb6.json`) and the branch
(`eval/results/2026-08-26T0249Z-4b15391.json`) — **identical**: recall@5
85.71%, recall@15 97.62%, recall@20 100%, refusal precision 60%. No
ranking or retrieval code path reads a username, so no movement was
expected and none was found.

**G-U2 — case-fold, hand-over, and break-glass recovery, run against a
real server.** On a scratch data dir (never the shared dev corpus):
opened the app as `JLBC_USER=DMOSS` (writes `users/dmoss.json` with
`username: "DMOSS"`); as `destin`, set a **$25** limit on `DMOSS` through
`PUT /api/admin/settings` using the OTHER casing than the file recorded;
confirmed in a Python shell that `check_limit("dmoss", …)` and
`check_limit("DMOSS", …)` both return **25.0**; transferred admin to
`DMOSS` (`confirm_admin_transfer: true`); restarted as `JLBC_USER=dmoss`
(yet another casing) and confirmed `GET /api/me` reports `is_admin: true`;
then created `RESET-ADMIN.txt` in the scratch data dir, confirmed
`admin_claimable: true`, called `POST /api/admin/claim`, and confirmed
admin was back to `destin`. Every step passed on the first try.

**G-U3 — an unreadable roster degrades honestly, run against a real
server.** `chmod 000` on the scratch data dir's `users/` folder:
`GET /api/admin/users` returned `{"unreachable": true, "people": []}`;
a browser screenshot of `/admin` showed the People panel's exact sentence
("The list of people couldn't be read from the shared folder. Check the
shared drive is connected, then reload.") and the hand-over card's typed
box with its own sentence ("The list of people couldn't be read from the
shared folder, so you'll have to type the username…"). `chmod 755` back,
reloaded, and the table returned with all four seeded people. A second
scratch data dir holding only the admin's own roster row showed the
hand-over picker as a **disabled** `<select>` reading "Nobody else has
opened the app yet" — matching the mockup's fresh-install case exactly.

### Browser pass against the approved mockup

Screenshotted `/admin` (headless Chrome, real corpus via symlinked
LanceDB, four seeded roster rows — `destin`, `dmoss` with a $25 custom
limit, `gwashington`, and `tmartin` hidden) and compared pixel-for-pixel
against `people-panel.html`. Matched: the four-column table with the
username in small type under the name; the sortable "Spent this month ▼"
header; the limit dropdown per row; one **Hide** pill per row; the
collapsed "1 person hidden (TMARTIN, last seen Today) · Show" line; the
"Spending limits" card (only visible once AI Mode is toggled on — it was
off in the copied dev settings, which is why it didn't render at first;
this is the existing AI-Mode gating chain working as designed, not a
defect) slimmed to one "Each person, per month" field with a pointer
sentence to People; the hand-over picker listing real people (`dmoss`,
`gwashington`) with the current admin and the hidden person both
correctly excluded; the save bar's **Discard** control rendering as the
same pill class as every other action, and zero `.adm-link` elements
anywhere on the page.

### 🔴 Not yet fixed as of this commit — do not read "shipped" as "finished"

A final whole-branch review (`a1a1eb6..b3a3fe8`) found **three Important
defects**, and this session's browser pass directly reproduced the first
one live rather than taking the review's word for it:

1. **The People panel's limit dropdown and amount box are bound to the
   server's row, not to a local draft — the amount cannot actually be
   typed into.** Reproduced live: setting the input's value via script and
   dispatching an `input` event left the field reading `25` immediately
   and again 800ms later — every keystroke a real person would type gets
   overwritten by the next re-render from the server-shaped props. An
   admin can pick "A specific amount" from the dropdown but cannot
   actually enter one through the browser today.
2. **Hide/unhide compares usernames exactly**, while the roster itself can
   re-spell a person's username between visits (`DMOSS` → `dmoss`) — so
   hiding someone under one spelling may not hide them under the next.
   The fix is one shared `samePerson` helper reused across
   `PeoplePanel.tsx`, `Admin.tsx` and `AdvancedPanel.tsx`, matching the
   server-side U0 rule; it does not exist yet.
3. **The spend-limit CAP itself is checked with an exact-match total.**
   `harness/ledger.py::month_total` sums a user's spend by their exact
   stored key, so if the same person's usage is recorded under two
   spellings, the enforced cap compares against a SMALLER total than the
   number the People panel displays (which sums with the fold). The fix
   is folding `month_total` through `harness.settings.fold` and amending
   the spec's U0 table to say so.

Three smaller items were flagged "fix before merge": a dead `fold` import
left in `registry.py`, an orphan-limit test that checks `tmartin`/`ghost`
but not the `hidden_users` orphan case, and a mirror-expression test that
should pin itself against `whoami.py` directly rather than a copy.

**None of these were assigned to this task** — Task 11's brief is gates,
browser pass and this file, explicitly not the merge. They are recorded
here, unfixed, so the branch is not mistaken for finished. A follow-up
pass is expected to close all three Important items and re-run the gates
before `user-roster` merges to master.

### ⏸ Known residuals (recorded, not fixed, and not blocking by themselves)

- **Three more bare-link-styled buttons live OUTSIDE `/admin`** and were
  left alone as out of this branch's scope: `.page-upload .linkish`
  (`QueuePanel`'s refresh,×2), `.ai-dismiss` (`AiModePanel`), and
  `.page-fiscal-notes .linkbtn` (`FiscalNotes`). `/admin` itself is now
  completely free of `.adm-link` (Task 10); these three are Destin's call
  whenever he next wants the "every action is a pill" rule extended
  app-wide.
- **The browser-side fold is `toLowerCase()`, not `casefold()`.**
  JavaScript has no `casefold`, so `PeoplePanel.tsx`'s limit-setting code
  and the hand-over picker's candidate matching both use `toLowerCase()`.
  For every Windows username in this office (plain ASCII), the two agree
  with the server's `casefold()` — but the server is always the authority
  the panel renders from, never the client's own fold.
- **A name typed on two different PCs before this shipped** can still
  produce two different roster entries the first time each machine's copy
  reaches the share — the documented fallback, not a bug this branch
  introduces.
- **`%USERNAME%` case drift now FOLDS for matching purposes, but the
  ledger still records whichever spelling each request actually arrived
  under.** `DMOSS` and `dmoss` are treated as one person for limits,
  admin and hiding — but "Who spent what → by person" can still show two
  rows for one analyst if they used both spellings, because that display
  was deliberately left alone (U16) rather than folded as a side effect.
- **The month-change refetch in the People panel swallows errors** the
  same way its sibling (usage-by-month) already did before this branch —
  a transient failure leaves the table showing last month's data with no
  visible error, rather than a stale-data warning.
- **`registry.py` carries a dead `fold` import and a docstring naming a
  `_windows_display_name()` helper that actually lives in
  `app/identity.py`.** Harmless, flagged for the next pass through that
  file.
- **Risk 1 from the spec — real names now live on a shared, human-readable
  file per person on the office drive — belongs in the Administrator
  Handbook, which still does not exist** (Plan 5 Track 5, unstarted). The
  confidentiality note chat history already needed for the same reason is
  still waiting there too.
- **Nobody but this session's headless Chrome has looked at any of
  this.** Destin has not opened the real `/admin` page against the real
  corpus and clicked through the People panel himself.

---

## Easy-wins batch — five small fixes (2026-08-22)

Branch `easy-wins`, built while Destin was away with instructions to reach a
mergeable state. Specs (with implementation amendments) at
`docs/superpowers/specs/2026-08-22-*-design.md`; process: five parallel
spec-drafting agents → one independent spec review (every spec got
corrections; none was dropped) → parallel implementation on
verified-disjoint file sets → per-task reviews (several re-ran the
implementers' mutations independently) → final whole-branch review (clean).

What each fix is, and where each item's detailed record lives (marked ✅ in
place at its original STATUS entry):

1. **Fund names** — `list_filter_values` fund values carry their
   `data/fund-catalog.yaml` name, mirroring the agency branch. New read-only
   `funds/names.py`; the Invariant-7 allowlist admits it with a narrow guard
   pinning that `harness/tools.py` reaches ONLY `funds.names` (the catalog
   module writes files). See the tool-cards "Still open" list.
2. **Tool card open-state hoist** — expanded state survives the card's move
   into the answer bubble. See the tool-cards "Still open" list.
3. **Books-panel offline honesty** — the "Add a JLBC book" panel no longer
   reports an empty gap it never measured when the network is down, and no
   longer caches that wrong answer for 12 hours. See the whole-report-links
   known-limits list.
4. **Rail reload after the title deadline** — the auto-generated chat name
   appears on its own ~21 s after an answer (derived from the server's own
   title timeout, with an anti-drift test), instead of landing unseen. See
   the persistent-conversation Minors.
5. **Issue-inbox transcript bounded** — a long attached conversation scrolls
   inside a 330px container instead of making the card arbitrarily tall. See
   the admin-extensions standing caveat.

Also: `uv.lock` regenerated for the 2026-08-18 package rename — the stale
lock made every `uv run` dirty the working tree.

**Gates on the merged branch:** pytest **3323 / 5 skipped** (a solo rerun;
one health-ladder test flaked once under load during the baseline and passed
solo both times), vitest **1158 (94 files)**, `tsc -b` 0, `npm run build` 0.
**No eval run and none owed** — `git diff` against master is empty under
`retrieval/`, `ingest/`, `chunking/`, `citation/` and
`harness/system-prompt.md` (verified by the final review, not assumed).

### ⏸ Outstanding — the browser pass (jsdom applies no stylesheet)

1. `/admin` → Issue reports → a report with a long attached conversation:
   the card stays about a screen tall and the conversation scrolls inside
   itself; a two-line transcript shows no scrollbar or dead space.
2. AI Mode: expand a search card while the model is still searching — when
   the answer starts, the card moves into the bubble STILL OPEN.
3. AI Mode: ask "what funds can you filter by?" — real names ("AHCCCS
   Fund"), not `fund:` codes.
4. New chat, ask, then wait ~25 s without clicking — the sidebar nickname
   pops in on its own.
5. WiFi off → Upload: the book cards say they couldn't reach azjlbc.gov and
   show the last known answer, never "every edition is here"; WiFi back on,
   the next visit is live (no 12-hour stale claim).

Small accepted residue, recorded in the specs: the fast-title case still
waits for the ~21 s bump; deeper tool-card view state (a "show all" inside a
card) still resets on the move; the issue `description`/`expected` fields
have no length cap; `ToolGroup`/`ToolCard` keep production-dead local-state
fallbacks for bare test fixtures.

---

## Product rename — JLBC Search (2026-08-18)

Destin's instruction for the 3-person beta: replace every reference to
"JLBC Insight" or "Ask the Budget AZ" in any form with **JLBC Search**.
This section records what changed, what deliberately didn't, and the
numbers.

### What changed (user-facing and internal)

| Surface | Before | After |
|---|---|---|
| SPA `<title>` + home hero | Ask the Budget AZ | JLBC Search |
| Repair / HealthGate / CorpusPanel copy | JLBC Insight | JLBC Search |
| FastAPI title + stub HTML | JLBC Insight | JLBC Search |
| machine_config validation sentences | JLBC Insight | JLBC Search |
| Launcher `APP_NAME`, message boxes | JLBC Insight | JLBC Search |
| Start-Menu / Desktop shortcuts | JLBC Insight.lnk | JLBC Search.lnk |
| Installer echo + descriptions | JLBC Insight | JLBC Search |
| One-click installer filename | Install-JLBC-Insight.cmd | Install-JLBC-Search.cmd |
| Bundle zip + staged dir | JLBC-Insight-\<v\>.zip | JLBC-Search-\<v\>.zip |
| Per-machine state (`%LOCALAPPDATA%`) | JLBC-Insight | JLBC-Search |
| `~/.config` Linux fallback | jlbc-insight | jlbc-search |
| OpenRouter `X-Title` (spend ledger) | JLBC Insight | JLBC Search |
| System-prompt lead + prompt splitter | Ask the Budget AZ — assistant instructions | JLBC Search — assistant instructions |
| QUICKSTART.md / PREVIEW-BRIEFING.md | JLBC Insight | JLBC Search |
| pyproject / package names | ask-the-budget-az-dev / -webapp | jlbc-search / jlbc-search-webapp |
| Worker log tags | jlbc-insight: | jlbc-search: |
| Script user-agents | ask-the-budget-az/0.1, /1.0 | jlbc-search/0.1, /1.0 |

### What deliberately did NOT change

- **"JLBC Agentic Search"** (memo footer `Generated with …`, Settings FROM
  line) — explicit Destin call on 2026-08-18, outside the instruction.
- **Old MCP-namespaced tool aliases** (`mcp__ask-the-budget-az__retrieve` /
  `cite` / `cite_batch`) stay RECOGNIZED in `citation-extract.ts` and
  `RefusalBanner.tsx` so pre-rename saved transcripts still render their
  tool cards; the new `mcp__jlbc-search__*` names are added alongside.
- **Historical artifacts** — specs, plans, investigations, retired
  PROMPT-\*.md, mockups, `webapp/reference/`, committed eval result JSONs —
  are untouched; they are the record of design intent and measurement
  history. `ingest/cache.py`'s UA measurement table keeps its quoted
  `JLBC-Insight/1.0` string for the same reason.
- **`data/insight-data/`** (the gitignored dev corpus dir name) and the
  `document-types.yaml` / catalog slugs — internal storage names nobody
  sees, and renaming them would break every machine's `machine.json`.
- GitHub repo id `ask-the-budget-az-dev` and design-spec filenames —
  they are URLs/history, not the product name.

### Gates

pytest **3299 passed / 5 skipped** · vitest **1149 passed** · `tsc -b` 0 ·
`npm run build` 0. **Layer 1 eval identical to the 2026-08-18 baseline** —
recall@5 85.71%, recall@15 97.62%, recall@20 100.00%, refusal precision
60% (`eval/results/2026-08-18T1813Z-1423734.*`). The rename touched no
ranking, ingest, chunking or citation code path — only user strings, state
paths and log tags — and the eval proves it.

### Beta-bundle consequence to remember

The state-dir rename means a machine that ran the old preview has
`%LOCALAPPDATA%\JLBC-Insight` left behind; the renamed install is fully
self-contained under `%LOCALAPPDATA%\JLBC-Search` and needs nothing from
the old folder. The 3-person beta ships a fresh corpus with a **blanked
admin and blanked key** (decided 2026-08-18) — configured at the demo.

---
(**Part 1 = TC1–TC12, placement; Part 2 = TC13–TC22, contents**). Plans:
`docs/superpowers/plans/2026-08-16-tool-card-in-message-bubble.md` (7 tasks)
and `docs/superpowers/plans/2026-08-16-tool-card-part-2.md` (5 tasks, 3 in
parallel lanes). **Both containment and wording decisions were approved from
rendered mockups, committed at
`docs/superpowers/specs/assets/2026-08-16-tool-card-mockup/`** — a visual
decision needs visual evidence of what was agreed, and prose is not that.

**Part 1.** A run of tool calls was a sibling floating above the answer, and
grouping only fired on ADJACENT calls — so a turn that searched, wrote a
sentence, then searched again produced two lone rows ("searched, searched")
that the existing grouping structurally could not reach. A run now attaches
**downward**, rendering as the first child inside the bubble that follows it.
Reading order is preserved: a two-round answer gets a card above each round's
prose, never one card at the top claiming all the work.

**Part 2.** The expanded card was then found unreadable and its scope was
amended in. The header reads as a sentence (`Searched for “…” and 2 more`),
search results group by **document** rather than passage, and the icon set was
redrawn.

### 🔴 The audit found something worse than the reported defect

`document_guide` had **never been styled at all** — no icon (it fell through
to a generic filled square) and no view (`RawFallbackView`, i.e. raw JSON). It
runs immediately before the assistant writes a document, so it appears in
exactly the conversations that end in a memo the analyst sends under their own
name.

### 🔴 A card was stating a FALSEHOOD, and the fixtures are why it survived

Found by the Part 2 whole-branch review, after three lane reviews passed it.

`ListFilterValuesView` derived every displayed name from `sample_doc_title` —
which is only an **example document**, so its leading name is an *agency*
whatever dimension was listed. Asked what kinds of document the corpus holds,
the card answered **"Kinds of document the corpus covers: AHCCCS, ADOA"**.

`harness/tools.py` already attaches an authoritative catalog `name`, and the
view discarded it — `interface FilterValue` did not even declare the field.
The server's own comment reads *"the sample title only implies what an id
means; the catalog states it."*

**Why nothing caught it:** `list_filter_values` accepts
`agency | fund | doc_type | publisher` and RAISES on anything else, but both
new copy tables were keyed on `retrieve`'s **filter** vocabulary
(`agency_canonical_id`, `fiscal_year`) — values this tool can never emit —
**and the test fixtures pinned that impossible input.** Every assertion passed
against a value that never occurs. Fixed, fixtures re-pointed, and an
anti-drift guard added that reads the accepted enum out of `harness/tools.py`
at test time (conventional here — `tool-display.test.ts` already cross-checks
that file).

### Decisions worth not re-litigating

- **No relevance number, rank index or pipeline counter** (TC17). `score 1.260`
  is a raw cross-encoder logit on roughly −10..10 — not a percentage, not a
  confidence — and printing it beside a dollar figure invites reading it as
  one. Budget Documents removed its relevance number and bar for the same
  reason; order carries the ranking.
- **The collapsed card carries NO failure signal** (TC9) — no red, no count, no
  word "failed", in the visible text or the accessible name. The model retries
  a failed call itself, so a red row usually marks a transient step in work
  that then succeeded, and alarming an analyst about a self-correcting event
  spends the trust every other warning needs. **Demoted, not deleted:** the
  failure keeps its full treatment inside the expansion.
  - Consequence the request did not ask for: the settled detail line
    `all complete` had to go too. Claiming a clean run while suppressing
    `1 failed` is a false positive claim, which is worse than the noise it
    removed. Silence claims nothing.
  - **Citation failure is untouched and stays loud.** `cite`/`cite_batch` never
    render as tool rows at all; a failed citation is still a red-X chip with
    the server's reason. Core Invariant 2 lives there — verified in the diff,
    not assumed.
- **Pixel-art glyphs abandoned for these rows** (TC15). The magnifier's ring
  closed into an illegible blob at rendered size, and the app already owned a
  magnifier (`components/SearchIcon.tsx`, from the approved mockup, used in
  four places). The tool row was the only place drawing a second one. The
  mascot keeps its pixel art — that is character art, this is chrome.
- **The style-guide card states its rules are advice with nothing checking the
  finished document against them** (TC20). True: the design that added the tool
  refused a server-side rewrite because it would mean editing figures an
  analyst is about to send. A card showing house rules without saying so
  implies a check that does not exist.
- **Agency names are NOT de-duplicated** (TC21). Duplicate catalog ids for one
  agency are a real corpus defect with its own spec; two rows reading "Child
  Safety" is correct output, and collapsing them here would bury it.

### 🔴 TC22 — one width, and the reported gap was bigger than it looked

Destin reported the card changing size. Measuring found two causes, not one:
`.chat-bubble` sets `font-size: 14px` so its `65ch` resolves at 14px **and** a
nested card loses a further 34px to padding and border, while the standalone
`.chat-tool-group` also said `65ch` but inherited the document's 16px — a
*bigger* unit. The standalone card was ~100px wider and shrank the instant an
answer arrived. Both now state the same measure.

### What the reviews caught that ~1,000 passing tests did not

**Six tests that could not fail**, including: a guard whose regex was an OR, so
deleting the load-bearing half of TC20's sentence stayed green; an assertion
pinning `"4,812"`, a comma-formatted string the code never emits; and one
asserting a string that only renders in a state the test never enters. Two of
the six were the *plan's own* example code.

**Three defects invisible to any single lane.** The plan's example code
silently dropped the `and N more` count on two of four tools. A Part 1 test
still asserted the Part 1 header format, which no Part 2 lane owned. And
`toolGlyph` moved to a 24×24 viewBox in one lane while its second caller lived
in another lane forbidden to touch it — **git merged cleanly, every suite
stayed green, and the merged tree really was rendering a cropped quarter-icon.**
That last one is the third recorded instance of this shape on this project.

**The glyph fix is structural, not a patch.** `toolGlyph` is now module-private
and a `ToolGlyph` component owns its own `<svg>`, viewBox and stroke, so `tsc`
itself refuses a future caller from getting it wrong. Both a per-caller
assertion and a source-level guard were added anyway.

**One genuinely good result:** the final review ran **59 in-place mutations and
could not find a single un-failable test.** Every honesty guard died to the
mutation that mattered.

### Also fixed on the way

- A lone **failed** call was DELETED rather than demoted: the n=1 branch
  renders `ToolBody` directly (TC5's one-click rule) and so bypassed the only
  code applying the failed treatment. A lone failed retrieve expanded to an
  **empty box** — and `history-rehydrate.ts` marks a torn mid-search block
  failed with no error text, so reopening a stored interrupted chat showed a
  card claiming a completed search that never returned.
- `.chat-tool-sentence` replaced `.chat-tool-summary` and lost all five
  truncation declarations, so the header **wrapped** instead of truncating.
  jsdom applies no stylesheet; nothing caught it.

### ⏸ Still open

- ✅ **Funds render as raw ids — FIXED 2026-08-22** (easy-wins batch, see
  that section). All 187 corpus fund ids were probed live and every one is
  in the committed `data/fund-catalog.yaml` (the `fund:2005` example here
  was stale — real ids are slug-shaped), so `list_filter_values` now
  attaches the catalog name the way the agency branch does, via a new
  read-only `funds/names.py` behind its own Invariant-7 read-side guard.
  An id the catalog doesn't know still degrades to the code.
  **⚠ Name CORRECTNESS was then audited on 2026-08-22 at Destin's ask, and
  the first pass's own headline ("one of 187 is wrong") was itself wrong —
  the catalog's fund column is systemically polluted.** Reading the names
  found FOUR defect classes parsed in as "funds": schedule `Total -` /
  `SUBTOTAL` rows (18 stamped), AGENCY names filed as funds ("Department of
  Juvenile Corrections"), budget-adjustment lines ("FY 2026 Unallocated
  Salary Adjustments"), and truncations — worst, the single word "Account",
  which the ingest stamper's substring scan then matched inside
  "Account**ing**" onto 5,238 chunks across 143 agencies, the most-stamped
  "fund" in the corpus. **Destin's call ("fix the branch before merging"):
  names are now served through an ALLOWLIST** in `funds/names.py` — at
  least two words, containing the word "fund" or ending in
  "account"/"subaccount" — measured over all 227 entries with every hidden
  name read (each is pollution or a visible truncation; all four kept
  fund-less names are real funds). 138 of 187 stamped ids show verified
  names; the other 49 keep their honest raw codes, because a visible code
  beats a plausible wrong name. **Still open, its own spec:** the stamps
  themselves are the pre-existing fund twin of the 2026-08-16 agency
  mis-labelling (the query-understanding section predicted it: "fund
  resolution has the identical gap") — the fix is catalog regeneration +
  word-boundary/genericity rules in the stamper + a re-stamp pass, NOT
  display work. **→ DONE 2026-08-23 on branch `fund-identity` — see "Fund identity repair" below.**
- ✅ **A card expanded mid-search snaps shut — FIXED 2026-08-22** (easy-wins
  batch). Open state is hoisted into `AssistantTurnBubble`, which survives
  the move into the bubble, keyed by the run's first tool-call id. The
  deeper per-view state (RetrieveView's "show all", Disclosure) still
  resets on the move — deliberately out of scope, waiting for a report.
- **The doc-type anti-drift guard is one-directional by design** — the map can
  silently LOSE an entry (a missing label degrades to the raw code). Defensible;
  the code comment justifies only the other direction.
- The full 31-query Layer 2 run is unaffected by this work and still unrun.

---

## Citation highlight locate — SHIPPED 2026-08-18, browser check outstanding

Spec: `docs/superpowers/specs/2026-08-18-citation-highlight-locate-design.md`
(L1–L4). Merges `167839c` (python lane) + `0a3f913` (webapp lane). This is
the deferred **A7 coordmap** from the attested-citation spec, delivered as a
**read-time lookup** instead of an ingest artifact — no re-ingest, no schema
migration, and the existing 83k chunks are fixed immediately.

### The problem, as measured

Replayed every linked figure chip from the live run
`eval/results/agent/2026-08-17T2324Z-88f90b3` (137 figures) against the real
PDFs, simulating the viewer's exact chain: 71 highlighted correctly; **46
sat outside the stored bbox** (a merged narrative chunk stored only its
FIRST paragraph's rectangle — verified on live rows, e.g.
`jlbc-baseline-fy2024-ade-0087`'s bbox ends at y=334 while its own second
bullet sits at y≈350–390); **7 on a different page** than the stored one;
**7 defeated by accounting-paren drift** (PDF prints `$(546,838,600)`, stored
source text carries `(546,838,600)`); 4 DOCX (no page image by design); 2
genuinely absent. 44% of *correctly linked* citations rendered as a miss;
2 of the 60 misses are honest.

### What shipped

- **L1 (ingest, new docs only):** `narrative_chunk.py` stores the union bbox
  of same-page member paragraphs and per-paragraph `(text, page, bbox)`
  lines in `source_anchor` (existing JSON column). Chunk ids and text are
  byte-identical to before — eval ground truth untouched.
- **L2 (server):** `GET /api/chunks/{id}/locate?text=…` — PyMuPDF search,
  first success wins: anchor line → stored page (clipped) → whole-doc scan;
  paren-swapped + numeric-core candidates; MinerU-0-1000 autodetect shared
  with the viewer. Returns `{page, rects, basis}`; **any failure is
  `basis: "none"` and the viewer's existing chain runs unchanged** — locate
  can only add precision. Measured 0.04–0.25 s per document incl. the
  191-page AFR; open docs cached in a closing LRU (the share-handle lesson).
- **L3 (viewer):** the click-time check fetches locate with the source-side
  rendering (figure chips) or the cited slice (prose cites); when `basis` is
  not none, `PdfPage` draws exactly those rects and skips the text-layer
  strategy, and `SourceView` shows the locate page. The same fetch hydrates
  the cited-text panel for figure chips (their annotation carries no chunk
  body by design — the panel used to say "unavailable" on exactly the chips
  that have a source).
- **L4 (failure surfaces):** a PDF load failure is now a plain-language
  panel — "Couldn't open this page", the verbatim passage is still below,
  **Open document ↗** (the raw file link, always accurate — Destin's ask),
  Retry, and the raw error demoted to a detail line. DOCX sources keep the
  cited-text-forward panel, no Open button (there is no PDF; 415 by design).

### Gates

pytest 3299 / vitest 1148 / `tsc -b` / `npm run build` all green on the
merged tree; Layer 1 eval **identical to the recorded baseline** (recall@5
85.71%, @15 97.62%, @20 100%, refusal 60% — results committed as
`eval/results/2026-08-18T1101Z-718a47d.*`), G1 passes. bbox/page are
display-only: verified nothing in ranking, refusal, or eval reads them.
Live-verified against the real corpus: the measured miss above now returns
`basis: "scan", page 17` with the value's exact rect (y≈362, outside the old
bbox).

### 🔴 The browser pass caught what the suite could not

Destin clicked chips on a live server and the highlight boxes were
**vertically mirrored** — a number near the top of the page drew its box
near the bottom. Cause: the locate endpoint's rects are TOP-LEFT-origin
PDF points (PyMuPDF's convention, same as stored bboxes), and the first
version fed them through pdfjs's `convertToViewportRectangle`, which
expects BOTTOM-LEFT origin. The correct transform is the plain scale
multiply `bboxToViewportRect`'s points branch already does. Fixed in
`1423734`; the test mock now models pdfjs's real bottom-left convention
and a zoomed test pins the scale multiply, so the mirror class of bug
fails in tests from now on. Re-checked in the browser after the fix:
boxes sit exactly on the numbers — approved.

### ⏸ OUTSTANDING

- Not yet witnessed in a browser: the WiFi-off / share-blip panel with its
  Open document + Retry buttons, and a DOCX bill chip's cited-text-forward
  surface (both pinned by vitest, neither seen).
- The A7 ingest-time coordmap backfill remains the right shape for a future
  re-ingest and is NOT built; the locate endpoint makes it optional rather
  than load-bearing.

---

## ⬛ Corpus identity consistency — this section is SUPERSEDED (2026-08-16)

> **It used to say "SPEC APPROVED, NOT BUILT" and describe the problem. It is
> BUILT.** See **"Corpus identity — names and agency labels repaired
> (2026-08-16)"** further down for what shipped, the measured before/after,
> and the follow-ups.
>
> **Two figures it stated were WRONG and were corrected by measurement.**
> Kept here only so a future session that half-remembers them does not
> re-derive the same mistakes:
>
> - It blamed 721 mis-labelled documents on three corrupted catalog names,
>   on the theory that a bare `Board of` phrase had become a name for
>   `agency:ost`. **No such entry exists** — the shortest key in the whole
>   catalog is `ahcccs` — and repairing those strings changes labelling by
>   **zero**. The defect was `rapidfuzz.token_set_ratio`, which scores 100
>   for any candidate whose tokens are a subset of a catalog name, so the
>   single word `Arizona` matched perfectly.
> - It described the 137 bad new titles as "named by a bullet or a bare
>   slug". **Only 25 carried a bullet**; the rest were correct agency names
>   missing the format suffix, which no name validator can detect. And 375
>   documents sat in a third title format, not the 6 it recorded.

## Plan B — resilient processing — SHIPPED (2026-08-13)

Spec: `docs/superpowers/specs/2026-08-11-document-types-and-resilient-processing-design.md`
(**T5, T6, T7, T8, T12**; T9 shipped in Plan A, T10/T13 are Plan C, **T11 —
the backfill — is deliberately out of scope**). Plan:
`docs/superpowers/plans/2026-08-12-standalone-plan-b-resilient-processing.md`.
Calibration: `docs/superpowers/investigations/2026-08-12-coverage-floor-calibration.md`.

**The problem it solves.** A document could extract to almost nothing and
still be written to the corpus and reported `live`. `agao-afr-fy2024` produced
**20 chunks from 191 pages** — an analyst searching it found nothing and
concluded the corpus lacked the material. Nothing anywhere said otherwise.

**As shipped:** the worker measures each extraction against the source file's
own text layer, falls to the next extractor below the floor, keeps the best
attempt, and **holds a document out of the corpus entirely** when every method
fails — recording every attempt on the job. `documents.json` gains an
`extraction` record; a duplicate upload reports whether re-processing is worth
it; held-out documents appear on the Admin page under "Held out of search".

**`COVERAGE_FLOOR = 0.10`, calibrated across all 7,434 documents.** Median
coverage 87.9%; every floor from just above 2.0% to just below 17.1% catches
an identical set of two documents, so 10% is the plateau **centre**. The
spec's expected 15–25% was too high. **A ratio above 1.0 is normal** — healthy
AFRs score 278–286% because chunk text carries table markup — and is never
capped.

### 🔴 The acceptance run did not go as planned, and that is the useful part

**The document that motivated this plan no longer fails.** Re-processed
through the real queue it scored **49.0%** on the first rung — over the floor,
so the ladder never fired. Extraction is unchanged (page-100.json is still
23,894 bytes of paragraph blocks); **chunking** changed, almost certainly Plan
A's orphan recovery. The 2026-08-12 calibration measured the *stored* chunks,
not what a re-run produces.

**But it is still not a good document**, and the plan's "read the chunks, do
not count them" step is what caught it: **30% of its chunks are bare figures**
against 5–8% for its healthy siblings, with no column headers and no units —
only 5 of 388 chunks carry "expressed in thousands". Under Invariant 1 an
unlabelled figure is worse than a missing one, because it is still citable.

**So it sits in a gap: not broken enough to trigger fallback, not good enough
to use.** The floor is a catastrophic-loss detector and does exactly what it
was specified to do.

### 🔴 The forced-fallback run — coverage ranks the WRONG extractor

Run at Destin's request in an isolated worktree with the floor temporarily
raised to 0.52 (uncommitted; shipped value stayed 0.10). **The first real
rung-to-rung fallback ever executed.**

**The machinery works**: all three rungs ran, each was journalled, the document
was held out with the right sentence, and **the corpus was not damaged** — the
original 388 chunks and the sidecar record survived a failed re-processing
untouched.

| rung | coverage | real text (tag-stripped) | bare-figure pages |
|---|---|---|---|
| opendataloader | **49.03%** | 344,872 | **28%** |
| mineru | 44.77% | 353,141 | **13%** |
| mineru-ocr | 43.68% | 353,002 | 13% |

**MinerU more than halves the bare-figure rate and coverage prefers
OpenDataLoader anyway.** T5's "keep whichever result scored highest" ranks by
coverage, so **the ladder would systematically choose the structurally worse
output for this class of failure.** Volume and structure disagree, and volume
is wrong. Full write-up, including a corpus-wide calibration of a structural
signal that separates the bad document from all 2,227 others:
**`docs/superpowers/investigations/2026-08-13-structural-quality-signal-calibration.md`**.

Two more from that run: **`mineru-ocr` is nearly identical to `mineru` on a
document that HAS a text layer** (353,002 vs 353,141 chars, same 13%) — a full
extraction for essentially nothing, and the ladder runs it anyway. And a
projection that MinerU would score ~75% was **wrong**, because it extrapolated
from 5 pages chosen for being pathological; the true ratio is 0.91×, not 1.53×.

### What review caught that the suites did not

**Every task's implementation was correct and its reference tests were not.**
Three tasks found the plan's *example code* wrong while its prose held —
including a loop that would have discarded healthy extractions in production,
and one returning the *last* attempt where spec T5 says "keep whichever result
scored highest". **Four separate WHY comments asserted things measurement
contradicted**; the clearest claimed "a budget bill is mostly tables" when the
committed sample bill is 279,819 paragraph characters against 176 table
characters.

Reviewers ran their own mutations rather than trusting implementers' tables.
On Task 4 that caught 3 of 23 surviving — two of them guards that are correct,
load-bearing, and green whether or not they exist. The final whole-branch
review found two blocking defects **and** a plan defect: **T12's health message
was built, worded and tested server-side and rendered nowhere**, because Task
6's file list carried no webapp file. All fixed.

### Still open

- **The FY2024 AFR got re-minted to MinerU in the 2026-08-16 structural
  acceptance run** (`639f0cf`), but not because ranking on structure landed —
  see below. It is no longer in its OpenDataLoader state; the principled fix
  (rank on structure as the ladder's tie-break) remains unbuilt and a spec
  change.
- **Ranking on structure is unscheduled work.** Neither shipped approach
  catches this: S26 inspects the input (the two AFRs are indistinguishable, and
  FY2024 *is* tagged, so S26 routes it exactly where it already goes), and T6
  measures volume (49% did arrive).
- **The structural signal is calibrated against ONE positive example.** The
  false-positive side is solid — 2,227 of 2,228 documents score under 1%. The
  false-negative side is unknown and cannot be estimated from one example.
- **T12 only pays off for documents ingested after Plan B.** The 7,434 existing
  ones have no `extraction` record, so a duplicate upload of any of them
  correctly makes no claim.
- **Nothing has been seen in a browser** — the "Held out of search" panel, the
  two-click Dismiss, and the duplicate-upload health sentence are pinned by
  specs and unwitnessed. jsdom applies no stylesheet.

## Admin extensions — aliases, guidance, issue reports (2026-08-13)

**Merged `b108d13`; gated; visually unwitnessed.** Spec E1–E3 + E6 shipped as fourteen
tasks ([`docs/superpowers/plans/2026-08-12-admin-extensions.md`](docs/superpowers/plans/2026-08-12-admin-extensions.md),
against [the design spec](docs/superpowers/specs/2026-08-12-admin-extensions-design.md)),
each implemented by a fresh subagent and reviewed by a second one before merge. **A
fifteenth piece — the System Guidance viewer — was added after Destin saw the merged UI
running; it is not in the plan.** Both documents were written on the
`ai-persistent-conversation` branch and were copied onto master when this section was
corrected, so the links above resolve.

### What shipped

| Piece | Where |
|---|---|
| Alias overlay file (mtime-cached read, atomic write) | `store/office_aliases.py` |
| Overlay consumed in query resolution, **WEAK confidence only** | `retrieval/query_agency.py` |
| Overlay in the Budget Documents filter box | `app/search_terms.py` |
| Admin alias routes with plain-English validation | `app/routes/tuning.py` (`GET/PUT /api/admin/aliases`) |
| Office guidance file + `{{OFFICE_GUIDANCE}}` prompt slot | `harness/office_guidance.py`, `harness/prompt.py`, `harness/system-prompt.md` |
| Guidance admin routes | `app/routes/tuning.py` (`GET/PUT /api/admin/guidance`) |
| Issue report storage (one JSON file per report) | `app/issue_reports.py` |
| Issue routes — ungated submit, own-only listing, admin resolve | `app/routes/issues.py` |
| Typed client for all three | `webapp/src/api.ts` |
| Three admin panels + regrouped page | `webapp/src/admin/{Aliases,Guidance,Issues}Panel.tsx`, `webapp/src/pages/Admin.tsx` |
| Analyst-facing report page + nav entry | `webapp/src/pages/ReportIssue.tsx`, `ToolsNav.tsx`, `App.tsx` |

### The E1 gate — an admin alias cannot move ground-truth queries

Two eval runs on the same machine minutes apart, identical corpus, the second with a
three-alias overlay loaded (`dor`→`agency:rev`, `ade`→`agency:ade`, `azdps`→`agency:dps`):

| | recall@5 | recall@15 | recall@20 | refusal precision | p95 |
|---|---|---|---|---|---|
| Control (no overlay) | 88.10% | 100.00% | 100.00% | 60.00% | 768 ms |
| With overlay | 88.10% | 100.00% | 100.00% | 60.00% | 772 ms |

Results committed under `eval/results/2026-08-13T0513Z-309f3e5.*` (control) and
`…0514Z-309f3e5.*` (overlay).

**The unchanged numbers are only meaningful because the overlay was proven live.** Two of
the three fixture aliases are inert — the catalog already owns `dor` and `ade`, and the
first tier to name an agency keeps it — so the real test is `azdps`, which nothing
resolves without the overlay:

    'azdps budget'   no overlay: []   with overlay: [('agency:dps', 'WEAK')]

It resolves, and it resolves WEAK. That is the whole E1 property: an admin's alias can
improve ranking and can never delete the right answer from the page.

### Deviations from the plan

1. **Report context capture is trimmed.** The spec listed `page` and `app_version` on a
   report; the form is its own route (so "page they were on" would always read `/report`)
   and no version constant exists. Reports carry `submitted_by`, `submitted_at`,
   `description`, `expected` only.
2. **Transcript attach is a picker, not a "current conversation" checkbox** — the
   conversation lives in `Ai.tsx` state the report page cannot see. The form offers an
   optional dropdown fed by `GET /api/history` (the caller's own chats). Same consent
   property: none by default, explicit copy that the administrator will read everything.
3. **Only the NEW panels are collapsible.** The five shipped panels got grouping and
   reordering, not collapse.
4. **The eval ran against a scratch data dir** that symlinks the corpus read-only, rather
   than writing the overlay fixture into `data/insight-data/` as the plan said. The 14 GB
   working data dir was never modified.
5. **Two spec E6 copy decisions were overridden by Destin** (2026-08-12): the alias
   explanatory sentence was rewritten in office English because the spec's version used
   "corpus" and "catalogued", both banned by this repo's own jargon guard; and group
   labels now render only on multi-panel groups, so "Spending" and "Access & files" appear
   bare. Surviving labels, in order: Needs attention, AI Mode, Search & documents.

### Defects the reviews caught that the suites did not

- `load_office_aliases` raised `AttributeError` on a malformed *row* inside `added`
  (`{"added": [null]}`) — uncaught, on the path retrieval calls for every query, for a
  hand-editable file on the share. Fixed and pinned.
- The admin alias collision check consulted only the alias table, so a catalog agency's
  own NAME could be bound to a different agency: `corrections` → Revenue was accepted and
  would have boosted Revenue on every query containing "corrections". Fixed by unioning
  the name-phrase table through the same logical-group comparison.
- `save_office_guidance` moved the live file to `.bak` *before* writing its replacement, so
  a failed write left the office with no guidance at all.
- Wiring a filesystem read into `build_system_prompt` left ~134 existing prompt assertions
  reading whatever `office-guidance.md` happened to be in the live data dir. `conftest.py`
  now isolates `JLBC_DATA_DIR`.
- A refused save from the shipped-shorthand card showed the admin *nothing* — the only
  `role="alert"` lived inside the other, collapsed card, which renders no children.
- The report form claimed "Nothing else about you is collected." even when the analyst had
  attached a whole conversation. Clause dropped.
- The over-cap guidance error said "8,192 characters" while enforcing 8,192 **bytes**.

The final whole-branch review then found what no per-task review could see:

- **The agency picker offered 16 catalog ids under 7 identical display names, and the
  overlay tier was the only tier that did not expand the logical group.** "Revenue,
  Department of" appeared twice (`agency:dor`, `agency:rev`) with nothing to tell them
  apart. Duplicate ids split the stamped chunks, so an admin's shorthand landed on one
  half of a corpus; with `MATCH_PENALTY = 2.0` against `REFUSAL_THRESHOLD = 1.46`, some
  real answers become refusals. The overlay tier now expands the group (confidence stays a
  hardcoded WEAK literal) and the picker is deduped by logical group: 157 rows → 148, no
  duplicate names, and PUT still accepts any catalog id.
- **An unreachable share read as "No reports yet" and "You haven't filed a report yet"** —
  a confident claim from an unknown state. Fixing it uncovered that the `except OSError`
  around `Path.glob` was **dead code**: pathlib swallows the error (verified against a
  `chmod 000` directory), so the guard had never once fired. Now `os.listdir`, and both
  screens say the folder could not be read. A vanished share also had to be told apart
  from an empty one — `store/config.py` swallows the mkdir failure and returns the path,
  so a gone network drive surfaced as `FileNotFoundError`, i.e. "genuinely empty"; both
  this and `harness/office_guidance.py` now discriminate on the root data dir the way
  `app/health.py` does.
- **An analyst's own torn report vanished from their list** while the admin saw it — the
  non-admin filter keyed on `submitted_by`, which an unreadable stub has no room to carry.
  The frontend branch written to render it was unreachable, with a comment saying otherwise.
- **A duplicate React key**: the shipped-shorthand list is one row per agency, so `ua`
  legitimately appears twice; the specs' fixture never repeated an alias.
- **The picker dedupe then introduced its own miss** in the browse filter box, which keys
  agencies off the doc_id's trailing slug — so a shorthand set on `agency:cs` covered zero
  documents, all of which carry `-dcs-`. `_agency_terms` now expands the group too.

### The System Guidance viewer (added after the merge review, not in the plan)

Destin asked for it after opening the merged page: an administrator writing guidance
could not see the ~1,200 lines of instructions the assistant already has, so they were
liable to contradict them, duplicate them, or spend the 8 KB cap restating something.

A **"See System Guidance"** button in the AI guidance panel opens a read-only window
listing every section of the rendered instructions, grouped by kind, each expanding to
its text, with a Budget-documents / Fiscal-notes switch (the two renders genuinely
differ — 58 KB vs 49 KB). `GET /api/admin/prompt` (`app/routes/tuning.py`) does the
splitting server-side; `webapp/src/admin/SystemGuidance.tsx` renders it; the dialog shell
was extracted out of `ReportChooser` into `webapp/src/components/Modal.tsx` so both
consumers share one focus-trap implementation.

Three review findings on it were honesty defects, worth recording because the feature
exists to give an accurate picture:

- The office's own guidance was shown **last**, but `{{OFFICE_GUIDANCE}}`
  (`harness/system-prompt.md:942`) has five sections after it — including the refusal
  rules that its own preamble says override it. Two code comments asserted the opposite.
  The window now states where the block actually sits.
- The size line rendered the whole prompt's byte count (guidance already included) and
  then said the admin's writing is "added to this". It now switches on whether guidance
  is saved.
- Everything above the first `##` was silently dropped, and the test asserting nothing was
  dropped used the **same splitter**, so it structurally could not see it. There is now a
  line-coverage assertion, verified to fail when the lead is removed.

Guards worth keeping: every top-level heading must land in a named group (a new section
cannot quietly vanish from the window), and the jargon guard now exempts only the quoted
shipped heading and text — not the card around it.

### Suite counts at merge

`pytest` 2660 passed / 5 skipped · `vitest` 834 passed (79 files) · `tsc -b` exit 0 ·
`npm run build` exit 0. (The plan's own fourteen tasks finished at 2638 / 816; the
viewer added the rest.)

### Standing caveat — nobody has looked at it

jsdom applies no stylesheet. Destin opened the merged app on 2026-08-13 and approved the
merge, but did not report on every surface, and these three were never looked at:

1. **The report chooser on `/search`** (open a report card → "Full report"). The System
   Guidance work removed the `.page-docs ` prefix from 14 modal shell rules so the dialog
   would paint on the admin page. A reviewer verified no other rule targets those class
   names and that `ReportChooser` mounts only inside `.page-docs`, so it should be
   pixel-identical — but if that sheet ever renders as an unstyled white block, this is
   the change that did it.
2. **`Your tools` expanded in the System Guidance window.** That section has no `###`
   subsections (~550 lines), so it opens as one block inside a 640px scroller. If it is
   unreadable the fix is splitting it into subsections, not CSS.
3. ~~**A long attached conversation in the issue inbox.**~~ **Bounded 2026-08-22**
   (easy-wins batch): the transcript scrolls inside a 330px container, nothing
   truncated. The browser look is still owed, and the adjacent gap remains: the
   `description`/`expected` fields have no length cap server-side or display
   bound, so a very long typed report can still make a tall card.

Also unwitnessed and pinned only by specs: the byte meter, the 148-option agency select,
and the report form. The "AI Mode" group label still sits directly above the panel headed
"AI Mode" — Destin saw the stutter described and chose to leave it.

## Plan C — the book panel and the queue (2026-08-13)

Spec: `docs/superpowers/specs/2026-08-11-document-types-and-resilient-processing-design.md`
— **T10** (invert the book panel) and **T13** (the queue shows work, not
history), with T13 amended the same day. Plan:
`docs/superpowers/plans/2026-08-13-plan-c-book-panel-and-queue.md` (8 tasks).

Gates: **pytest 2861 / 5 skipped** (from 2824) · **vitest 925** (from 913) ·
`tsc -b` 0 · `npm run build` 0. **No eval run, and the rule does not ask for
one**: nothing under `retrieval/`, `chunking/`, `citation/` or
`harness/system-prompt.md` was touched. `ingest/` was, but only in where a
job file lives and which loader a caller uses — the eval calls `retrieve()`
and cannot observe either.

### 🔴 The spec's own implementation instruction was wrong, and measurement caught it

T13 said to filter job files on **mtime from the directory scan, before
parsing them**. A file's mtime does not carry the job's **state**. Measured
on the live data dir:

| | |
|---|---|
| job files | **7,118** |
| `live` / `failed` / `cancelled` | 7,100 / **14** / 4 |
| **`failed` with a file older than 24 h** | **13 of 14** |

**A 24-hour mtime window drops 13 of the 14 failures** — the exact inversion
of the clause T13 calls the one rule not to relax. The same hole applies to a
`queued` job: ingest is default-OFF per machine, so an upload can legitimately
wait days with a stale mtime while the ingest PC is closed.

### T13 is a STORAGE change, not a filter — Destin's call, 2026-08-13

Jobs reaching `live` or `cancelled` move to `<data_dir>/jobs/done/`.
**`failed` never moves**, so "every failed job regardless of age" is a
property of *where the file is* rather than a rule something must remember to
apply. Dismiss (`failed → cancelled`) moves it, so T13's "until retried,
cancelled or dismissed" falls out of the same shape.

Chosen over encoding the state in the filename because this queue is a
directory of small JSON files precisely so a colleague with no code access
can read it in Notepad (`ingest/jobs.py` module docstring). A folder named
`done` says what it holds; a filename suffix does not.

**The 24-hour window was dropped entirely.** Once finished jobs live
elsewhere an age window has nothing to do, and a window with an exception
clause is what produced the defect above. The one thing it was really buying
— not yanking a row out from under someone watching their own upload finish —
is now a **client-side** touch, because the browser knows what it was
watching and the server does not.

### Measured, before and after, on a copy of the live jobs folder

| | rows | payload | file reads |
|---|---|---|---|
| before (`load_all`) | 7,118 | **3.128 MB** per poll | 7,118 |
| after (`load_active`) | **14** | **0.008 MB** | 14 + one listing |
| `?all=1` | 7,118 | 3.128 MB | on request only |

The one-time sweep moved **7,104 files in 0.13 s**; 14 + 7,104 = 7,118, so
nothing was lost, and the only state left in the main folder is `failed`.

**The cost was in seven callers, not one.** The worst was
`ingest/worker.py::_candidates` — the ingest poll loop read all 7,118 files
every pass, off a shared drive, and nobody had noticed. Six of the seven are
equivalent by construction (their filters already excluded every archived
state). **The seventh genuinely changes and the obvious edit breaks it
silently**: every `live` job is archived, so building `last_ingest_at` from
the main folder reports "nothing has ever been ingested" against 7,434
documents, with no error. Both the naive swap and the missing fallback were
reproduced as mutations.

### 🔴 A REAL GAP the existing suite found in the new code

`test_admin_corpus_route::test_corpus_reports_the_queue` writes a `live` job
in the **pre-sweep** layout, and the first version of `newest_live_job()`
returned `None` for it. Until the sweep runs, every finished job is still in
the main folder and the archive is empty — so the admin panel would have read
"nothing ingested" for the whole window between server start and the sweep
finishing, and **permanently on any machine where the sweep cannot run**. It
now falls back to the main folder, which is never more expensive than the
`load_all()` it replaced.

### T10 — the panel offers only what is missing

Before: **62 editions offered, 0 usefully addable** — 38 ingestable and all 38
already in the corpus, 24 not ingestable and offered anyway. "Add all"
reported `skipped_existing: 139` and appeared to do nothing.

**JLBC has used FOUR book URL conventions, not two**, and this is what makes
the check correct: `{yy}ar` (approps FY2013–2026), `{yy}app` (approps
FY2005–2012), `{yy}baseline` (baseline FY2013–2027), `{yy}book1` (baseline
FY2012 only). The last two were confirmed **by title**, not guessed.
Verified against the live corpus: approps newest **FY2026** (22 editions),
baseline newest **FY2027** (16).

**A comment I wrote was wrong and mutation caught it.** I claimed a
two-pattern regex would report the newest approps edition as FY2013. It does
not — the newest year is unaffected. What it really costs is the older end
(approps 22 → 14, baseline 16 → 15), and **all nine lost editions are marked
ingestable in the catalog**, so every one would have been offered as "not in
your corpus" when the corpus holds it. The comment now says that, with the
numbers.

Editions are read from `source_url` and **never from the doc_id** — 21
documents carry a family in their id that contradicts their own title.

**Offline behaviour is part of the feature.** The answer is cached 12 hours;
a network failure serves the last good answer with `online: false` and a
plain reason. This app is verified to cold-start with WiFi disconnected, and
a panel reporting an empty gap as "everything is already here" would be a
confident wrong answer produced by a network failure.

**I nearly dropped a real capability.** T10's mockup shows only an Add
button, so the first version had no dry run — and five existing specs went
red, which is how it was noticed. "Discover" is what found the FY2027
Appropriations Report (139 documents, 0 unreachable). It returns as a
per-edition **Preview**.

### Two defects in this work's own tests

Both are the class this project keeps shipping, and neither came from review:

1. **The stage labels were RETYPED rather than moved** during the queue
   extraction, turning "Searchable" into "Done". The existing suite caught it.
2. **A spec passed with the button wired to the wrong mode** — the fake
   returned `showing: "all"` unconditionally, which flipped component state so
   a *later* poll satisfied the assertion. The fake now echoes its argument
   like the real route. Caught by mutating the button and watching it stay
   green.

Seventeen mutations were run in place across the eight tasks; every one
turned its target red.

### ⏸ OUTSTANDING — nobody has looked at either page

Every check above is data, logic or a test. **jsdom applies no stylesheet**,
so the rendering is unverified — and both of the last two shipped defects on
this project went out green under thousands of passing tests. Task 8 Step 3
of the plan carries the checklist: the queue showing a handful of rows with a
true finished count; "view all"; a 12-day-old failure present; a row
surviving the moment it turns live; the book panel offering **FY 2027
Appropriations Report** and nothing already held; an un-addable edition
showing its `era_note` with no Add button; and — WiFi off — the panel saying
it could not reach azjlbc.gov rather than hanging.

⚠ `uvicorn` runs without `--reload`, so **Python changes need a server
restart**; only the SPA picks up a rebuild.

### ✅ The browser pass HAPPENED (2026-08-15/16), and it changed more than the plan did

Destin opened the running app and the page was rebuilt three times against
what he saw. **None of this was in the plan**, and the last item is a real
defect the plan could not have anticipated.

- **"Make it feel native."** Traced to a real cause, not taste: the page
  had asked for the app's own button and chip styles since it shipped and
  **those rules were never written for it**. A stylesheet comment claimed
  the primitives were in use; it was wrong, and is corrected.
- **"Too text dense."** Measured rather than guessed: **214 words → 39**.
  Upload became an expandable part of each document-type card, the separate
  "JLBC Books" section is gone, and the timing sentence moved down beside
  the queue it describes.
- **The Title field is REMOVED.** Five of the six document types name
  themselves; a typed title *overrode* the correct automatic one
  (`build_title` honours it verbatim). Agency submissions instead get an
  **agency picker** over the 157-agency catalog plus an admin-extensible
  overlay (`store/office_agencies.py`, `GET /api/agencies`). This also
  fixed **78 identically-named** future budget requests.
- **Styling**, at Destin's direction: the public-record notice wears a warn
  outline and matching header, one caret shape throughout, six independent
  cards inside one named "Uploads" card. `--warn` (`#b45309`) is the **one
  token in the app not copied from the JLBC mockup** — the mockup palette is
  monochrome navy and has no warning colour. `#d97706` was measured at 3.3:1
  and rejected; `#b45309` gives 5.9:1.

### 🔴 A route could conscript a machine that had opted out of ingest

Found by watching a real run, not by a test. The upload and books routes
called `worker.start()` directly, so **posting to either started the ingest
worker on a machine whose `machine.json` says not to process uploads** —
defeating the per-machine switch that exists so one analyst's laptop does
not spend six hours at 100% CPU on a Baseline book.

Fixed via `ingest.worker.revive_if_this_machine_ingests(app)`, which
consults `app.machine_config.ingest_enabled()` first.

**Gating alone would have traded a CPU problem for a trust problem**, so
the counterweight shipped with it: `app/queue_status.py` is now one module
holding the predicate AND the sentence, imported by both the admin panel
and `GET /api/jobs`, and the upload page renders it verbatim above the
rows. Two implementations of "is the queue stalled?" would eventually
disagree, and the way it shows up is the worst kind — the admin page saying
all is well while an analyst watches a stuck upload.

### Gates and state — MERGED `ed59c29` (2026-08-16)

~40 mutations run against the new specs, all caught. Layer 1 eval run
2026-08-16 after the FY2027 ingest: **G1 passes**, and the recall@5
movement is the corpus, not this branch — see "What's next".

**Merged `ed59c29`** ("merge: upload-page rework, T10/T13, ingest-switch
fix, and the identity spec"), 2026-08-16. **The merge of master into the
plan-c branch found two defects a clean merge hid — see `707b890`** — so the
cross-branch concern recorded here did manifest (two defects), and was
handled *in the merge commit itself* rather than surviving into master.
Content merge: 7 files changed on both sides
(`ingest/worker.py`, `ingest/jobs.py`, `app/routes/admin.py`,
`webapp/src/api.ts`, `webapp/src/pages/Admin.tsx`,
`webapp/src/styles/app.css`, `tests/test_admin_attention_route.py`) were the
conflict points and are resolved in the merged tree. **Master's
*"surface documents that are IN search and were read badly"* is adjacent
territory — check that master-side behaviour did not change the book-panel
merge (the two could interact).**

**Gates on the merged tree (per the merge commit): pytest 2978 / 5 skipped ·
vitest 980 · `tsc -b` 0 · `npm run build` 0 · Layer 1 eval G1 passing.**
(The 2909 / 958 figures in this block were the pre-merge branch state.)

---

## Corpus identity — names and agency labels repaired (2026-08-16)

Spec: `docs/superpowers/specs/2026-08-16-corpus-identity-consistency-design.md`
(I1–I15). Plans:
`docs/superpowers/plans/2026-08-16-corpus-identity-measure-and-fix-titles.md`
(10 tasks) and
`docs/superpowers/plans/2026-08-16-corpus-identity-fixing-the-labels.md`
(13 tasks). Branch `identity-consistency`.

**An identity string — a document's title, an agency's name — was accepted
from somebody else's rendering of a PDF and never checked against the
document itself.** Three suppliers (JLBC's website index, the harvested book
catalog, PDF table-of-contents extraction) emit strings that look like names
and sometimes are not. The corpus is now repaired and the suppliers with it.

### Measured, start → end

| | start | end |
|---|---|---|
| a title naming a **different agency** than the document | 284 | **4** |
| two documents sharing one title | 218 | **0** |
| doc_ids contradicting their own `source_url` | 22 | **0** |
| titles outside `{Name} — FY {year} {Book}` | 523 | **17** |
| documents no chunk of which mentions their agency label | 1,072 | **171** |
| identity strings failing the validator | 35 | **13** |
| distinct agency slugs (duplicate ids merged) | 153 | **147** |
| uninformative (raw-slug) titles | 230 | 59 |

**Layer 1 eval is UNCHANGED through all four corpus passes** — recall@5
85.71%, @15 97.62%, @20 100.00%, refusal precision 60%, measured as a
CONTROL immediately before the first write and again after the last. Gate G1
passes. Agency is a retrieval **preference, not a filter**, which is what
makes a label change structurally unable to delete an answer.
Suite 3,145 passed / 5 skipped.

### 🔴 The audit's stated root cause was WRONG, and the real one is worth knowing

The audit blamed a corrupted catalog entry — `agency:ost`'s `canonical_name`
is a table-of-contents row — for 732 mis-labelled documents, on the theory
that the standalone phrase `Board of` became a name for that agency.
**There is no bare `Board of` entry**; the shortest key in the whole catalog
is `ahcccs`. Repairing the corrupted strings changes labelling by **zero**.

The operative defect was `_resolve`'s fuzzy fallback, which scored with
`rapidfuzz.token_set_ratio` at cutoff 85. That compares token **sets**, so
**any candidate whose tokens are a subset of a catalog name scores 100**
regardless of coverage:

| candidate | `token_set_ratio` | `token_sort_ratio` |
|---|---|---|
| `Arizona` vs the Osteopathic entry | **100** | 14 |
| `Medicine` vs the Osteopathic entry | **100** | 16 |
| `Board of Barbers` vs `Barbers, Board of` | 97 | **97** |
| `DEPARTMENT OF CORRECTIONS` vs `Corrections, State Department of` | 88 | **88** |

`extractOne` then broke the resulting 100-way tie by **catalog order**.
Fixed by scoring with `token_sort_ratio` (perfect separation at the
unchanged floor of 85) and refusing ties outright. **Repairing the catalog
string makes `Board of` score HIGHER (76.9 → 100)** — do not re-file the
catalog repair as the labelling fix.

Second half of the fix: `_JLBC_URL_RE` recognised only two of the four
directories JLBC has published under, so ~1,448 documents lost their
strongest witness. `store/book_family.py::_BOOK_DIR` already knew all four.
Third: sub-programme slugs (`axsacute`, `dhsbehav`, `desage`) are not
catalogued, so they now resolve to the longest catalogued prefix — 35 slugs,
with `appropveto` denied by name because it is the appropriation-vetoes
summary, not that agency's page.

### 🔴 Every automated gate here was insufficient on its own

Recorded because the pattern recurred four times in one session:

- **An error-rate gate is blind to a matcher that stops matching.** "How many
  labels are wrong" scores a perfect zero if nothing is labelled. Coverage
  was measured separately before committing (80.9% → 80.5% on a 4,000-chunk
  sample; retention 94.1% corpus-wide).
- **A coverage gate is blind to 195 documents.** Hand-reading the dry run
  found an AHCCCS Acute Care document losing its label and gaining nothing.
  195 against 83,197 is noise in any aggregate.
- **A chunk COUNT is blind to a dropped column.** The re-label rewrites
  `agency_canonical_ids`; a bug dropping `doc_type` leaves the count
  identical. Chunk-id SETS and a per-column sample are what verify it.
- **A per-agency gate is blind to what the analyst reads.** `search_provider`
  preferred a vendored scrape over the repaired title, so a corpus repair
  would have left the page unchanged while the audit script reported zero
  errors. **`identity/resolve.py` shipped BEFORE any repair for this reason.**

### 🔴 Two of the controller's own safety rules were wrong, and both are recorded

1. **"No agency's error count may rise."** Nine rose, net **+12** against
   **−823**. The rule existed to stop fixing one agency by breaking a clean
   one; no clean agency moved. Accepted, deviation recorded.
2. **"Merge two agency ids only if they never share a fiscal year."** This
   rejected 5 of 9 merges. Measuring the names showed all seven distinct
   pairs carry a **byte-identical canonical name** — one agency recorded
   twice, so both ids are stamped in the same year *by construction*.
   Co-occurrence is the symptom, not a reason to refuse. The primary gate is
   now the same-name test (sorted token multiset); co-occurrence remains the
   fallback where names DIFFER, which is the rename-vs-parallel-units case it
   was built for. **University of Arizona Main Campus / Health Sciences
   Center have different names, run in parallel, fail both, and stay
   separate** — kept as a test so the guard is proven to still guard.

### What shipped

- **`identity/`** — `validator.py` (is this a name? decorations strip,
  corruption quarantines), `compose.py`, `resolve.py` (the ONE read-path
  title ladder), `check.py`, `label_audit.py`, `repair.py`, `relabel.py`,
  `merge_map.py`, `merge_agencies.py`, `rename_docs.py`,
  `history_migrate.py`.
- **One title ladder for three surfaces.** Search results, the browse listing
  and AI Mode each resolved titles differently. `tests/test_identity_resolve.py`
  asserts all three agree (gate G-I4).
- **Invariant 7 held.** `identity` joined the harness import allowlist, and a
  NEW guard pins that only the READ side may be reached — `identity/repair.py`
  imports `os`/`pathlib` and rewrites `documents.json`, so allowing the
  package alone would admit them by the back door.
- **`eval/identity_check.py`** runs after every ingest; findings surface in
  the admin **Needs attention** group. The corpus scanner lives in
  `identity/check.py` because **shipped code may not import `eval/`** — it is
  excluded from the Windows bundle, so the import raises on every office
  install and is silently swallowed.
- **Reversal records for every corpus pass**, at `<data_dir>/`:
  `label-reversal-*`, `agency-merge-reversal-*`, `doc-rename-reversal-*`.
  Saved conversations were backed up to
  `~/.local/share/JLBC-Insight/conversations-backup-2026-08-16T2140Z`.

### Saved conversations were migrated, not broken

Renaming the 22 doc_ids changes their chunk_ids. Transcripts persist chunk
ids in **two** independent places — the figure annotation from
`citation/annotate.py`, and the verbatim `retrieve()` JSON in `tool`
messages, which `harness/history.py` explicitly refuses to prune. Without a
migration those citations 404 and read "Source no longer available", a hard
visible break. 20 transcripts inspected, 3 rewritten, 73 ids changed, 0
corrupt. **This is the first thing the `version: 1` transcript stamp has
ever been used for.**

### ⏸ OUTSTANDING — nobody has opened the app

Every number above is data and logic. **The rendering is unverified**, and
this repo has shipped green under thousands of passing tests twice before.
The checks, in `docs/superpowers/plans/2026-08-16-corpus-identity-fixing-the-labels.md`
Task 13: search `barbers` and confirm the FY2005 result reads *Barbers,
Board of*; open the same document in the browse listing and confirm the two
agree; filter the agency facet to Osteopathic Examiners and confirm a
handful of documents rather than ~992; ask AI Mode a question that retrieves
a repaired FY2005 document and confirm the name in the answer matches;
open a saved chat citing one of the 22 renamed documents and confirm the
citation still opens; and `/admin` → Needs attention renders the identity
findings as a plain sentence. **`uvicorn` runs without `--reload`, so Python
changes need a server restart** — only the SPA picks up a rebuild.

### Follow-ups this work created or leaves open

- **171 documents still carry a label no chunk of them mentions** (was
  1,072). Some are false positives of the metric — a per-agency page whose
  boilerplate chunk does not repeat the agency name. A long tail, not a
  systemic fault. Re-read a sample before spending on it.
- **59 uninformative titles remain** (`AXSACUTE — FY 2005 Appropriations
  Report`). The FORMAT is right and the NAME is uninformative rather than
  wrong; the wrong name is in the harvested catalog itself. Explicitly out of
  scope in the spec — it needs a slug→agency lookup, a different repair.
- **4 titles still name a different agency**, and **17 remain outside the
  format**. Small enough to read individually; nobody has.
- **The sub-programme distinguisher is a raw slug.** A repaired title reads
  `AHCCCS (axsacute) — FY 2010 Appropriations Report`. It is unique and
  better than `AXSACUTE`, but `AHCCCS — Acute Care` would be better still and
  needs a slug→readable-name table.
- **Fiscal-note version markers** — 158 notes share a title with another
  note, with no way to tell introduced from amended. Destin's call: excluded,
  needs its own spec.
- **`book_family` / `doc_kind`** (spec I11) was WITHDRAWN from this work and
  deserves its own spec. Recording `book_family` at write time WOULD retire
  real workarounds — `store/book_family.py` and its four call sites, the
  `FUSED_TOP_K` over-fetch that exists only to feed the post-rank family
  filter, `ingest/driver.py`'s doc_type→family map, and `sectionSlugsFrom` in
  the webapp. But `doc_kind` is a rename touching the extractor routing
  table, the document-type registry, query understanding, the AI-mode tool
  enum and 9 pinned eval dimensions, and no analyst can perceive either.
- **`docs/superpowers/plans/2026-08-16-declared-agency-stamping.md` is
  UNBLOCKED.** It was sequenced after this work because both touch the same
  stamping ladder. Its own note about the cause of the mis-labelling has been
  corrected in place.
- **The agency-filter-vs-preference decision was measured on poisoned data.**
  STATUS.md records a hard agency filter losing to a preference (88.10% →
  83.33% recall@5) and names *"any re-ingest that improves agency stamping"*
  as the condition to re-measure. **This is that condition.** Re-measuring is
  a separate change with its own eval and is NOT done here.

---

## Whole-report links are DATA now, and a new edition is approved from /admin (2026-08-16)

Spec: `docs/superpowers/specs/2026-08-16-whole-report-links-design.md` (R1–R13).
Plan: `docs/superpowers/plans/2026-08-16-whole-report-links.md` (6 tasks).
Branch `whole-report-links`.

**The section immediately below this one curated 39 editions by hand-editing
TypeScript.** That fixed the symptom and left the cause: adding a fiscal year
meant editing `webapp/src/reportFamilies.ts` and rebuilding the app — a step
the non-technical successor who inherits this tool cannot perform, for a list
that gains two rows every year forever. It is now data with an approval screen.

| | before | after |
|---|---|---|
| where the URL table lives | a constant in the JS bundle | `data/report-formats.json` + an admin overlay on the share |
| adding a fiscal year | edit TypeScript, rebuild, redeploy | click **Approve** on `/admin` |
| correcting a wrong link | edit TypeScript, rebuild, redeploy | reopen it under **Already answered**, reachable every day |
| who can do it | a developer | the administrator |

`data/report-formats.json` was **generated from the shipped TypeScript, never
retyped** — verified byte-identical, 39 editions / 72 URLs, no value changed.

### What shipped

| Piece | Where |
|---|---|
| The committed table + the merge with the admin overlay | `store/report_formats.py`, `data/report-formats.json` |
| The merged table on the browse endpoint | `app/routes/corpus.py` (`report_formats` on `GET /api/corpus/documents`) |
| The TypeScript table DELETED; the page reads the server's | `webapp/src/reportFamilies.ts`, `webapp/src/pages/Search.tsx` |
| Pending-edition scan + approve/correct/check | `app/routes/book_formats.py` (3 admin routes) |
| `HttpProber.head_info` — status + size from a real request | `app/routes/books.py` |
| The approval card | `webapp/src/admin/ReportLinksPanel.tsx` |
| The verifier reads the merged table, not TypeScript | `scripts/verify_report_formats.py` |

### 🔴 The plan's own code was wrong in three ways that mattered, and measurement caught each

The sixth consecutive feature where **the plan's prose held and its example
code did not.** All three were found by running it, not by reading it:

1. **The `head()` refactor the plan asked for would have downloaded whole
   PDFs to learn they are missing.** `head()` falls back to GET only on a
   literal `405` (what IIS sends for "I don't do HEAD") and asks for one byte
   via `Range`. The plan's `head_info` sketch fell back on any `>= 400` with
   no Range. Delegating would turn **every 404 into a full unranged GET** —
   ~130 per book edition, of files that are tens of megabytes. **`grep -rn
   HttpProber tests/` returns nothing**, so no test drives that path and it
   would have shipped green. `head_info` was added alongside instead, and the
   405-only rule is now pinned in both methods.
   A consequence the sketch missed: the 405 fallback asks for one byte, so its
   `Content-Length` is **1**. Reporting a 600-page book as "1 byte" would fire
   the exact "this is visibly the wrong file" alarm the size display exists
   for, every time IIS refuses a HEAD. Size now reads `Content-Range`'s total
   first, and an absent size is `None` — never `0`.
2. **The plan's offline branch was DEAD CODE, and its own offline test would
   have passed against code with no offline handling at all.**
   `book_discovery._first_live` catches every exception per rung, and
   `HttpProber.head` swallows `RequestException` and returns `False`. So with
   the WiFi off the real prober reports every candidate as "not there" and an
   `except Exception:` branch never fires — **an offline administrator would
   be told "nothing needs a link"**, a confident wrong answer produced by a
   network failure, on an app verified to cold-start offline. Rebuilt around a
   `_NetworkWatch` that tells `(None, None)` "the host never answered" from
   `(404, None)` "the host said no", and the replacement test reproduces the
   PRODUCTION shape (a prober that returns `False`, not one that raises).
3. **The offline check ran BEFORE the confirm requests, so it also poisoned
   the cache.** `plan_edition` is catalog-first and answers a catalogued
   edition with zero network calls, so the offline test saw nothing and passed;
   `_candidate` then issued the confirms, got nothing, and the nulls were
   **written into a 12-hour cache**. An administrator with the share up and the
   internet down would see no banner, a perfectly good link marked "didn't
   respond", and it would **stay wrong for the rest of the day after the
   network came back**. The check moved after the confirms and no longer
   writes the cache when it trips.

### 🔴 Four more defects, each of the class this repo keeps shipping

- **The year guard had a query-string hole.** `names_its_year` stripped only
  the scheme and host, so `…/26ar/fy2026approprpt.pdf?y=2027` answered **True**
  for FY2027 — and a WHY comment claimed the strip existed to prevent exactly
  that. Since a hand-typed URL is never checked at save time, that warning is
  the only thing between a copy-paste slip and a live, downloadable, wrong-year
  report behind a button labelled "Full report". Query and fragment are
  stripped now, and both cases are pinned.
- **The admin card was mounted and pinned by nothing.** Deleting the
  `<ReportLinksPanel />` line left **1008 of 1008 specs green**, and `tsc -b`
  complained only about an unused import. Compounding it, `Admin.test.tsx` was
  making 69 real failing fetches that guaranteed the panel was invisible in
  every Admin spec, so no assertion there could ever have seen it. Same class
  as the citation annotation that never reached the UI.
- **The whole `api.ts` wire layer was unpinned.** Typo'ing the PUT endpoint,
  and replacing the error helper that carries the server's own sentence with a
  generic `"Request failed"`, each left 1008/1008 green. Method, path and body
  keys are pinned now.
- **A stale Check verdict survived editing the address**, so the card could
  show a new URL beside the old file's size and no year warning while Approve
  sent the new one — the precise failure the card exists to prevent. And an
  emptied address box silently collapsed into "JLBC published no such format",
  so one wrong keystroke deleted a good link and recorded a positive claim.

### The load-bearing guard, and why the obvious version is wrong

`test_every_url_names_its_own_fiscal_year` is what stops a copied row keeping
last year's URL — a live, downloadable, WRONG report that no `200 OK` can
detect. The obvious implementation (`str(fy) in path or f"{fy%100:02d}" in
path`) was measured against the real 71 URLs and **accepted 32 wrong
year/URL pairs**, because `"20"` sits inside every `fy20xx` filename JLBC
publishes: under `Appropriations Report:2020` it accepted SIXTEEN other
editions' reports. Comparing whole digit runs separates perfectly — **0 real
URLs wrongly rejected, 0 wrong pairs accepted** — and the three parametrised
rows that pin it are the only rows in the suite that can see the difference.
Do not delete them; the hole comes back invisibly.

**One documented exemption, and it must stay at one:** FY2023's table of
contents genuinely lives at `budget/apprpttoc.pdf`, out of JLBC's undated
directory. That is also why a year mismatch is **flagged and never refused** —
refusing year-less URLs would make the one edition that needs a hand
correction the one edition nobody can correct.

### ✅ The acceptance walk was RUN, against a live server on the real corpus

Not reasoned about — executed, on a scratch data dir symlinking the 14 GB
corpus read-only, with `Appropriations Report:2027` temporarily removed from a
copy of the table so exactly one edition was waiting.

| step | result |
|---|---|
| the pending card's data | FY2027 Approps, **probed live**: `27ar/fy2027approprpt.pdf` **43.9 MB / 200**, `27ar/apprpttoc.pdf` **438 KB / 200**, both naming their year |
| Approve | overlay written to the share; the card cleared **on an ordinary reload**, no `?refresh` |
| the browse endpoint | table back to 39, FY2027 present, response keys exactly `{documents, report_formats}` — the overlay's problems do NOT leak onto the ungated route |
| correct an approved edition | applied, and the PUT **echoed `names_its_year: false`** for the wrong-year URL, so the warning fires even when Check was skipped |
| a real, live, WRONG-year file | `ok: true` (it really downloads, 48 MB) with `names_its_year: false` — flagged, not refused |
| the same file with `?y=2027` | also `names_its_year: false` — the hardened guard holds against a live request |
| an address that does not exist | `404`, `bytes: null`, and its own plain sentence |
| **None published** on the single file | `single_file: null` preserved through to the browse page — one format, so the row is a plain link with no chooser |
| both formats null | **400**, carrying the server's own sentence verbatim |
| **network blackholed** | `online: false` with a reason naming azjlbc.gov, **the waiting edition still listed**, and **nothing written to the probe cache** |

`scripts/verify_report_formats.py` against the live site: **72 ok, 0 failed**.
Hiding the committed table makes it FAIL loudly rather than report a clean
sweep (verified by mutation).

### ⬛ The R7 deviation is RESOLVED — the whole thing moved to /upload (2026-08-16)

**The approval screen is no longer on `/admin`. It is a "Full report link" row
inside the Baseline Book and Appropriations Report cards on the Upload page**
(`webapp/src/pages/upload/ReportLinkRow.tsx`), and `webapp/src/admin/ReportLinksPanel.tsx`
is DELETED. Destin, 2026-08-16: *"'full report links' should be an option under
the baseline book/approps report upload cards, not its own top line menu item."*

**The reason is better than tidiness.** When JLBC publishes FY2028 you do two
things in one sitting — add its documents to search, and set its "Full report"
link. Those were two pages for one event, so the second was the half you forgot.

**This RESOLVES the R7 deviation rather than carrying it over.** The panel used
to stay on screen when healthy, as one collapsed line, against spec R7's
"render nothing when nothing is waiting" — because approving a WRONG link is
what makes it healthy, so the silent rule made the only correction editor
vanish on the very click that created the mistake. That reasoning is now
satisfied by where the row lives: **the book card is permanently on `/upload`,
so the row and its "Already answered" list are reachable every day** whether or
not anything is waiting. There is no quiet-shape/alert-shape split any more;
there is one row, with its right-hand status saying what is outstanding
(`FY 2027 needs one` in amber, or `23 editions set` in grey). `.adm-group>.adm-card`
in the stylesheet now has no consumer and says so.

**Admins only, and hidden entirely from everyone else** — Destin's call over
showing it read-only. `/upload` is open to the whole office and approving an
address changes what every analyst's "Full report" button downloads. A
non-admin's card renders no row **and makes no request**; `Upload.tsx` resolves
`GET /api/me` once and hands `isAdmin` to both book cards, the idiom `Header`
already uses for the Admin pill.

**The copy was cut for the move, from a rendered mockup Destin approved**
(`.superpowers/sdd/mockup.html`). The 26-word leading explanation is gone (the
row's name and its status say it); the full web address became the **filename**
(`27ar/apprpttoc.pdf`), with the whole address on the `open ↗` link and the
line's `title`; "Use a different link" became **change**; the per-format hint
sentences are gone.

### Owner decisions, so nobody re-litigates them

All three are Destin's, 2026-08-16, and each reversed something an earlier
commit on this branch had already done.

1. **The format names stay the ANALYST'S words: "Single File PDF" and "Linked
   Table of Contents".** A mid-branch commit shortened them to *Whole book* and
   *Contents page*; that was **reverted**. `webapp/src/components/ReportChooser.tsx`
   — what an analyst sees when they press "Full report" on Budget Documents —
   prints exactly those two long names, and an admin approving a "Whole book"
   that every reader then opens as a "Single File PDF" is two names for one
   file across two screens, reconciled by the one person who cannot see both at
   once. If they are ever re-worded, **re-word the chooser first and match
   these to it**, never the other way round.
   - The cost is a layout one, and it was measured rather than argued: the book
     card has ~586px of row against ~465px of content, so "Linked Table of
     Contents" cannot share a line with a filename, a size, an opener and two
     controls at any workable column width. The name therefore takes its **own
     full-width line** (`.up-rl-k{flex:1 0 100%}`) instead of sitting in a
     fixed-width column, and cannot wrap.
2. **"not now" is DELETED.** It sat inches from "None published", and the two
   mean opposite things — "not today" against the positive claim *JLBC
   published no such format* — so the quiet one read as **reject**. The
   property it was protecting (a way out of the row that writes nothing) is the
   caret, which every other section on the page already uses, and the spec that
   drove the button is re-pointed at the caret rather than deleted.
3. **No bare blue hyperlink styling.** The address-line actions wear the page's
   existing `.fchip` pill; **Approve** is the filled navy primary, scoped to its
   own row so Add and Preview stay secondary. Two links per edition also no
   longer share the accessible name "open" — the spec that had guarded that
   ambiguity *in* now asserts the names differ.

**Nothing that catches a wrong approval was touched.** The file size, the
wrong-year warning (*"That address doesn't mention FY 2028. Open it before
approving."* — the ONE defect a `200 OK` cannot detect), the null-status vs 404
distinction, `bytes === null` rendering nothing rather than "0 MB", the
server's own sentence verbatim on a 400, a visible 500, and the correction
editor all survive with the same test ids and the same guards. The 30 specs
that pinned them MOVED with the component to
`webapp/src/pages/upload/ReportLinkRow.test.tsx`; none was deleted.

**🔴 The vocabulary trap this move creates, and the guard for it.** The upload
page knows a book family by its SLUG (`approps` / `baseline`); the report-links
table is keyed on the DISPLAY LABEL (`Appropriations Report` / `Baseline`).
Filtering the wrong one matches nothing and the row reports a clean sweep for a
family with editions waiting — no error anywhere. The row maps slug→label and
`ReportLinkRow.test.tsx` **reads `app/routes/books_missing.py::FAMILY_LABELS`
at test time** so a server-side rename fails there rather than in front of an
administrator. Verified by execution both ways: a Baseline card shows only the
Baseline edition out of a two-family fixture, and the Appropriations card only
its own.

**Two deviations from the mockup, both deliberate.** "None published" stays on
an address line even when the app HAS a suggestion — it is a real answer, not a
refusal (R1), and Appropriations Reports FY2005–FY2010 genuinely have no single
file, so hiding it behind "change" would make the correct answer for six
editions a two-click path. And a lone waiting edition gets no `FY 2028` heading
above its two format lines, because the row above already names the year.

### 🔴 The CLOSED card had to learn to report a link, and then to report ALL of them

Two rounds, and the second is the one worth remembering.

**Round one — the chip counted DOCUMENTS only.** `bookStatus` looked at missing
documents while the link state lived inside a self-fetching `ReportLinkRow` two
components below it, so the header said *"up to date"* over a row saying
*"FY 2027 needs one"*, and a shut card said nothing at all. `api.bookFormats()`
is hoisted to `Upload.tsx`, the row takes the table as a prop, and the chip
reads *"1 needs a link"* in the mockup's amber. It **removes** fetches: one
round-trip answers for both families, and a card body unmounts when it closes,
so three card-opens used to be three identical requests.

**Round two — that chip still contradicted the row it summarises.** It counted
`pending` alone, while the row treats three more states as outstanding: a
stored wrong-year address, a malformed row on the share, and a failed fetch. So
an admin approving FY2028 with a wrong-year address turned the row amber and
the header green **on the same click**, hiding the contradiction behind two
shut disclosures — and a failed fetch read *"up to date"* over a table nobody
could read. There is now one exported `linkAttention(formats, slug, error)`
that both the row and the chip derive from, returning `pending` /
`needsLook` / `cantCheck`; the chip gained a **"needs a look"** (amber) and a
**"can't check links"** (red) state. Two copies of "is there work in here?" is
exactly how the disagreement came back after round one removed it.

This also restores a property the deleted `/admin` panel had: it counted year
warnings in its own health check, so counting only `pending` was a regression
against it.

### The wrong-year warning is DERIVED, not remembered

The largest behavioural change on the branch. It used to be component state
written from the PUT's reply — and every book card unmounts the instant another
card is clicked, so an admin who approved a wrong-year address and then clicked
the other card came back to a row reading "24 editions set", not amber, with
the warning gone; reopening the edition under "Already answered" showed nothing
either. A live, downloadable, WRONG-year report behind a "Full report" button,
and the only thing that had ever said so erased by an unrelated click.

`GET /api/admin/book-formats` now reports `names_its_year` for every stored
edition, so it is a property of the DATA: it survives a remount, a reload and a
different machine, and clears itself when the address is corrected.

### The FY2023 contents page stopped raising a permanent false alarm

`budget/apprpttoc.pdf` — the one address in `YEARLESS_BY_DESIGN`, published out
of JLBC's undated directory, and genuinely the FY2023 Appropriations Report —
was flagged wrong-year on **every** visit to the book card, above a *different*
edition's approval controls. Always-on and always-wrong teaches a reader to
scroll past the one treatment the real warning wears.

The exemption lives in a new `_stored_year_check()` used **only** by
`_approved_row`, the derived warning above. `names_its_year()` is unchanged, so
`/check`, the PUT echo and a pending edition's candidates all still warn —
pasting that address for any other year really is a wrong-year report behind a
"Full report" button. Live route: approved rows flagged 1 → **0**, the FY2023
row still present and still carrying its address.

### Gates on this work

**pytest 3232 / 5 skipped · vitest 1142 (91 files) · `tsc -b` 0 ·
`npm run build` 0.** **No eval run, and the rule does not ask for one** —
`webapp/` plus one admin route; nothing under `retrieval/`, `ingest/`,
`chunking/`, `citation/` or `harness/system-prompt.md`.

Mutations, each reverted separately. The move: deleting the mount (2 red),
removing the admin gate (3 red), filtering on the slug instead of the label
(13 red), deleting the wrong-year warning (2 red), re-mounting the panel on
`/admin` (1 red). The chip round: nine more, of which **eight turned their
guard red and one SURVIVED** — removing the chip's own `isAdmin` gate, which
the fetch gate makes unreachable; that is recorded as a comment at the code
rather than left looking guarded. The FY2023 exemption: deleting it turns its
two positive specs red and leaves the two not-exempt ones green. The
`linkAttention` round: four, all red — dropping the chip's `needsLook` branch
(2), dropping its `cantCheck` branch (1), reverting the retry gate to
`{formats ? …}` (1), and dropping `needsLook` inside `linkAttention` itself,
which turns **both** the row's spec and the chip's red, which is the point of
there being one function.

### ⏸ Nobody has looked at it

jsdom applies no stylesheet. Unverified, and worth a human's eye:

- **The stacked full-width format name.** "Linked Table of Contents" on its own
  line above its filename is a layout nobody has seen; the ~586px-vs-~465px
  measurement says it must stack, not that the result reads well.
- **Chip density on the closed card.** The chip can now say *"1 needs a link"*,
  *"needs a look"* or *"can't check links"*, in two colours. Whether that reads
  as useful at a glance or as noise on a page of six cards is a judgement no
  test makes.
- The amber `is-need` state, the ellipsised filename, the nested "Already
  answered" disclosure, the `.fchip` pills, the filled-navy Approve, and the
  hairline suppression above a `FY 2028` heading.

### Gates

**As FIRST SHIPPED, before the move to /upload: pytest 3226 / 5 skipped ·
vitest 1025 (89 files) · `tsc -b` 0 · `npm run build` 0.** Roughly 45 mutations
were run across the six tasks and their fix passes; every one turned its
intended guard red. (The always-visible-when-healthy card was a net +4 specs;
that shape no longer exists — see the section above.)

**No eval run, and the rule does not ask for one** — nothing under
`retrieval/`, `ingest/`, `chunking/`, `citation/` or `harness/system-prompt.md`
was touched.

### ⏸ OUTSTANDING and known limits

- ⬛ **The browser pass below was of the /ADMIN shapes, which no longer exist.**
  It is kept because it proved the DATA and the payoff — the live probe, the
  sizes, the 39-edition correction list, and the "Full report" button appearing
  on `/search` after an approval — all of which the Upload row inherits
  unchanged. What it says about layout and copy is superseded: the panel is now
  a row on the book card and "Use a different link" is *change*. (The format
  names were shortened to *Whole book* / *Contents page* mid-branch and then
  **reverted** — see the owner decisions above.) **The moved row has not been
  seen by anybody.** Driven in headless Chrome 150 against the real corpus, with
  `Appropriations Report:2027` temporarily removed from a copy of the table so
  exactly one edition was waiting. Screenshots were read, not inferred. What
  rendered correctly:
  - **the pending card**, first in "Needs attention" — both formats named in
    English (*Single File PDF*, *Linked Table of Contents*) with their real
    sizes (**43.9 MB** and **0.4 MB**), an *Open to check ↗* link each, *Use a
    different link* / *None published*, and one **Approve** button;
  - **the healthy collapsed line** — *"Full report links · 39 editions
    answered · Show"* — one quiet row, no `<h2>`, none of the alert styling its
    neighbours use, visibly lighter than the "Issue reports" card beneath it.
    (This was Destin's deviation from R7. It rendered as intended and is now
    **gone** — the move to /upload resolved the deviation;)
  - **the expanded correction list** — all 39 editions, each offering *Change
    the links for FY {year}*, the most recently approved at the top;
  - **the payoff on `/search`** — after approving on `/admin`, the **FY 2027
    Appropriations Report** row shows a **Full report** button beside the
    FY 2027 Baseline. That row is exactly the one that had no button before.

  ⚠ Two caveats on that: it was **headless Chrome, not a human's eye**, so
  nothing here judges whether the three per-format actions read as a *choice*
  rather than a row of similar links, and the browser was the only viewport
  tested (1400px wide). ⚠ `uvicorn` runs without `--reload`, so **Python
  changes need a server restart**; only the SPA picks up a rebuild.
- **Still unwitnessed:** the blank-address warning, the offline banner and the
  stale-Check reset are pinned by specs only — each needs a state the
  screenshot run did not drive.
- **An approve-without-looking is still possible, by design (R9).** The
  mitigation is the size, the HTTP status and the year warning on the card —
  a 0.2 MB "book" or a 47 MB "table of contents" is visibly wrong. Nothing
  forces the administrator to press **Check** or open the link first.
- **Breakage of an ALREADY-approved link is not detected by the app** (R13).
  `scripts/verify_report_formats.py` is what catches it, and it must be run by
  a human — it needs the public internet, so a test reaching azjlbc.gov would
  fail on every disconnected office machine.
- **Known derivation limit.** The pending scan reuses
  `books_missing.corpus_editions()`, which reads the `{yy}ar|app|baseline|book1/`
  directory out of each document's `source_url`. Measured over all 7,574
  documents on 2026-08-16 that agrees **exactly** with the browse page's own
  rule (`section_of` then `doc_type`) — 39 editions, zero disagreement either
  way. But a book document with **no azjlbc `{yy}dir/` address** — a hand
  upload through the Upload page, or a fifth JLBC directory convention — would
  group under a family on the browse page and be **invisible to this scan**,
  so it could never become pending and would silently never get a button. If a
  hand-uploaded book section ever appears, that is the trigger to move
  `FAMILY_OF_DOC_TYPE` server-side.
- ✅ **The `app/routes/books_missing.py` dead-offline-branch hole is FIXED
  2026-08-22** (easy-wins batch). `NetworkWatch` is hoisted into
  `app/routes/books.py` (one implementation, book_formats' own suite guards
  drift); the panel now tells "the host never answered" from "JLBC said no"
  per lookahead year, serves the last good answer with `online: false` and
  the shipped reason sentence, and never writes the poisoned answer into
  the 12-hour cache (`online and not watch.unreachable`). The offline test
  now drives the real ladder with a prober that returns False — the old one
  raised OSError from a monkeypatch, a shape production cannot produce.
- **The page-count/size provenance comments were dropped.** The TypeScript
  rows carried `// 620pp/48.0MB, toc 1pp` recording what was downloaded on
  2026-08-16; JSON has no comments and the schema has no field for them, so
  that survives only in git history and in the verifier's `--full` output.

---

## "Full report" now covers every book edition in the corpus (2026-08-16)

**Destin asked why the FY2027 Appropriations Report had no "Full report"
button when the FY2027 Baseline beside it did.** The answer was neither type
nor a defect: `REPORT_FORMATS` in `webapp/src/reportFamilies.ts` — the curated
family+year → whole-report-URL map — held **three** editions (Baseline 2026 /
2027, Approps 2025). Everything else fell through to "no verified URL, so no
button". FY2025 was the mirror image, with the button on the Approps row and
not the Baseline.

**39 editions now, up from 3** — Appropriations Report FY2005–FY2027 and
Baseline FY2012–FY2027, which is every book edition the corpus holds. 72 URLs.

### Every URL was DOWNLOADED and read, and that is not ceremony

Two cheaper sources were available and both would have shipped a wrong file:

- **The vendored site index** (`webapp/reference/assets/search/index-lite.js`)
  files **slideshows and single sections under the bare report title**. "FY
  2021 Appropriations Report" is also `21H-Sfullappropspres.pdf`; "FY 2014
  Appropriations Report" is also `14AR/384.pdf`. Title matching would have put
  a presentation behind six of these buttons.
- **`data/jlbc-book-catalog.json`** is clean but is built to feed a probe
  ladder that TOLERATES a 404, so it carries unverified URLs. Its FY2027
  Baseline `linked_toc_url` is a different path from the shipped one, and
  `budget/fy2027approprpt.pdf` — the shape its own convention implies — **is a
  404**. The real FY2027 Appropriations Report is `27ar/fy2027approprpt.pdf`
  (550 pages, verified), and it is **in no committed catalog at all**, because
  that edition postdates the 2026-06-16 harvest snapshot.

Each file's page count and size are recorded on its row. Three Baseline single
files (**FY2017, FY2018, FY2019**) are scans with **no text layer whatsoever**
— they were verified by rendering their cover pages to images and reading them
by eye.

### Two shapes worth not re-deriving

- **Approps FY2005–FY2010 have a linked TOC and no single file.** JLBC did not
  publish one until FY2011 (the book catalog's `both_formats_from` agrees).
  One format means the row links straight to it with no chooser — intended, not
  a gap to fill with a guess.
- **`Baseline:2014`'s single file is 229 MB**, ~5× its siblings. It is the
  right document (cover reads "FY 2014 Baseline Book, January 2013"); JLBC
  published that one un-optimised. Nothing warns the reader about the size.

### 🔴 It invalidated the fixture of a CRITICAL regression guard

`Search.test.tsx`'s docs[0]-fallback guard — the one pinning the 2026-08-10
defect where "Full report" on the FY2026 Appropriations Report opened the
**AHCCCS section PDF** — worked by asserting that FY2026 Approps was
*uncurated and multi-document*. Curating it turned that test green-for-the-
wrong-reason territory, and it failed loudly, which is the good outcome.

Re-pointed at a **raw-slug family** (`program-review`, two fixture documents),
which by construction can never acquire a curated entry — `familyOf` returns
the slug only for doc_types `FAMILY_OF_DOC_TYPE` does not name. **Verified by
mutation**: restoring the pre-fix `docs[0]?.doc_url` fallback turns it red.

### Guards and gates

`reportFamilies.test.ts` gained four offline checks, the load-bearing one being
**every curated URL must name its own fiscal year** — copying a row and
forgetting to bump the URL yields a live, downloadable, WRONG report behind a
button, which is the one failure a 200 OK cannot detect. Verified by mutation
(FY2018 row pointed at the FY2019 report → red). One documented exemption:
FY2023's TOC lives at `budget/apprpttoc.pdf` with no year in the path, because
JLBC published that edition out of the undated directory.

`scripts/verify_report_formats.py` re-checks reachability (`--full` re-reads
every PDF). A script, not a test: it needs the public internet, and a test
reaching azjlbc.gov would fail on a disconnected office machine.

**pytest 3151 / 5 skipped · vitest 984 (88 files) · `tsc -b` 0 ·
`npm run build` 0 · all 72 URLs live.** **No eval run, and the rule does not
ask for one** — nothing under `retrieval/`, `ingest/`, `chunking/`, `citation/`
or `harness/system-prompt.md` was touched; this is `webapp/` plus one script.

### Browser-verified, unlike most entries in this file

Driven in headless Chrome against the real corpus: the FY2027 Appropriations
Report row now shows "Full report", its chooser opens with
`27ar/apprpttoc.pdf` and `27ar/fy2027approprpt.pdf`, FY2005 Approps renders as
a plain link straight to its TOC (one format, no chooser), and FY2012/FY2019
render as chooser buttons.

**Not checked:** nobody has clicked through to confirm a browser actually
renders each of the 72 PDFs, and the 229 MB FY2014 download has not been tried
on a slow connection.

## Corpus — what is ingested and what is NOT (2026-08-01)

> ⬛ **HISTORICAL SNAPSHOT — superseded by the 2026-08-02 S20 backfill.** This
> section was written the day before the backfill finished and records a
> pre-backfill corpus. Its counts (24,841 budget chunks / 3,527 documents) and
> its "Remaining work" table are **stale**: the 27 pre-FY2022 book editions were
> all ingested 2026-08-02, `agency-budget-request` / `agency-submission` are now
> registered doc_types (Plan A), and the corpus stands at **83,016 budget chunks
> / 7,566 documents** as of the FY2027 Approps ingest (2026-08-16). The AFRs
> FY2021–FY2025 are all in the corpus (see the structural-extraction section).
> The still-true core of this section — that some publish-process gaps are
> MANUAL steps (AFRs, bot-blocked agency requests) and that budget-bill is
> DOCX-only by design — is kept below.
>
> Recorded here because the deferral previously existed only as a comment in
> `~/backfill-scripts/orchestrate.py`, which is not in this repo.

**In the corpus (at 2026-08-01):** 24,841 budget chunks + 13,278 fiscal-note
chunks / 3,527 documents. JLBC Baselines FY2022–2027 and Approps FY2022–2026
(11 editions), the complete fiscal-note back catalogue (2,104 notes, sessions
2026→1999), and exactly **three** other documents — one AFR (FY2025), one
executive budget (FY2027), one budget bill (FY2026).

| Remaining work (at 2026-08-01) | Count | Blocked by |
|---|---|---|
| **JLBC books, pre-FY2022** | **27 editions** (Baselines FY2012–2021, Approps FY2005–2021) | ~~Nothing — deferred by Destin's MVP call 2026-07-31~~ **ALL INGESTED 2026-08-02** |
| **Annual Financial Reports** | 3 (FY2022–24) | ~~**`gao.az.gov` is behind Cloudflare bot management**~~ **ALL INGESTED** (FY2021–2025 now in corpus) |
| **Executive budgets** | ~~2~~ **0 — INGESTED 2026-08-01** | done (FY2025 + FY2026 now live) |
| **Budget bills** | 7 (FY2022–2027) | S24 — the harvest holds **PDFs**, and budget-bill is **DOCX-only** by design. Word versions come from JLBC internally |
| **Agency budget requests** | 78 (FY2027 only) | ~~**Plan 6 Track 1** — `agency-budget-request` is not a registered doc_type~~ **now a registered doc_type (Plan A)**. 60 reachable, **18 behind bot protection** needing a human with a browser |

**So (at 2026-08-01): 5 documents can be ingested with no new code; 85 need
Plan 6's registry; 27 book editions are a deliberate deferral, not an
oversight.** — the registry need and the 27-edition deferral are both since
closed by the backfill + Plan A.

**The AFRs cannot be fetched automatically (2026-08-01).** All four failed with
HTTP 403. Two distinct causes, found in that order:

1. `ingest/cache.py` sent no User-Agent, so it identified as `python-requests`
   and the WAF rejected it outright. **Fixed** in `e198074` (browser UA, with
   the measurements in the code comment). This was real and worth fixing — it
   would have hit other hosts too.
2. Underneath that, **`gao.az.gov` sits behind Cloudflare bot management.** The
   403 body is the "Just a moment…" JavaScript challenge (`server: cloudflare`);
   after ~15 requests it challenges the IP and even `gao.az.gov/` returns 403.
   No header defeats this — it requires executing JS in a real browser, and
   working around it is not something this project should do.

**Therefore the 3 AFRs are a MANUAL step**, in the same category as the 18
bot-blocked agency budget requests: download them in a browser, then add them
through the app's Upload page (which is the designed path — it carries the
Invariant 8 public-record confirmation). The URLs are in the mockup index.
Record this in the handbook next to the agency-request list.

Sources and verified URLs for all of the above are in the website mockup's
5,854-row index (`webapp/reference/assets/search/index-lite.js`), which spec
**S28** turns into `data/document-catalog.json`. Plan 6 Task 16 ingests the
backlog. Earlier years of agency budget requests are NOT harvested and live on
78 separate agency websites with no shared URL convention — a research project,
not a crawl.

## ✅ Structural extraction — acceptance run DONE, and it found a real defect (2026-08-16)

The acceptance step of the structural-extraction work (plan Task 8). Merges
`c7db891` (the feature), `6bae076` (admin visibility), `639f0cf` (this run),
`eccfbdc` (the defect it found). **The corpus changed**: `agao-afr-fy2024` is
re-minted and now reads with `mineru`. Restore point:
`backups/lancedb-20260816T121040Z.zip` (2.0 GB, taken automatically seconds
before the write); the previous reading's extractor output is still cached
under `extractor-output/agao-afr-fy2024/`.

**All five predictions confirmed, from the job record:**

| rung | coverage | unlabelled | outcome |
|---|---|---|---|
| `opendataloader` | 0.4903 | **0.3063** | trips the ceiling — ladder continues |
| `mineru` | 0.4477 | **0.0000** | **kept** |
| `mineru-ocr` | — | — | **never ran** (X12: text layer present, a rung had passed) |

MinerU is inside X3's comparability band (0.4477 ≥ 0.75 × 0.4903 = 0.3677) and
wins on structure. The swap renders on the admin page with both numbers; the
new "in search, but badly read" panel correctly shows nothing, because the kept
reading scores 0.00%.

**Content — the actual gate, since the count is not:**

| | before | after |
|---|---|---|
| bare digit-run passages | 117 | **0** |
| table chunks | 1 | **422** |
| chunks with any heading | few | **450 of 450** |
| chunk characters | 565,478 | 516,399 |

Page 9 was a heading-less run of digits and now reads *"DEPARTMENT OF
ADMINISTRATION / ADDITIONAL GILA WORKFORCE DEVELOPMENT AID … 200,000"* — an
agency, an appropriation name and an amount. Page 10's figures now sit under
their real column headers (NET APPROPRIATIONS / EXPENDITURES / LAPSED
APPROPRIATION AUTHORITY).

**Retrieval unmoved, against a CONTROL not a remembered baseline**
(`eval/results/2026-08-16T1122Z-9c9f8d6`, same branch and same 47-query set,
run one hour earlier on the pre-change corpus): recall@5 85.71% (=), @15
97.62% (=), @20 100% (=), refusal 60% (=). **0 of 47 queries changed status**;
one moved rank 1 → 2. Gate G1 passes.

### 🔴 What it found: the reading swap CREATED 121 wrongly-labelled passages

**This is why "read the kept chunks" is the gate and the count is not.**
Switching the document to MinerU removed 117 *unlabelled* passages and created
121 *wrongly-labelled* ones — 27% of the document claiming "(expressed in
thousands)" over whole-dollar figures, **a 1,000× error on citable numbers**,
inherited from a heading four pages earlier belonging to a different statement.

`ingest/structure.py`'s docstring already warned about exactly this
counterexample. **What was new is the SCALE.** The corpus-wide measurement on
2026-08-13 found 8 such passages in 80,854 and the defect was downgraded to a
follow-up on that basis — but that measurement was taken while this document
was read by OpenDataLoader, which emits no heading at all for those pages and
so contributed **zero**. One document raised that defect class ~15×.

**NOT fixed.** `eccfbdc` attempted it and was reverted (`1292030`) after being
measured as inert — see the next section. The real cause is
`_resolve_section_path`'s text search, and no fix is designed yet.

### Still open from this run

- **The 8 documents holding a >20-page heading run are still wrong in the
  corpus.** Re-processing them buys NOTHING until the `_resolve_section_path`
  fix lands — that was measured, see the next section. The list, for when it
  does:
  `agao-afr-fy{2021,2022,2023,2024,2025}`,
  `governor-governors-budget-fy{2026,2027}`, `jlbc-baseline-fy2027-s58`.
  **`agao-afr-fy2025` is pinned by SIX eval ground-truth chunk ids and nothing
  re-binds them** (`eval/refresh_chunk_ids.py` was deleted) — re-process it
  only with a plan for those.
- **A live document written OVER the structure ceiling is now visible** (the
  admin panel shipped in `6bae076`), but its silence means "nothing ingested
  since the measure shipped scored badly", NOT "the corpus is clean" — every
  document ingested earlier carries no measurement and can never appear there.
  `scripts/structure_scan.py` is what audits those.
- **`STRUCTURE_TIE_BAND` tension, unresolved and hypothetical on this corpus:**
  a ~100%-bare reading can still beat a materially cleaner one that falls
  outside the 0.75 size band. Deliberately NOT fixed — adding a second
  uncalibrated threshold against a failure never observed is how this gets
  fragile. Wait for a real example.
- `settings.json` on the dev corpus had `admin_username: "desti"`, a typo that
  locked the admin page. Fixed in place 2026-08-16 (backup beside it).

---

## 🔴 Heading inheritance — the bound was INERT and was REVERTED (2026-08-16)

Merge `eccfbdc`, reverted by `1292030` the same day. **Kept as the record of
how the mistake happened, because it is the exact failure this repo's own
rules warn about.**

The fix bounded `_build_outline`'s positional heading inheritance to 5 pages,
calibrated across a measured distribution of 48,382 heading runs. It had
**ZERO effect on a single chunk in the corpus** — verified by running the
actual chunker over 40 documents with and without it: section paths
byte-identical.

**Why it did nothing.** `_build_outline` is not what decides a chunk's
`section_path`. For table chunks — nearly all of an AFR or a Governor's
budget — `chunking/builders/table_chunk.py::_resolve_section_path` picks the
path by **TEXT SEARCH** (`doc.outline_path(q)` over the table's own cell
text), falling back to its own separate nearest-preceding-heading walk.
Neither consults the outline's positional inheritance.

**So the real cause of the mislabelling is the text search, not distance.**
A table on page 177 of `agao-afr-fy2023` binds to a heading on page 3 because
one of its cells matches text in that heading's section. That is why 166 of
that document's 198 chunks (84%) sit under "Note 3. — Description of Selected
Columns", and **why re-processing those documents would have fixed nothing.**

**How the error happened.** Every measurement behind the bound was taken
against `OutlineNode.body_blocks` — the MECHANISM — and treated as a proxy
for what chunks receive. The 53 → 27 → 5 curve that picked the bound is a
true measurement of a quantity nothing downstream reads. The chunker was
never run end-to-end until afterwards.

**"Assert behaviour, not mechanism."** Twelve specs passed, five of six
mutations were caught, and the whole thing verified a function no chunk
depends on. **Mutation testing proves a test observes the CODE; it cannot
prove the CODE observes anything.** The missing step was one end-to-end run
of `chunk_doc` against cached extractor output — free, offline, and about
sixty seconds.

### 📏 The measurement, kept — it was gathered for the wrong fix and fits the right one

Recorded here because it otherwise survives only inside a REVERTED commit
(`git show eccfbdc`), findable only by someone who already knows to look.
It cost real time, and whoever adds a locality rule to
`_resolve_section_path` needs exactly this: what section lengths are NORMAL.

**Contiguous heading runs across the live 97,358-chunk corpus — 48,382 runs**
(a run = consecutive pages carrying the same leaf heading; keyed on runs, not
min-to-max span, because a heading recurring in a table of contents AND its
own section is recurrence, not travel, and conflating them inflates the tail):

| run length | share |
|---|---|
| 1 page | **86.5%** |
| 2 pages | 8.3% |
| 3–5 | 4.3% |
| 6–20 | 0.8% |
| 21–50 | 12 runs |
| 51+ | 12 runs |

**Every one of the 24 runs longer than 20 pages was READ, and every one is
wrong** — "Table of Contents" governing **408 consecutive pages** of the
FY2027 Governor's budget, "Note 3. — Description of Selected Columns"
governing 27–49 pages of five separate AFRs, and a garbled fused fragment
(`OTAL OTHER FUND EXPENDITURES: \$15,208,607,391FY24 TOTAL…`) governing 65.

**A 14-run sample of the 6–20 band is all legitimate** — "Capital Projects",
"Red Imported Fire Ant Control", "CROSSWALK OF GENERAL APPROPRIATION ACT TO
…". So the boundary between right and wrong sits between 20 and 21 pages on
this corpus, and anything at or under 5 pages is unambiguously normal.

**Caveat that makes it usable rather than misleading:** these are *observed*
run lengths in the CURRENT corpus, which is the output of the buggy text
search — not ground truth about how long real sections are. A long run here
means "the current rule assigned this heading to that many pages", which is
precisely the thing being fixed. Use it to calibrate what is normal, never to
validate the fix; validate that by running `chunk_doc` end-to-end and reading
the result.

### What is still true, and still open

- **The mislabelling itself is real and large.** 166 of 198 chunks in
  `agao-afr-fy2023`; **1,092 of 1,577 in `governor-governors-budget-fy2026`
  are filed under "Table of Contents"**, spanning pages 2–643, including real
  program tables (Adult Probation Services $35,884.7, etc.).
- **`agao-afr-fy2024`'s 1,000× units error is real** and is NOT fixed: 122 of
  its 450 chunks claim "(expressed in thousands)" over whole-dollar figures.
- **The fix belongs in `_resolve_section_path`**, and it is not yet designed.
  The text-search rule binds a table to any outline node containing one of
  its cell strings, with no locality requirement at all.
- **Re-processing the 8 documents buys nothing until that lands.** The
  earlier "1,799 pages fixed" estimate in this file's history was derived
  from the same mechanism-proxy and is withdrawn.

---

## 🔴 FY2024 AFR ingested but effectively EMPTY (2026-08-01)

> **⬛ SUPERSEDED 2026-08-16.** The 20-passage state described below is long
> gone — the document was re-ingested 2026-08-13 (388 passages, OpenDataLoader)
> and re-read 2026-08-16 (450 passages, MinerU, 0% bare). Kept as the record of
> the failure that motivated both the coverage floor and the structure measure.
> The open decisions at the bottom are all now DECIDED: it was re-routed to
> MinerU by the ladder, automatically, on the evidence.

**Found immediately after ingest, by comparing passage counts.** All four AFRs
report `live`; three are fine and one is not:

| doc | pages | passages | tokens |
|---|---|---|---|
| `agao-afr-fy2021` | 163 | 169 | — |
| `agao-afr-fy2022` | 178 | 182 | — |
| `agao-afr-fy2023` | 184 | 189 | 758,497 |
| **`agao-afr-fy2024`** | **191** | **20** | **5,673** |

FY2024 yielded chunks only from pages 58 and 184–191; **pages 1–183 produced
nothing**, and its first chunk is a "THIS PAGE INTENTIONALLY LEFT BLANK" marker.

**Not a bad download and not a scan.** The PDF is tagged (`StructTreeRoot`
present) and its mid-page carries 8,700 characters of text — *more* than
FY2023's 5,076. The source is fine.

**Root cause: the publisher changed how it tags the document between years.**
On page 100, FY2023 emits **1 table block** (rows/columns, 235 KB of page JSON)
where FY2024 emits **17 paragraph blocks** (24 KB). GAO tagged FY2023's
financial statements as tables and FY2024's as loose paragraphs.
OpenDataLoader reported each faithfully; `chunking/builder.py` builds table
chunks then narrative, and found almost nothing it recognised in the paragraph
form.

**Why this matters more than one document:** a publisher silently changing
structure between editions is a recurring hazard for a corpus meant to be fed
for years by non-technical staff, and **nothing flagged it** — the job says
`live`, the queue is green, and an analyst searching FY2024 AFR content simply
gets nothing and concludes the corpus lacks it.

**This is exactly the S27 gate case, now with a real example**: a chunks-per-page
floor (~0.10 here vs ~1.03 for its three siblings) would have quarantined it
with an actionable reason. Use these four documents as the S27 calibration
fixture — they are a rare clean control, same publisher and near-identical page
counts.

**Open decisions** (deliberately not made at 2 AM): whether to re-route this
document to MinerU (S26's detect-don't-declare would do it automatically),
whether the narrative chunker should handle paragraph-tagged tables, and
whether to delete the near-empty document meanwhile so search does not answer
"nothing" for FY2024.

## ✅ `eval/queries.yaml` can now measure the recency boost (2026-08-01)

**FIXED — and the first thing it measured is a real cost.** Thirteen no-year
queries (`n-001`..`n-013`) with FY2022–2024 ground truth were added to
`eval/queries.yaml`. Coverage went from **0 of 34** queries exercising the
recency path to **13 of 47**, and the set now holds pre-FY2025 ground truth
(FY2022 ×9, FY2023 ×4, FY2024 ×4 chunks) for the first time.

**What the new instrument reports about the shipped weight
(`RECENCY_BOOST_PER_YEAR = 2.064`), same corpus, boost the only variable:**

| weight | n-* recall@5 | n-* recall@15 |
|---|---|---|
| 0.000 | **100.0%** (13/13) | 100.0% |
| 2.064 (shipped) | **76.9%** (10/13) | 100.0% |

**The boost costs 23 points of top-5 recall on old targets and costs nothing
at @15.** Ten of the thirteen sit at rank 1 with the boost off; five are
demoted and three fall out of the top 5 — `n-003` 1→8, `n-010` 1→7, `n-013`
1→8. The recurring shape is a newer near-duplicate that says *"no funding for
this program"* outranking the single edition that funded it. Worst case:
"Which appropriations did the Governor line-item veto?" puts three FY2026/27
boilerplate passages about the veto *process* above the only veto-summary
document in the corpus.

**This is a trade, not a defect** — @15 is what gate G1 measures, AI Mode reads
all 15 chunks, and the chronological-ordering win is real. But it is now a
trade with numbers on both sides, which it was not when 2.064 was chosen.
Re-decide it during the post-backfill sweep (Plan 7 Task 6).

Whole-set eval, before → after adding the block: recall@5 62.07% → **66.67%**,
recall@15 96.55% → **97.62%**, recall@20 100% → **100%**. **No existing query
changed status or rank** — the movement is entirely the new entries, which
score better at @5 than the incumbent set. Guards: `test_sweep_recency.py`
now asserts coverage stays non-zero, that pre-2025 ground truth survives, and
that no `n-*` question ever acquires a fiscal year (the silent-failure case —
layer 1 would filter it and the entry would keep printing a plausible number
while measuring nothing).

Two things deliberately NOT done: no AGAO AFR entries (the AFRs are
near-identical fund tables edition over edition, so an undated question about
a fund is legitimately answered by the newest one — pointing it at FY2022
would be ground truth invented to fail), and no FY2021 entries (the FY2021
AFR is the only FY2021 material and has the same problem).

<details><summary>The original finding, kept as the record of what was wrong</summary>

Found during the Phase D sweep and **verified independently**: of the 34 queries
in the Layer 1 budget eval, **32 name a fiscal year**, so S21 layer 1 hard-filters
them and the recency boost never executes. The other 2 are refusal queries with
no ground truth. **Zero queries exercise the code path.**

That matters beyond recency: the flat `cur@5 / cur@15 / cur@20` column across an
entire weight sweep looks like proof of safety and is nothing of the kind — it
is proof the set never ran the code. Any future "no regression" claim from this
set about ranking policy is worthless until it has no-year coverage.

**Second gap, same file:** every ground-truth chunk in it is **FY2025 (9),
FY2026 (12), FY2027 (13)** — nothing older. The set predates the backfill, so
**nothing in the repo can currently measure harm to an older target.** The
sweep's `prx@` columns (explicit-year queries with the year stripped, original
ground truth kept) are a stand-in and are **optimistic**, because their targets
are all recent and the boost helps recent targets.

Fix: add no-year queries with pre-FY2025 ground truth to `eval/queries.yaml`.
This is a prerequisite for trusting any ranking-policy change — S30's section
boost has the same blind spot.

</details>

## ⬛ The Upload UI — original shape was REJECTED, then REDESIGNED and APPROVED in Plan C (2026-08-11 → 08-16)

> **This section is now the historical record.** It was written after Plan A's
> original six-card upload UI was rejected, before the Plan C browser rework.
> That rework then happened and merged with `ed59c29` (2026-08-16): the page
> was rebuilt three times against Destin at the screen, the title field was
> removed, an agency picker added, text cut 214→39 words, and Destin
> browser-approved it. See the Plan C section's "browser pass HAPPENED". The
> specific "do not polish" instruction below is **resolved**; the still-useful
> part is the "agree the shape before building" lesson and the behaviour-notes.

What happened, recorded so the redesign starts from the right place and the
mistake is not repeated:

1. Destin asked for the six document types to "each have a selectable UI row in
   the upload tab". **That was misread when the spec was written**: it became
   six independent upload cards, each with its own file input, fiscal-year
   field, public-record checkbox and Submit button, stacked down the page. He
   rejected it on sight — *"why are there 6 entirely different upload cards"*.
   **The word doing the work was "selectable"**: he meant a selector made of
   rows feeding ONE form, not six parallel forms.
2. Rebuilt as one card — a selectable list of the six types, one form below it,
   redirect types showing their explanation where the form would be. **Also
   judged unsatisfactory** ("this still sucks"), and he stopped there rather
   than iterate mid-stream. The specifics of what is wrong were deliberately
   not gathered at that moment; **ask before assuming at redesign time.**

The one-card version is on master because master otherwise carried the shape he
rejected outright and Plans B/C build on top of it. It is an interim.

**The failure was upstream of every gate.** The spec said "six guided rows", the
plan implemented it, and every reviewer checked the rows against the spec and
passed them — correctly. No test, review or eval can catch a UI shape that
faithfully implements a misread requirement. **When the deliverable is a
layout, agree the shape with Destin before building it** — the brainstorming
skill's visual companion exists for exactly this.

**Behaviour underneath is reviewed and should survive any redesign** (all of it
is pinned by specs): registry-driven types with no hardcoded list in the page,
`publisher` derived server-side and never sent by the client, stage required
for a type that declares one, the Invariant 8 public-record gate,
drag-and-drop sharing one code path with the file picker, the filename
fiscal-year sniff, 409-duplicate handling, and a `role="status"` success
confirmation visible without scrolling to the queue.

Open judgement calls the redesign should settle, from the one-card build:
switching type currently clears the form (deliberate — carrying a file across a
type change is how an AFR gets uploaded as an Executive Budget); no type is
pre-selected, so the form appears only after a choice.

## Document types — Plan A shipped (2026-08-11)

Spec: `docs/superpowers/specs/2026-08-11-document-types-and-resilient-processing-design.md`
(T1–T14; **this plan implements T1, T2, T3, T4 and T9 only**). Plan:
`docs/superpowers/plans/2026-08-11-plan-a-document-types-and-upload-rows.md`
(7 tasks). **Supersedes the old Plan 6's scope**, which is now three plans:
A (this), B (resilient processing, T5–T8/T12), C (upload surfaces, T10/T13).

**Document types are described in exactly one place now.** `data/document-types.yaml`
plus `ingest/doc_types.py` feed the extractor dispatcher, doc_id identity, the
upload allowlist, `GET /api/document-types`, the model's tool-boundary filter
enum, and the upload page. Two new types are registered end to end
(`agency-submission`, `budget-bill-summary`), and the upload page's dropdown of
raw internal slugs (`s-pdf`, `bh-pdf`, `detailed-list-pdf` — unusable by an
analyst) is now six guided rows that each name a real document, say where it is
published and which file to use.

Gates on the merged tree: **pytest 2443 / 5 skipped** (base control 2392),
**vitest 756**, `tsc -b` 0, build clean, and **eval identical to a same-machine
control** — recall@5 88.10% · @15 100% · @20 100% · refusal 60%. Gate G1 passes.

### 🔴 The defect that would have left 1 document out of 78

`make_doc_id`'s non-JLBC branch **dropped the filename entirely**, assuming one
document per publisher per fiscal year. True for the AFR and the Executive
Budget; false for the 78 agency budget submissions the backfill is meant to add.
Verified by execution before the fix: `BHA-FY27.pdf` and `DXA-FY27.pdf` both
minted `governor-agency-submission-fy2027`. **A corpus write is an upsert**, so
ingesting 78 documents would have left **one**, with nothing erroring anywhere —
the same collision class already fixed once for JLBC books, arriving by a
different route. The fix is registry-driven and **structurally cannot move an
existing id**: `make_doc_id` returns from inside `if publisher == "jlbc":`
before any changed line, which is a stronger guarantee than the corpus sweep
that was originally proposed.

A third instance of the same class was caught in review: two Budget Bill
Summaries for one year differing only by stage collided, because `stage` was
required and distinguishing but absent from the id. Also fixed.

### The registry is now the single source of truth — and two hidden second copies were removed

- **`harness/tools.py`'s `_DOC_TYPES` had drifted to 11 entries against 15**, and
  a filter on a missing value is rejected at the tool boundary with **no error**,
  so the model concludes the corpus lacks the material. It is now pinned equal to
  the registry, so it cannot drift again.
- **`Upload.tsx` hand-maintained a doc_type→publisher map with a `?? "jlbc"`
  fallback.** That defeated T4's own acceptance test ("adding a seventh row must
  be a change to the YAML, not to code"): a row declaring `publisher: agency`
  would have posted `jlbc`, minted the wrong id, and been unfindable by a
  publisher filter — silently. **The server now derives publisher from the
  registry and the client no longer sends it.**

### 🔴 "budget bill summary" hard-filtered onto the wrong document type

Found by the final review, verified by execution: `"what did the budget bill
summary say about AHCCCS"` resolved to `doc_type: budget-bill` — the 136-chunk
FY2026 DOCX feed bill — returning **zero** summary chunks. `"budget bill"` is an
EXACT phrase (a hard filter) and the new type had no phrase of its own.

Worse, it lands in the silent shape `retrieval/query_doc_type.py`'s own
docstring warns about: those budget-bill chunks are non-empty, so the
empty-result fallback never fires and `dropped_filters` stays empty — **the
analyst is never told a filter was inferred.** Invariant 3. Fixed with an
ordered phrase entry; eval unchanged.

### T9 — the model is told how bill summaries relate to Appropriations Reports

A Budget Bill Summary precedes that year's Appropriations Report, may answer
current-year questions, must be **ignored entirely** once the Appropriations
Report is published, and — since several exist per year for drafts that later
changed — only the most recent is trustworthy.

**The model cannot observe corpus state**, so every condition is written as a
check it can run. Two defects here were caught only by review:

1. The Approps-Report check's example filter **omitted `fiscal_year`**. Since
   approps chunks exist for many prior years, that search almost always returns
   material, so the model would conclude the current year's report was published
   when it was not — and cite a stale prior-year enacted figure. A silent
   wrong-year citation.
2. **`stage` reached the job record and stopped there** — never `documents.json`,
   never `doc_title`. The retrieved chunk payload carries no stage, so
   "Engrossed supersedes Introduced" was an instruction whose condition the model
   could never evaluate. It would have shipped green, because a prompt test can
   only assert the text is present. Fixed by putting the stage in the document
   title, traced end to end from `build_title` through `documents.json` and
   `titles_for()` to the `doc_title` the model actually sees.

### 🔴 Two tests passed whether or not their feature worked

Both caught, and the pattern is the point. One asserted a jsdom-unobservable
native file-input reset. The other pinned the fiscal-year fix above over a
1,500-character window spanning three bullets, two of which mention
`fiscal_year` — so reverting the fix left the suite **green**. Its own RED
evidence had reverted the whole commit, stripping both bullets at once: **a wide
revert cannot prove a narrow pin.** Found by a reviewer re-running the mutation
narrowly rather than reading the assertion.

### The plan's PROSE held; its example CODE was wrong five times

A function named that does not exist (`inferMetaFromFilename` for `guessMeta`),
a call against a signature that never gains the parameter (`new_job(stage=)`,
which would have `TypeError`d every upload), a filter missing the field its own
prose demanded, a test asserting a substring of the wrong string, and a holdout
the plan did not anticipate. Every one was caught before merge. **Treat plan code
blocks as sketches to run and correct, not text to transcribe.**

### ⏸ OUTSTANDING — nobody has opened the page, and nothing has been ingested

- **The rebuilt Upload page is unverified in a browser.** jsdom applies no
  stylesheet. Check: the six rows' rhythm and the new row heading; drag a PDF
  onto a row (the affordance was added blind); the per-row success confirmation
  visible without scrolling; the two redirect rows scrolling to the Add-a-book
  panel; the stage picker on Budget Bill Summary.
- **No document of either new type has ever been extracted.** MinerU routing is
  asserted, never executed on a real Agency Submission or a real "House and
  Senate Budget Bills" PDF — chunk quality and agency stamping for these two
  types are unknown. This is the S27-gate shape the FY2024 AFR recorded.
- **The T9 rule has never run against a live model.** Needs a keyed machine and
  two real summaries in the corpus.
- **Deliberately not fixed:** the JLBC branch does not slugify, so a bill-summary
  doc_id can carry spaces and `#`. Every consumer was traced (the webapp
  `encodeURIComponent`s, `sql_str` escapes the predicate) and **no functional
  break exists** — changing id minting has real blast radius against pinned eval
  chunk_ids, so it stays cosmetic.
- **Follow-up worth doing in Plan B:** narrow the `_DOC_TYPES` anti-drift
  assertion to a *materializable* subset of the registry (excluding
  `redirect`-marked rows). `baseline-book` and `approps-report` can never carry
  chunks — book ingest always stamps a book's children with per-section types —
  so the enum and the registry are answering two different questions that
  coincidentally share a key set today.

## ✅ Prose before the first heading — FIXED and the corpus REPAIRED (2026-08-12)

Merge `c1b43f9`. The corpus write is done: **3,434 documents updated,
`budget_chunks` 77,574 → 80,486 (+2,912), `fiscal_note_chunks` 13,278 → 14,161
(+883).** Snapshot taken before the write:
`data/insight-data/backups/lancedb-20260812T230906Z.zip`.

**Recovered chunks are APPENDED, so no existing `chunk_id` moved** — that is
what made this an INSERT of 3,795 rows rather than a rewrite of 77,574, and it
is why eval ground truth survived untouched. Verified against the live corpus
before the write (69,846 of 77,574 chunk_ids re-derived across 4,952 documents,
0 mismatches on id, text, section_path or provenance) and again per document
during it: **every document had to reproduce its existing chunk_ids
byte-identically before any new row was inserted for it. 0 documents failed
that gate, 0 were skipped.**

**Eval after the write is IDENTICAL to the same-machine control taken before
it** — recall@5 88.10%, @15 100%, @20 100%, refusal precision 60%
(`eval/results/2026-08-12T2318Z-24369d9.json`). 3,795 new chunks entered the
ranking pool and displaced nothing. Gate G1 passes.

`jlbc-baseline-fy2022-hla` now carries its agency description alongside its two
tables. Spot-checked directly rather than inferred.

**378 documents could not be repaired** — no retained `extractor-output/` on
this machine. They are the migration-era entries (the ones lacking
`ingested_at`). Re-running the same operation wherever their extractor output
lives would finish the job.

### 🔴 `agao-afr-fy2024` was DELIBERATELY EXCLUDED — this is a decision, not an oversight

The fix would have taken it from 20 chunks to 388, which reads like a repair of
the document recorded elsewhere in this file as "effectively EMPTY". **Reading
the recovered content shows it is not.** GAO tagged that edition's financial
statements as loose paragraphs rather than tables, so what gets recovered is
table rows stripped of their column headers — sometimes usable
(`FANTASY SPORTS CONTEST FUND … APPROPRIATED ACTIVITY ‐ 150,100.00`), sometimes
figures with nothing saying what they are (`‐ (2,600) 8,021,000 7,981,822`).

That is worse than empty. Empty is honest; unlabelled figures are **citable**,
and the citation linker matches a figure to a chunk — so a number could be
cited into meaningless context (Invariant 1). Destin's call: it stays at 20
chunks and waits for **Plan B's T7 fallback ladder to re-route it to MinerU**,
which reconstructs tables visually and is the designed fix for exactly this
shape.

**A numeric-density heuristic did NOT detect this** — those chunks are full of
agency and fund names, so they score "clean" at 1.6% junk while being flattened
table rows throughout. Reading eight random chunks did detect it. Do not build
a content-quality gate on character-class ratios.

### ✅ Plan B's floor calibration is UNBLOCKED

The distribution that produced a ~5% floor was contaminated by this bug. The
low band was one-page agency entries whose only prose was the dropped
description — `jlbc-baseline-fy2022-hla` measured 16.6% before and 74.2% after,
`jlbc-approps-fy2026-ico` 13.0% → 77.8%.

### ✅ The floor is now CALIBRATED against the repaired corpus (2026-08-12)

Full write-up:
[`docs/superpowers/investigations/2026-08-12-coverage-floor-calibration.md`](docs/superpowers/investigations/2026-08-12-coverage-floor-calibration.md).
All 7,434 documents scored, 0 unresolved. **The floor is 10%**, and the spec's
15–25% expectation was **too high** — T6 and Risks 1–2 are amended.

Median coverage 87.9%. Every floor from just above 2.0% to just below 17.1%
catches an identical set of **two** documents, so 10% is the plateau centre —
correct here because the metric degrades on both sides. **2 of 7,434 documents
(0.03%) would ever pay for a fallback**, which closes spec Risk 2.

Two findings that outlive the number:

- **The corpus has two chunk tables.** The first pass summed `budget_chunks`
  only, scored all 2,104 fiscal notes at 0.0%, and made **28.3% of the corpus
  read as broken**. Caught by reading the low scorers, not counting them.
- **🔴 The ratio detects catastrophic loss, not corruption.** It cannot see a
  document that produced the right *amount* of the *wrong* text. Passing the
  floor is not a certificate of health, and no analyst-facing copy may say it
  is.

### `jlbc-baseline-fy2013-s1` is FIXED — it is NOT a second re-route candidate

The claim below (that it is a genuine second FY2024-AFR-shape failure unaffected
by this fix) was **wrong**. The orphan repair fixed it: 8 → 16 chunks, coverage
**1.03% → 97.6%**, and chunks 0008–0015 carry ~14,140 characters of real
substantive prose. Its first 8 chunks are still garbled heading fragments
(`Federal 59 uirements`, `FY 20l3`) — a minor heading-extraction issue, not
data loss.

**`agao-afr-fy2024` is the only document Plan B's ladder must recover.** The
only other document below the floor is
`legislature-fiscal-note-fy2016-hb2003-27`, where **azleg.gov published a
literal test file** (`THIS IS A TEST`, 323 characters). No re-extraction will
improve it — it is the worked example for why T8 needs a human dismissal path.

<details><summary>The original finding, kept as the record of what was wrong</summary>

## 🔴 Prose before the first heading is DROPPED on the PDF path (2026-08-12)

Found while calibrating Plan B's coverage floor (spec T6).

`build_narrative_chunks` walks the document's **outline tree** and collects the
`Paragraph` blocks hanging off each node. A paragraph that appears **before the
first heading** belongs to no node, so nothing ever visits it and it is never
chunked. `builder.py` has a synthetic `preamble` section for the DOCX path;
**the PDF path has no equivalent.**

On a JLBC agency page the block sitting before the first heading is the
`AGENCY DESCRIPTION` paragraph — the text that answers *"what does this agency
do"*. Confirmed end to end on `jlbc-baseline-fy2022-hla`: present in the source
PDF, present and well-formed in MinerU's own output, absent from the chunks.
The reader parses 7 outline nodes for `jlbc-approps-fy2024-ind` and the
description paragraph is attached to none of them.

**Measured over 300 random per-agency documents** (MinerU paragraph blocks
parsed vs paragraph text reaching the outline):

| | |
|---|---|
| prose characters extracted | 1,988,434 |
| reaching the outline | 1,886,602 |
| **orphaned, never chunked** | **101,832 (5.1%)** |
| documents losing any prose | 170 of 300 (56.7%) |

For most documents this is one boilerplate paragraph among many sections and
costs little. **The subset where it matters is the short one-page agency entry
whose ONLY prose is that description** — it loses 100% of its narrative and
survives as a bare table. Those are exactly the documents that scored 12–20% on
the coverage measure.

### 🔴 This BLOCKS Plan B's floor calibration — do not set the floor first

T6 requires a corpus-wide coverage measurement before the floor is chosen. That
run is done (below) but it measured a corpus carrying this bug, so the low tail
is contaminated:

| corpus | min | p1 | median | max |
|---|---|---|---|---|
| budget (5,330 docs) | 1.03% | 23.01% | 78.02% | 286.31% |
| fiscal notes (2,103) | 52.63% | 80.59% | 98.10% | 103.38% |

A floor fitted to this distribution lands near **5%**, which would ratify the
bug as normal. **Fix the orphan bug, re-chunk, then re-measure.** Estimated
effect: `jlbc-baseline-fy2022-hla` moves from ~17% to ~72%, clearing the low
band entirely — after which the spec's original 15–25% expectation may well be
correct. **The repair does not need re-extraction**: `extractor-output/` is
retained (3.3 GB), so it is a re-chunk + re-embed. That still re-mints every
`chunk_id`, and `eval/refresh_chunk_ids.py` is deleted with nothing replacing
it — re-point eval ground truth as part of the work.

### Two genuinely broken documents, isolated by the same run

- **`agao-afr-fy2024`** — 1.97%, already recorded elsewhere in this file.
- **`jlbc-baseline-fy2013-s1`** — **1.03%, NEW.** 150 characters recovered from
  a 14,634-character source; all 8 chunks are corrupted heading fragments
  (`" Overview"`, `"Debt Rating"`, `" Federal 59 uirements"`). Same shape as the
  FY2024 AFR and previously unknown.

Controls behaved: the four sibling AGAO AFRs scored 278–286% against FY2024's
1.97%. **A ratio above 100% is normal and not a bug** — chunk text carries
table markup and repeated headers, so this is a proxy for extraction health,
never "fraction of text captured". The measure also catches only CATASTROPHIC
loss; a book whose extraction died halfway would score ~50% and pass any floor
in this range. State that as a non-goal rather than discovering it later.

### ⚠ Three wrong claims were made during this investigation — do not inherit them

Recorded because they are the kind of thing that gets copied forward:

1. **"The chunker throws away paragraphs."** False. 71.5% of the corpus is
   narrative chunks (55,464 vs 22,110 table); per-agency documents average 10.3
   narrative chunks, median 5. Narrative chunking works.
2. **"87% of agency pages are missing their prose."** False as stated. That
   probe tested for ONE paragraph and the result was generalised. Only **7.7%**
   of per-agency documents have zero narrative chunks.
3. **The first calibration run silently scored 378 of 7,434 documents** because
   `source_blob_path` is sharded (`pdfs/4d/4d2a….pdf`) and the resolver rebuilt
   it from the basename. It looked like a clean result. Always print the
   population a measurement actually covered.

</details>

## Consolidated eval pipeline — SHIPPED, merged to master (2026-08-18)

**Merged to master 2026-08-18** (branch `consolidated-eval-pipeline`, 30+ commits,
was 17). Full suite green on the merged result: **3265 pytest** (3 more than the
pre-merge 3259, incl. a new judge-resume test). Design:
`docs/superpowers/specs/2026-08-16-consolidated-eval-pipeline-design.md`;
plan: `docs/superpowers/plans/2026-08-16-consolidated-eval-pipeline.md`;
query inventory: `docs/superpowers/plans/2026-08-16-eval-query-inventory.md`.

**What it is.** Replaces the smoke/full/dr-probe organization of the Layer 2
agent-loop eval with one profile-driven pipeline:
- **Query sets** — each query tagged `set: quick | multi | deep | refusal`
  (the retired `subsets`/`--subset` mechanism is deleted).
- **Headline** — `tokens_to_accurate` / `turns_to_accurate` (cost of a
  *correct* answer), computed only over responses that pass all key facts
  and cite ≥1 verified source. **Wall-clock is not a metric** (dropped by
  Destin's call — network/machine-load dominated).
- **Four axes** — retrieval, agent efficiency, doc-type understanding
  (`document_correctness`, Multi set), plus citation/hygiene/refusal
  signals carried forward.
- **Tool-error ledger** — every failed retrieve/cite/argument logged with
  the turn it cost (feeds prompt/tool tuning).
- **Over-time archive** (`eval/results/over-time/`) — one metrics.jsonl row
  per run with comparability keys; trend lines split at each query-set or
  corpus change (never trended across incomparable runs).
- **Free verification script** `scripts/verify_agent_query.py` — checks
  every key fact's presence in the corpus (free, no OpenRouter).

**Query set state.** 53 queries after a findability pass:
- **quick 45 / deep 3 / refusal 5, multi 0.**
- **All 53 are solvable — 0 fact-presence misses** (every key fact exists
  in the corpus). The quick set was diversified (niche agencies, more
  years, harder shapes), then ~15 plausible-but-not-in-corpus anchors were
  re-pinned to real JLBC figures or removed. Some facts exist but are not
  in a single top-20 bare retrieve — that is retrieval effort, scored on
  the agent axis, not a query defect.

**Review status.** Final whole-branch review: **no Criticals**, only the
docs gap (now filled). 3259 pytest passing.

**Paid smoke run (2026-08-17/18).** 15 random quick queries ran through
the full orchestrator (`run_full_layer2 --sets quick --queries <15 ids>
--workers 4`) — live agent (z-ai/glm-5.2) → score → judge. Result:
**11/15 accurate (73.3%)**, key_fact_rate 0.83, cite pass 94.6%, holistic
3.4, chunk_relevance 0.78, **$0.44 total**. The 4 misses are instructive
(AHCCCS pin, cm-university not converging, cm-supplementals over-citing,
SOS fact-right-but-uncited — the honesty gate working). See the skills
run: `eval/results/agent/2026-08-17T2324Z-88f90b3/`.

**Report bundle.** A styled, navigable HTML report is auto-generated and
auto-opened at the end of every `run_full_layer2` run
(`eval/results/agent/<run>/report/index.html`): summary table with hover
tooltips + sort, per-query pages with the judge review and the
conversation rendered with the live app's chat classes. Regenerate:
`uv run python -m eval.report_bundle eval/results/agent/<run>`.

**2026-08-18 deepseek audit + improvements (all merged).** This was the
first serious measurement on the consolidated pipeline, and it found
three honest things worth recording because each changed the tooling:

1. **Provider errors must be excluded from model metrics.** An OpenRouter
   **403 key cap struck mid-run** and killed 10/45 deepseek queries — each
   wrote an `_error` frame and was mis-scored as a model failure (hu/rate
   read 0.229). Now `agent_scoring.py` classifies 403/rate-limit/5xx/network
   outages as `provider_errors` and excludes them from the accuracy
   denominator.
2. **The accurate bar was measuring the wrong citation path.** The harness
   consumes `[[cN]]` figure tags into VERIFIED figure annotations (the real
   citation chips), but `accurate` only counted `cite()`-tool calls — so a
   correct, auto-cited answer scored "0 citations." `accurate` now credits
   tag-linked figures. This alone moved deepseek from 8/45 → 20/35 and glm
   from 26/45 → 30/45.
3. **Prompt/harness guidance + judge resumability.** Added a "Conversation
   rhythm" section, a "MUST emit `[[tag]]`" rule with a worked example,
   glanceability guidance, and `cite_reminder`/`filter_hint` stamped onto
   every retrieve result. Three "this year" queries reworded to explicit
   "FY 2026" (policy: "this year" = FY2027). The judge now writes partial
   `judge.json` after every grade and resumes without re-paying on rerun.

**Headline result (clean rerun, all improvements).** Full 45-question
quick set with **deepseek-v4-flash-0731** → `run_dir
eval/results/agent/2026-08-18T0850Z-6a28d03/`:
**32/45 accurate (0.711)**, fact rate 0.785, cite pass 0.895, **$0.21**.
Same set with **glm-5.2** → 30/45 accurate (0.667), $2.20. **deepseek now
leads glm on accuracy at ~1/10 the cost** — the opposite of the pre-audit
read (0.229) and a vindication of the scoring + harness fixes. glm was
judged with glm; both judged by the same glm-5.2 judge.

**Open / NOT done**
- ⏸ **Multi set: DEFERRED (follow-up)** — 0 queries authored. Needs
  hand-pinned `correct_response_docs` and care given the findability
  lessons. When authored: `mt-` id prefix + `correct_response_docs` list +
  corpus/verify pass.
- ⏸ **Clean glm full-45 rerun on the *updated* query wording** (the glm
  30/45 above is on the pre-reword set; the deepseek 0.711 is on the
  reworded one — not quite the same population, so the head-to-head is
  directionally but not exactly apples-to-apples).
- ⏸ **~13 remaining non-accurate deepseek queries** in the 0850 report —
  the dominant residual failure is ambiguous "operating budget" targets
  (e.g. full-sources vs General Fund vs a specific line), i.e. query-spec
  ambiguity rather than retrieval/citation defects. Worth either tightening
  wording or adding domain guidance before the next baseline.
- ⏸ **The ~12 "reachability-not-in-one-bare-retrieve" facts** are fine
  (documented), but a handful of queries still carry plausible-by-etiquette
  anchors worth re-confirming before a full baseline is scored on them.
- ⏸ **Agent-built "findability" filters** — discussed, then NOT built: a
  cheap test showed naive year/doc-type filters change nothing for
  reachability, so the fancy machinery was dropped (see the section below
  for the honest reachability caveat).

## What's next

- **✅ CORPUS IDENTITY CONSISTENCY — BUILT, APPLIED AND MERGED 2026-08-16.**
  Titles naming a different agency 284 → **4**; duplicate titles 218 → **0**;
  doc_ids contradicting their source 22 → **0**; documents labelled with an
  agency they never mention 1,072 → **171**. Layer 1 eval unchanged through
  all four corpus passes. **Both implementation plans carry a DO-NOT-RE-RUN
  banner** — they applied corpus mutations and are design intent now, not
  work. Full record, including the two figures the audit got wrong and the
  open follow-ups, in the section below. **Only the browser walkthrough is
  outstanding.**
  **Repairing needs NO re-ingest — verified**, so do not scope this as a
  corpus rebuild.
- **Two corrections landed in this file on 2026-08-16 — both were claims
  that read as "handled" and were not.** *"Catalog debris removed"* was
  query-side only, and the corpus is still stamped from the poisoned
  canonical name; *"Six already-ingested documents would mint a different
  id"* is **22**, because the original audit only checked FY2026/FY2027.
  Both are marked in place next to the original text. **Verify a
  "fixed" claim against the data before building on it** — the same lesson
  this file already records for the ingest-lock entry.
- **FY2027 Appropriations Report ingested and verified 2026-08-16.** 140/140
  live, 0 failures, 2,336 passages, 0 duplicate ids corpus-wide, 4.61
  chunks/page (healthy band 3.24–5.24). Corpus now **83,016 budget chunks /
  7,566 documents**. Its titles are wrong — that is the identity defect, not
  an ingest failure. It is the **first edition ever ingested through the
  probe ladder** rather than the catalog, which is exactly why it exposed it.
- **⚠ A CORPUS CHANGE READS EXACTLY LIKE A CODE REGRESSION — demonstrated
  2026-08-16.** The Layer 1 eval fell recall@5 88.10% → **85.71%** and
  recall@15 100% → 97.62% after that ingest. **Zero code changed.** Proven by
  a control on the SAME branch and SAME 47-query set two hours earlier
  (`eval/results/2026-08-16T0913Z-4157e80` vs `…T1122Z-9c9f8d6`): six queries
  moved rank, every one of them with newly-ingested FY2027 chunks in its top
  5, and **not one changed status**. Gate G1 passes. Do not read that number
  as a regression, and **do not diff a post-ingest eval against a
  pre-ingest one without saying so.**
- **⚠ THIS DEV MACHINE HAS A WORKING OPENROUTER KEY (confirmed 2026-08-11).**
  Several sections below say a task "needs a machine with an OpenRouter key"
  or that `ai_available` reports *"no API key configured"* here. **That is
  stale.** `<data_dir>/settings.json` has carried a live `openrouter` provider
  key since 2026-08-09 (Standard `z-ai/glm-5.2`, Deep Research
  `moonshotai/kimi-k3`), and `GET /api/ai/status` returns `available: true`.
  A session on 2026-08-11 wrote "no key on this machine" into STATUS.md on the
  strength of one bad probe and nearly deferred a whole browser pass to
  another machine over it — **check `/api/ai/status`, not a half-remembered
  note.** What is genuinely still true of the paid work (the 31-query Layer 2
  baseline, the glm-vs-deepseek head-to-head) is that **it spends Destin's
  real money**, so it needs his go-ahead — not that it is technically blocked.
- **Corpus navigation — SHIPPED 2026-08-12, BOTH GATES PASSED** (section
  below). Corpus map in the prompt, `spread` retrieval, `year_coverage`, the
  inferred-filter echo. `key_fact_rate` **0.463 → 0.685** against a real
  same-machine control, every citation metric up, input tokens down 41%.
  **What is left: the full 31-query run + judge (~$1.50–3), which no
  committed run currently provides for the CURRENT query set** — the set
  changed in `0e32df3` after every existing baseline, so any older
  comparison measures the question edits. Also unwatched in a browser, and
  the `by: "doc_id"` spread axis has never been exercised live.
- **Attested citation linking — SHIPPED AND VERIFIED LIVE 2026-08-11**
  (section below). The model tags each figure with the passage it came from
  and the system verifies the tag; document-authority ranking is deleted.
  False-link rate down **13–15×**, and a captured live turn reached **100%
  coverage with 44 figures linked by tag** — marker compliance, the design's
  one open risk, is closed. Browser testing found **six defects that all the
  offline measurement missed**; every one is fixed and pinned. Do not read
  the ~55% offline coverage as a regression — it is the UNTAGGED floor,
  measured on transcripts that predate tagging.
  **Still to do:** the 31-query Layer 2 baseline + judge
  ([`PROMPT-attested-citation-baseline.md`](PROMPT-attested-citation-baseline.md)),
  and two non-citation findings — a mislabelled source chunk
  (`jlbc-approps-fy2026-bh26-0003`) and the model narrating tool mechanics.
- **The post-backfill retrieval regression — the free half DONE 2026-08-03**
  (`PROMPT-retrieval-accuracy-regression.md`). The `historical` agent-eval
  queries were RE-AUTHORED against the genuinely old books (see the section
  below) — the one piece of that handoff that needs no OpenRouter key. The
  keyed half still stands: finish the interrupted glm-vs-deepseek head-to-head
  (deepseek run is 25/31 on a keyed machine) and, per the handoff, only then
  make the retrieval change (year-inference-as-default-filter is the highest-
  leverage target, but it must be validated with a Layer 2 run — never Layer 1
  numbers alone). **Nothing on the retrieval path was changed here.**
- **Eval speed + the defend loop SHIPPED 2026-08-03 (no eval numbers changed).**
  `run_agent_eval --workers N`, `judge_agent_run --workers N`, and a new
  one-shot `eval.run_full_layer2` (run → score → judge, one pinned run dir)
  all parallelize the paid OpenRouter calls; `eval.defend_agent_run` replays
  a weakly-scored transcript through a fresh session so the model can defend
  or revise its answer against the evaluator's feedback — useful for spotting
  faulty evals. Thread-based (not process): the paid work is I/O, and the two
  ONNX models are already shared singletons. Defaults stay serial (1 worker).
  No Layer 1 or Layer 2 numbers changed.
- ~~**🔵 RUNNING NOW — S20 backfill on the Z13**~~ **DONE 2026-08-02** — every
  ingestable JLBC book edition is in the corpus (38 editions, 7 failures all
  azjlbc.gov 404s), and Phase D's recency re-calibration landed the same day.
  See the "Volume ingest / S20 backfill" row and the Plan 7 section. The stale
  "RUNNING NOW" text below is kept only because the rest of the bullet records
  the phase structure; **it is not live work.**
  Phase A (parity gate) and Phase B (recency machinery) are DONE and merged.
  Phase C (the backfill itself) is ~65% through the fiscal notes with the
  38 book editions still to come; ~6 h remaining at the current rate.
  Phase D (recency + refusal calibration) is BLOCKED until the corpus is
  complete. Nothing else in this list touches the ingest path, so all of it
  is safe to work in parallel.
- **Parallel work available NOW** (safe alongside the running backfill — all
  disjoint from the ingest path). Handoff prompts at the repo root:
  ~~[`PROMPT-parallel-ai-hardening.md`](PROMPT-parallel-ai-hardening.md)~~
  **DONE 2026-07-31** — S22 + S23 shipped, merge `5e1ae3b`; see the section
  below,
  [`PROMPT-parallel-ingest-defects.md`](PROMPT-parallel-ingest-defects.md) (the
  two 🔴 handoff-blocking defects; develop + merge, do NOT restart the running
  server), and
  ~~[`PROMPT-parallel-write-plan5.md`](PROMPT-parallel-write-plan5.md)~~
  **DONE 2026-07-31** — the plan is written (see the next bullet).
- **Plan 5 — Tracks 1–4 SHIPPED; Tracks 5–6 remain (20 of 27 tasks).**
  What is left: **Track 5, the Administrator Handbook** (tasks 21–23,
  [`PROMPT-plan5-session-c.md`](PROMPT-plan5-session-c.md) — Task 21's memo
  renderer can start now; 22–23 describe admin screens that now exist, so
  they are unblocked) and **Track 6, gates G2/G3** (24–27), which need a
  finished bundle and a finished handbook. Track 4's handoff
  (`PROMPT-plan5-track4-cleanup.md`) is retired — do not execute.
  The original plan, for reference:
  [`docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md`](docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md).
  27 tasks in six tracks: admin/settings UI (S11/S13/S15/S16/S17/S19),
  resilience (S18 repair flow + launch health ladder + a `RESET-ADMIN.txt`
  break-glass path out of an admin lockout), packaging + launcher
  (S7/S8), legacy deletion (`web/`, `mcp-server/`, `db/`, dead `retrieval/`
  modules), the **Administrator Handbook** (JLBC-memo-styled Word doc built
  from `docs/HANDBOOK.md`, shipped in-app AND beside the corpus on the share —
  covers operation, the cost model, why each AI tier got its model,
  confidentiality, and how a non-technical successor extends the app with AI
  help), and gates G2/G3. Tracks 1–2, Track 3 and Track 5's Task 20 can run in
  three parallel sessions; Track 4 must follow 1–2; the handbook's writing
  tasks follow the admin UI; Track 6 needs the finished corpus.
  **Handoff prompts, one per parallel session:**
  [`PROMPT-plan5-session-a.md`](PROMPT-plan5-session-a.md) (tasks 1–13, admin +
  resilience), [`PROMPT-plan5-session-b.md`](PROMPT-plan5-session-b.md) (tasks
  14–17, packaging — **stops after the Task 14 measurement for a shape
  decision**), [`PROMPT-plan5-session-c.md`](PROMPT-plan5-session-c.md) (task
  21 now, the memo renderer; tasks 22–23 wait for Session A).
  **Task 13 (bundle-size measurement) is the highest-risk item and gates the
  rest of packaging** — it also carries the split-distribution fallback if a
  MinerU-inclusive bundle proves impractical. The AI-Mode hardening that used
  to sit here (S22 + S23) shipped 2026-07-31 — see the section below.
- ~~**Z13 backfill + recency calibration (S20/S21)**~~ **DONE 2026-08-02** —
  historical-year corpus backfill and recency-ranking calibration on the Z13
  Linux machine. Runbook:
  [`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md) (~~the only active
  handoff~~ **COMPLETE — do not execute**). Recency plan:
  [`docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md`](docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md).
- **Layer 2 agent-loop eval — BUILT, first smoke baseline COMMITTED
  2026-08-01** (`eval/results/agent/2026-08-01T1157Z-25399b1/`, 11 queries,
  $0.43, 0 errors, model `z-ai/glm-5.2`). The full 31-query baseline has NOT
  been run — do that before trusting a `compare_agent_runs.py` delta on
  anything outside the smoke set. What the first baseline says, and the four
  improvement targets it hands us, are in the section below.

---

## Corpus navigation — SHIPPED, both gates passed (2026-08-12)

Spec: `docs/superpowers/specs/2026-08-12-corpus-navigation-design.md`
(N1–N7, N11; N8/`expand` removed before implementation). Plan:
`docs/superpowers/plans/2026-08-12-corpus-navigation.md` (11 tasks, all
done). Merged `2dc295f`.

**The model can now see the corpus's shape and search it by group.** Three
things shipped, all additive — the default `retrieve()` path is structurally
untouched:

1. **A corpus inventory table in the system prompt (N1–N3).**
   `harness/corpus_map.py` builds it from the `documents.json` sidecar and
   `session.py` snapshots it ONCE per conversation. Family comes from
   `source_url` via the rule hoisted to `store/book_family.py`, never from
   doc_id — 21 doc_ids encode the wrong family, and a map built from them
   would claim editions that do not exist while the guidance line told the
   model to assert it.
2. **`spread` on retrieve() (N4–N6).** One query, searched separately inside
   each named fiscal year or document, ONE rerank batch, agency penalty
   before the per-group trim, recency never applied. The structural fix for
   edition monoculture: FY2026 cannot be crowded out of the pool when FY2026
   IS its own pool.
3. **`year_coverage` + the inferred-filter echo (N7, N11).** The candidate
   distribution by fiscal year counted over the legs (what the pool cap hid),
   plus `inferred_doc_types`, `dropped_filters` and `preferred_agencies` —
   which the tool layer has always computed and always dropped.

### G-N1 — Layer 1 unchanged, proven against a same-hour control

Not a remembered baseline: master's own run landed at **23:18Z** and this
branch's at **23:22Z**, same machine, same corpus, four minutes apart.

| | control (23:18Z, 24369d9) | shipped (23:22Z, 4f991fa) |
|---|---|---|
| recall@5 / @15 / @20 | 88% / 100% / 100% | **88% / 100% / 100%** |
| refusal precision | 60% | **60%** |
| fallback rate | 31% | **31%** |
| latency p95 | 857 ms | **856 ms** |

Identical on every metric, p95 within one millisecond.

### G-N2 — `key_fact_rate` 0.463 → 0.685 against a real control

**The 2026-08-01/02/03 runs are NOT comparable and `compare_agent_runs.py`
correctly refuses them**: `eval/agent_queries.yaml` changed in `0e32df3`,
after every committed run, so no baseline shares the current query set. A
control was run instead on the merge's first parent (`52e74d9`), same 11
smoke queries (`queries_sha256` verified identical BEFORE spending), same
machine, same models.

| metric | control | shipped | |
|---|---|---|---|
| **`key_fact_rate_mean`** | 0.463 | **0.685** | **+48% relative** |
| `cite_pass_rate` | 0.898 | **1.00** | ▲ |
| `first_try_cite_rate` | 0.915 | **1.00** | ▲ |
| `retries_per_citation` | 0.043 | **0.00** | ▲ |
| `tag_accuracy_mean` | 0.901 | **0.944** | ▲ |
| `input_tokens_mean` | 149k | **88k** | −41% |
| `steps_mean` | 5.27 | **3.18** | ▲ |
| `retrieve_calls_mean` | 3.45 | **2.64** | ▲ |
| `cost_mean_usd` | $0.071 | **$0.032** | ▲ |
| `wall_p95_ms` | 220s | **147s** | ▲ |
| `false_refusals` | 2 | **1** | ▲ |

All three G-N2 clauses pass: key_fact_rate not worse (much better), no
citation-metric regression (all four improved), input tokens well inside the
±15% allowance in the good direction.

**The per-query attribution is unusually clean.** `spread` was called on 2 of
11 queries with ZERO argument errors, and **both went 0.0 → 0.667**
(`an-ahcccs-gf-drivers`, `cm-des-gf-growth`). `hs-arra-k12-stabilization-2010`
— the FY2010 question the map exists for — went **0.0 → 1.0**. Neither of the
two regressions (`cm-basic-aid-3yr` 0.667→0.333, `lk-dps-operating-fy2026`
0.5→0) used spread at all.

### 🟡 Watch, not dismissed

- **`figure_coverage_mean` 0.953 → 0.864 and `unverified_rate` 0.047 →
  0.136.** More figures unlinked. Both moved the wrong way and neither is
  explained yet.
- **`narration_hit_queries` 1 → 2** — one more query leaked tool mechanics,
  the known prompt-hygiene gap.
- **`cached_tokens_mean` 119k → 64k** is arithmetic, not a cache defect: the
  cache RATE fell 80% → 72% because the turn is three steps instead of five,
  so the always-uncached first step is a larger share of a smaller total.
- **n=11, single runs.** `compare_agent_runs.py` prints the stochasticity
  warning itself. These are flags for the full run, not conclusions.

### Still outstanding

- **The full 31-query Layer 2 run + judge** (historical — use today's
  `--sets quick,multi,deep,refusal`; the set is now 45 quick / 3 deep / 5
  refusal, not 31, and `--subset` is retired). It would establish the
  canonical baseline for the current query set — which, per the `0e32df3`
  finding above, **no committed run holds today**, for this work or any
  other.
- **Nobody has watched a spread answer render in a browser.** The chunks mint
  aliases and tag normally (pinned by test, and `tag_accuracy` rose), but the
  per-chunk `group` field has never been seen on screen.
- **The doc_id spread axis is untested live.** Every spread call the model
  made was `by: "fiscal_year"`.

### What the plan's own code sketches got wrong

Recorded because the plan is explicit that its code blocks are sketches to
run and correct, and this run is more evidence for that rule:

- `_session(system_prompt=None, **over)` was said to override — in Python a
  duplicate keyword is a `TypeError`, not an override. The helper needed a
  named parameter.
- `FakeEmbedder.calls` is a LIST, so the sketched `embedder.calls == 1` could
  never pass.
- `_chunk()` in `tests/test_pipeline.py` takes no `fiscal_year`; the sketch's
  `type(c)(**c.__dict__)` construction is `dataclasses.replace`.
- A JSON example in the prompt ending `}}` tripped the template guard that
  forbids a surviving `}}` — the guard was right and the example was
  reformatted.
- The spread tests' first draft used `"ahcccs"` as the neutral query and every
  score came back 2.0 lower: `MATCH_PENALTY` firing on a real agency acronym,
  working exactly as designed.

Also: `git mv`-ing `app/book_sections.py` broke
`test_every_first_party_import_resolves`, because `source_files()` is
`git ls-files` and the new shim was untracked. The guard is doing its job —
stage the file.

## JLBC memo formatting for generated reports — code complete (2026-08-13)

Spec: `docs/superpowers/specs/2026-08-12-jlbc-memo-formatting-design.md` (M1–M12).
Plan: `docs/superpowers/plans/2026-08-12-jlbc-memo-formatting.md` (8 tasks, two
parallel tracks). Reference fixture:
`samples/raw-docx/jlbc-staff-memorandum-style-reference.docx` — the real FY 2027
Appropriations Report Round 1 instructions memo Destin supplied.

**AI Mode's `create_document` produced a generic Office document** — stock
`Title`/`Heading N`/`List Bullet`, no page setup — so an analyst who wanted to
send it reformatted it by hand first. It now renders as a JLBC memo.

A new top-level **`memo/`** package renders Markdown into a styled Document:
letterhead (`Joint Legislative Budget Committee` / **`Research Memorandum`**),
the address block, a 2.25pt rule, a borderless `DATE / TO / FROM / SUBJECT`
block, then the body at Calibri 10.5pt with `Header`-styled section headings and
0.1875″ bullets. Every page carries `Generated with JLBC Agentic Search` in the
footer. The model's `title` becomes the **SUBJECT** line — there is no separate
title line, because the reference has none and `Title` is spent on the masthead.

Gates: **pytest 2592 / 5 skipped** (the documented ONNX skips), **vitest 771 /
74 files**, `tsc -b` exit 0, `npm run build` clean. **No eval run** — the
system-prompt edit is confined to the `create_document` section and
`eval/run_eval.py` calls `retrieve()` directly, so it cannot measure it. Same
call as S22/S23; confirmed with Destin.

### Deliberate deviations, both recorded at the code

- **`Research Memorandum`, not `Staff Memorandum`.** The letterhead is carried
  verbatim because the analyst edits and sends the result as their own work, and
  a document needing its letterhead pasted in has saved them nothing. But a
  Staff Memorandum is a specific JLBC work product with specific authorship, and
  a machine-drafted document must not claim to be one.
- **Name resolution is override → Windows → username, REVERSING spec M5.** An
  override that loses to auto-detection cannot correct a *wrong* AD name, and a
  wrong name (`JARRETTD`, an un-updated maiden name) is likelier than a missing
  one. The spec's intent — nobody types this if Windows knows it — is
  unaffected, because the override is empty until somebody sets it.

### 🔴 Nine defects in the PLAN's code, and two were tests that proved nothing

The plan's prose reasoning held up under execution. **Its code blocks did not** —
nine defects, every one in a code block, found by agents running the code rather
than transcribing it. The two worth remembering:

1. **A width assertion that passes on a broken table.** The plan checked
   `columns[].width`, which reads correctly *even when the cells are wrong*.
   Creating the memo block's rows up front yields cell widths of 2743200 EMU and
   wrapping labels while the column assertion stays green. `tblLayout` — which
   the plan blamed — changes nothing observable; it is kept only because the
   reference carries it and it governs Word's RENDER-time behaviour. The
   replacement checks every cell and was verified red first.
2. **`test_the_memo_block_labels_are_in_order_and_not_bold` does NOT guard the
   bold-on-runs rule**, though it looks like it does. Proven by mutation: move
   bold from the runs to the `Header` style and that test stays green while the
   labels render bold in Word, because run-level bold reads `None` when
   inheritance supplies it. **Only
   `test_bold_is_never_put_on_the_header_style_itself` catches it.** Do not
   delete that test believing the other one covers it.

Also: `create_app` takes `provider=`, not `search_provider=` (the wrong kwarg
makes a red step red for the WRONG reason); `SENDER_SUFFIX.lstrip(", ")` yields
`"via JLBC Agentic Search"` because `lstrip` takes a character set; adding
`display_name` "beside `user`" in `HarnessSession.__init__` would have silently
rebound `settings`/`executor`/`transport` at positional call sites (it is
keyword-only); and the route's `user=current_user()` at the `session_factory`
**seam** is not the constructor — editing it would have broken ~25 fake
factories.

### Invariant 7 held, structurally

`harness/documents.py`'s import allowlist gained **exactly one** entry, `memo`,
and that is only safe because `memo` carries its own allowlist test — so the
guarantee stays structural and becomes transitive. `harness/tools.py`'s
allowlist is **unchanged**: it may not import `app.*`, so the analyst's name is
resolved in `app/routes/conversations.py` and injected as a finished string. The
module that writes files has no knowledge of identity sources; the module that
knows identity writes no files.

### 🔴 It passed every test and still looked wrong — five differences, found by LOOKING

Destin opened the first version and said "that's not the same." He was right.
Both documents were then rendered to images and compared, which is what should
have happened before handing it over:

| | The real memo | First version |
|---|---|---|
| Masthead colour | black | **accent blue** (Word's stock `Title` style) |
| Section headings | inside a **bordered box** | plain bold text |
| Spacing | tight | **roughly double** everywhere |
| Address lines | *italic* | not italic |
| JLBC seal | on page 1 | missing |

**The spacing had one cause with a compounding effect.** python-docx's blank
template sets `w:spacing w:after="200" w:line="276"` in its document defaults —
10pt after every paragraph, 1.15 line spacing. The reference sets neither.
Because this memo builds its vertical rhythm out of EMPTY PARAGRAPHS (recorded
in the spec, and true), every deliberate gap came out doubled and the
DATE/TO/FROM/SUBJECT block sprawled over half a page. Zeroing it then collapsed
the memo block's spacer rows to nothing, so row height and inter-block spacing
both had to be stated explicitly rather than inherited.

**The boxed heading is the instructive one.** The reference's section headings
use the built-in `Header` paragraph style — noted correctly in the spec, and odd
enough to be memorable. But the BOX is direct paragraph formatting on each
heading, not part of the style, so copying the style name reproduced the oddity
while missing the thing that makes a JLBC heading recognisable.
`memo.style.box_paragraph()` applies it per paragraph, deliberately: the memo
block's labels share that style and must stay unboxed, exactly as the reference
does it.

**The seal is the reference's own `word/media/image1.png`**, vendored to
`memo/assets/jlbc-logo.png` and placed at its recorded size (1195465 x 828675
EMU) in a FIRST-PAGE footer, which is where JLBC puts it — the reference has no
default footer at all. The "Generated with JLBC Agentic Search" line rides in
both footers, because a disclosure that appears only on page 1 is missing from
every page after it.

### The lesson, which this repo has now learned three times

**All 30 assertions were green while the page was plainly wrong.** They measured
margins to the EMU, font sizes and column widths — properties, not appearance.
`scripts/render_memo_sample.py` now renders a sample and a PNG of page 1
precisely so the next person LOOKS instead of inferring. Run it after any change
to `memo/`.

### ⏸ Still worth a human eye

The comparison above used rendered images at 80 dpi via LibreOffice, which is
not Word. Opening `/tmp/memo-sample.docx` beside `/tmp/memo-reference.docx` in
real Word on a JLBC machine is still the final check — particularly the seal's
placement and the boxed headings, which are what LibreOffice is most likely to
draw differently.

---

## Document guide — SHIPPED, unwitnessed (2026-08-13)

Spec: `docs/superpowers/specs/2026-08-13-document-guide-design.md` (G1–G11).
Plan: `docs/superpowers/plans/2026-08-13-document-guide.md` (3 tasks, **executed
— do not re-run**; its example code carried five defects, see below). Merged
`f91b68f`, commits `ded4242` / `3eb3b2c` / `923cc43`. Builds on the memo
formatting section above: that made a generated document LOOK like JLBC's; this
is about what it SAYS and how it is shaped.

Gates on the merged tree: pytest 2824 / 5 skipped, vitest 913 across 83 files,
`tsc -b` 0, `npm run build` clean. **No eval was run** — see the reason below.

**A sixth tool, `document_guide(report_type)`.** It returns JLBC house style
(numbers, voice, forbidden phrases, length, formatting) plus one of three
report shapes — `research-memo` (the default), `comparison`, `agency-profile`.
Guidance lives as Markdown under `harness/guides/`, loaded by
`harness/guides.py`, so a non-technical successor edits house rules in a text
file — the same reasoning that makes `harness/system-prompt.md` a file.

**A tool rather than more system prompt, for a measured reason.** The prompt is
the cached prefix every conversation pays for on every step (S22). Only the
tool's ~90-word schema joins it; the ~700-word guide is fetched on the small
minority of turns that write a document.

Gates on the branch before merge: pytest 2727 / 5 skipped (the documented ONNX
skips), vitest 842 / 79 files. The merged-tree numbers at the top of this
section are the ones that count — master moved 46 commits during execution and
was re-synced and re-gated twice before the push.

### 🔴 It is ADVISORY and UNENFORCED

Nothing validates the model's output against the guide, and **no code rewrites
the model's numbers** (spec G6). The tool hands over advice; the model writes
what it writes. That is deliberate — a server-side rounding pass would be
editing figures the analyst is about to send under their own name — but it
means the only evidence the guidance works is reading a real document.

### 🔴 The answer-versus-document number split, and why losing it would be silent

Rounding (`$6.0 million`) is scoped to the **document body** and explicitly
forbidden in the **chat answer**, where figures keep source precision
(`$6,043,200`). Documents carry no citation chips; chat answers do, and
`citation/matching.py` refuses an untagged figure below **4 written significant
digits**. A bare "round your numbers" would be applied to answers too.

**If that split were ever dropped from the guide, untagged citation coverage
would fall with no error anywhere** — no test fails, no log line, nothing
visible until someone re-measures the false-link/coverage numbers. It is
therefore stated in TWO places and guarded in both: in `harness/guides/shared.md`
(`test_the_answer_versus_document_number_split_is_stated`) and repeated inline
in the `create_document` section of the system prompt
(`test_the_prompt_repeats_the_source_precision_rule_for_answers`, run against
both corpora). The prompt copy is not redundancy: the guide is read only on
turns that write a document, and the rule applies to every turn.

The second content rule with its own guard is **"use bullets, never numbered
lists"** — `memo/markdown.py` renders `1)` as an unstyled plain paragraph, so
borrowing the fiscal-note skill's numbered convention produces visibly broken
documents.

### No eval was run, and that is the right call

The prompt edit is confined to the `create_document` section, which
`eval/run_eval.py` cannot measure — it calls `retrieve()` directly and never
reads the system prompt. Same reasoning as S22/S23 and the memo work. Nothing
under `retrieval/`, `ingest/`, `chunking/` or `citation/` was touched.

### Guide length — judged, not just counted

Read as the model would and trimmed: research-memo **672 → 641** words,
comparison **765 → 729**, agency-profile **702 → 671**. The three type files
are already tight (93 / 181 / 123 words); the 548-word shared block is the bulk
of every total. What came out was redundancy only — a paragraph restating "Name
your sources" (its one unique clause folded into that bullet instead), and two
compressions. **Comparison deliberately stays over the plan's ~700 guideline.**
Its remaining three table rules each prevent a distinct concrete defect —
building a total by summing rows, adding a derived percentage-share column, and
a one-row "comparison" — and cutting to hit the number would mean deleting a
rule. 729 vs 700 is not a difference the model can feel.

### 🔴 Five defects in the PLAN's code, and two were tests that proved nothing

Same shape as the memo work, and the third time this repo has recorded it: the
plan's **prose reasoning held**; its **example code did not**. Every defect was
in a code block, found by running it rather than transcribing it.

1. **The bullets guard was BACKWARDS — it passed precisely when the rule was
   deleted.** The plan asserted `"numbered list" not in text.lower()`, which is
   unsatisfiable beside the rule it protects ("Use bullets, never numbered
   lists"): it forbids the *phrase*, not the practice. Proven by mutation —
   removing the rule from `shared.md` turned it green. It now asserts the
   prohibition is **present**.
2. **The discoverability test could not see the system prompt at all.** The
   plan's only pointer test checked the `create_document` tool description.
   The prompt paragraph is what actually drives the behaviour, and deleting it
   entirely left the plan's test green. Two tests now cover it, both run
   against both corpora, and a test asserting only the tool-list line would
   still not do — a bare name in a list is not an instruction.
3. **A content guard that never matched.** The plan matched the literal
   `"as the source writes"`, which the guide wraps between "the source" and
   "writes them". All content assertions now normalize whitespace, so
   reflowing a Markdown paragraph cannot break a guard.
4. **`guides._read`'s docstring claimed the suite catches a missing guide
   file. It did not** — a missing *type* file still returns the shared block
   and reads as non-empty. `test_every_guide_file_is_present_on_disk` checks
   the disk and makes the claim true.
5. **The plan's edit anchor did not exist.** It said to add the pointer after
   `"...link the analyst can click."`; the description actually ends "Returns
   a download token the interface turns into a link". Appending blindly would
   have buried the pointer after the return-value sentence.

### The webapp tool card had no label

Found by Task 2, fixed here. `webapp/src/chat/tool-display.ts` had no
`document_guide` case, so the chat rendered a raw row reading `document_guide`
with its argument beside it while every sibling tool has plain English. It now
reads **"Check style guide"**, summarised by the report type the model asked
for (null when it asked for none — printing `research-memo` there would show a
choice the model never made). A new spec asserts the whole registered tool set
never renders a raw snake_case name, so the *next* tool added to
`harness/tools.py` fails there rather than in front of an analyst. Both cases
verified by in-place mutation. The expanded body and the card icon still take
their generic fallbacks, which degrade legibly (collapsed raw JSON, neutral
square) — worth a pass if anyone touches `tool-views/` next.

### Packaging needs nothing

`packaging/build_bundle.py` selects app files via `git ls-files`, so
`harness/guides/*.md` ship in the Windows bundle automatically. Verified in
Task 1, not assumed.

### ⏸ NOBODY HAS WATCHED A REAL DOCUMENT PRODUCED UNDER IT

Every check above is tests and content. **No model has been given this
guidance and asked to write a memo** — that needs a machine with an OpenRouter
key. The open questions a live run answers: whether the model calls the tool at
all without enforcement, whether it keeps source precision in the answer while
rounding in the document, and whether the three shapes produce documents an
analyst would send. Until then the feature is unmeasured in the only way that
counts.

---


## Budget Documents — highlighting + book sections — SHIPPED (2026-08-11)

Spec: `docs/superpowers/specs/2026-08-11-budget-docs-highlighting-and-book-sections-design.md`
(H1–H11, B1–B8). Plan:
`docs/superpowers/plans/2026-08-11-budget-docs-highlighting-and-book-sections.md`
(10 tasks). Merged `e6e0e14`. Resolves both issues in
`docs/superpowers/handoffs/2026-08-11-highlighting-and-raw-doc-types.md`.

**Two defects, both found by opening the running app after 2,999 tests passed.**

| | before | after |
|---|---|---|
| cards showing any mark | **0 / 200 (0.0%)** | **193 / 200 (96.5%)** |
| documents under raw machine slugs | 647 | **0** |
| mis-minted doc_ids resolved correctly | — | **21 / 21** |
| family-filter leakage | up to 269 docs | **0** |

Gates on the merged tree: pytest 2392 / 5 skipped, vitest 723, `tsc -b` 0,
eval recall@5 88.10% · @15 100% · @20 100% · refusal 60% · p95 752 ms —
identical to baseline, G1 passes.

### Highlighting: the matcher was the whole story, and the obvious snippet fix was WRONG

`highlight()` searched the snippet for the **entire query as one literal
substring**, so a mark appeared only when every word of the question appeared
consecutively and in order. Measured against the live corpus: **0 of 200
cards produced a single `<mark>`.** Now: every typed word marks on word
boundaries, **no vocabulary list of any kind**.

Four candidate rules were measured over 240 cards and **all four leave the
blank rate at 2.9%** — dropping function words is cosmetic, and a `length >= 4`
rule silently loses `aid` (basic state aid) and `des`. Word boundaries are what
actually matters: substring matching runs 8.3 marks per card peaking at 31.

**🔴 The match-centred preview window was measured and REJECTED.** It scores
higher on terms-visible and reads worse: JLBC front-loads these documents
(heading, then "The Baseline includes $X for Y", then background), so the
median first query-word match sits at **character 5** and the leading text IS
the summary. One observed case shifted ten characters to gain one term and
chopped "Enrollment Changes" into " Changes". It ships as a **fallback** for
the 3.5% of cards whose leading text holds no typed word. **Do not re-tune this
into the default** — the 32%-of-cards figure that argues for it counts marks,
not usefulness.

**Also dead, and instructively:** "only mark terms that are rare across the
results" collapses to 0.4 marks and 70% blank, because it drops `ahcccs`,
`child`, `subsidy` — the words that made the passages rank. Retrieval has
already filtered to passages sharing the topic, so within a result set the most
relevant terms are the most common. **Any "let the data decide which words
matter" scheme fails for this reason**, including deriving matched terms from
BM25.

### Book sections: the parent comes from `source_url`, never the doc_id

`bd`, `bh` and `s` are **JLBC's own printed page-number prefixes** (BD-10,
BH-11, S-1), not document types — every one of the 647 is a chapter of a book
already on the page. `ingest/lance_writer.py` already said so in a comment.

**🔴 The doc_id parses for all 647 and is WRONG for 21** — Baseline sections
minted with an approps doc_id, the `make_doc_id` collision class recorded
elsewhere in this file. `source_url` is the only independent evidence: 647/647
parse, **zero** disagree with the document's own title. Split: Appropriations
Report 389 / Baseline 258. **The 21 doc_ids are read around, not repaired** —
re-minting re-points chunk_ids and eval ground truth.

`detailed-list-pdf` and `topic-pdf` occur under **both** books, so a `doc_type`
filter cannot express "Baseline sections" and would leak up to 269 documents.
`app/search_provider.py` filters exactly, in `app/` — no eval gate, no ranking
change. Measured post-filter yield is **0 of 20 in the worst case**, so a
family filter can legitimately return a short or empty page; the page's
existing "with those filters" copy names the cause.

A book's tray shows **two groups, summary sections above agency pages** — but
only when both exist. Most families (AFR, Executive Budget, Budget Bill) have
no sections at all, and a lone "Agency pages" label restates what the reader
can already see.

### 🔴 The suites were necessary and nowhere near sufficient

**17 defects surfaced during execution. None was caught by any test suite** —
including **five tests that passed whether or not the feature worked**: an
assertion whose `getByText` regex could never match across a `<mark>` boundary
(so it passed on broken truncation), a regression test that passed identically
with and without the guard it existed to pin, and one that would have stayed
green if its feature were deleted outright. Each was caught only by tracing
what the test would do against the **pre-change** code.

The pattern is worth keeping: the plan's **prose reasoning** held up under
measurement, while its **example code** — written out in full and never run —
produced a formula that divides by zero, a `frozenset` membership test that
raises on a list, snapping arithmetic wrong in both directions, a dependency
this repo does not have, and an unsatisfiable assertion.

### ⏸ OUTSTANDING — nobody has looked at the page

Every check above is data and logic. **The rendering is unverified**, and both
original defects shipped green under 2,999 passing tests. Task 10 Steps 4–5 of
the plan carry the specific checks: search `how much did child care subsidy
cost` (marking, expand-in-place, no marks on a nonsense query), then open a
Baseline year card (two tray groups), tick the Baseline type filter and confirm
no Appropriations Report section appears, and confirm `capital outlay` still
finds its sections in the filter box.

---

## ✅ The `historical` agent-eval queries re-authored against the old books (2026-08-03)

The one free piece of `PROMPT-retrieval-accuracy-regression.md`'s §5 done on a
key-less machine. Before the S20 backfill the corpus floor was FY2022, so the
five `historical` Layer 2 queries were authored to the FY 2022/23 JLBC editions
and the file header promised to re-author them once the old books landed. The
backfill (2026-08-02) brought every ingestable book edition back to FY2005, so
they were re-authored — all five REPLACED, not edited — to target genuinely old
material with no modern near-duplicate.

The old five (hs-promise-program-2023, hs-enhanced-fmap-2022,
hs-water-augmentation-2023, hs-building-renewal-2023, hs-esa-cost-2022) were
"not wrong, just no longer the oldest material" and are gone, replaced by:

| query | targets | pinned figure(s) |
|---|---|---|
| `hs-arra-k12-stabilization-2010` *smoke* | FY2010 ARRA State Fiscal Stabilization cut-and-backfill of Basic State Aid | $472,114,000 |
| `hs-leaseback-prisons-2010` | FY2010 state sale/lease-back requirement (incl. prisons) | $735,419,300 |
| `hs-bsf-draw-2008` | FY2008 Budget Stabilization Fund drawdown (Laws 2008 Ch. 53) | $487,000,000 |
| `hs-full-day-kindergarten-2005` | FY2005 Full-Day Kindergarten start-up (Ch. 278) | $21,000,000 |
| `hs-fy2010-oneshot-financing` | FY2010 one-time financing total (with the revised-figure dual basis) | $1,104,000,000 or $1,510,000,000 |

**Authoring discipline followed exactly as the file header prescribes:**

- **Every pinned figure verified present in the corpus** by a full-table
  substring scan against the live 77,574-chunk `budget_chunks`, not assumed.
- **Figure recurrence checked across all FYs** to reject weak fingerprints:
  `$21M`/`$4M` and `1,677` recur in modern editions as unrelated lines, so the
  FDK query names FY2005 + the program specifically rather than relying on the
  round figure alone; `$472,114,000`, `$735,419,300` and `$487.0M` are
  distinctive to FY2009–2012, so the only way to score is the actual old book.
- **The chance to score from a wrong-but-modern near-duplicate is closed by
  construction** — the recession measures have no FY2025-27 analog.
- **REACHABLE, verified offline** (no API key needed): each passed the header's
  spot-check — ONE top-20 retrieve of the verbatim question, every key fact
  present in the concatenated chunk text; the pipeline correctly inferred the
  fiscal year and ranked the old book first.

Guards: `tests/test_eval_agent_queries.py` (shape quotas still `historical
>= 3`, smoke still 11 queries across ≥4 shapes incl. exactly 1 historical) and
`tests/test_eval_agent_schema.py` pass; **2168 pytest / 5 skipped** (the 5
skips are the documented ONNX/model-closure skips). Nothing under
`retrieval/`, `harness/`, `ingest/`, `chunking/` or `citation/` was touched —
this is a query-set change, so no eval was run (per the CLAUDE.md rule).

**Still open, needs a keyed machine (unchanged by this work):** finish the
interrupted glm-vs-deepseek head-to-head (deepseek `.../2026-08-03T0242Z/
9a8fd91` is 25/31 — its six `hs-*` transcripts and `rf-county-budget` are
missing, and those six hs- queries no longer exist under the old ids, so the
re-run should use the new set), then make the retrieval fix.

---

## Attested citation linking — code complete, live baseline OUTSTANDING (2026-08-11)

Spec: `docs/superpowers/specs/2026-08-02-attested-citation-linking-design.md`
(A1–A9). Plan: `docs/superpowers/plans/2026-08-02-attested-citation-linking.md`
(11 tasks, all implemented). **Supersedes the post-hoc linker documented in
the next section**, which stays as the record of the defect that motivated
this.

**The model now attests, and the system verifies.** Each retrieved passage
carries a stable per-conversation alias (`c1`, `c2`, …) on the retrieve
JSON. The model appends `[[c3]]` after every figure it takes from a
passage. At turn end the markers are parsed out of the raw answer — they
reach the annotator and **nothing else**, not the streaming frames, not
`finalAnswer`, not transcripts — and each is treated as a **hypothesis**,
verified against the named chunk only.

**A false link now needs two independent failures**: the model must name
the wrong chunk AND that chunk must coincidentally hold the value inside
the figure's written-precision window. Previously one failure sufficed.

### 🔴 `citation/authority.py` is DELETED, not demoted

Document-authority ranking was the mechanism behind the wrong-doc defect
(34.2% of linked figures matched more than one document; the rule picked
by document type, which cannot see whether a chunk concerns the right
agency, fund or topic). **No code path may now pick a source by rank.**
An untagged figure links only when exactly ONE document in the turn's pool
contains the value; otherwise it is refused with an `ambiguity_count`.
Re-introducing any tie-break here re-introduces the defect.

### The gate: false-link rate, not coverage

`eval/false_link_check.py` is the memo §5.2 method as a committed script —
it links **invented** figures against real retrieve pools, so every link
is false by construction. 1,080 trials per profile across the 27 baseline
pools that retrieved anything:

| profile | before | after |
|---|---|---|
| 4-sig billions (`$12.49B`) | 3.7% | **0.28%** (13× down) |
| 4-sig millions (`$376.2M`) | 2.9% | **0.19%** (15× down) |
| exact grouped (`391,157,700`) | 0.4% | **0.00%** |

Not a seed artefact — `--seed 99` gives 0.19 / 0.19 / 0.00.

**Coverage on the recorded figures fell 92.9% → 54.7%.** **This is the
untagged floor, not the shipped number.** Recorded transcripts carry no
markers, and the diagnostic confirms it: every link is
`unambiguous-fallback`, zero are tag-verified.

**On a LIVE turn with tagging, coverage is 100%** — see the live-session
section below.

The figure count rose 435 → 468 during the live fixes, because accounting
negatives stopped being invisible, so the percentages below that predate
that change are on the smaller denominator. False-link rate never moved.

### 🔴 The specificity floor dominates the loss, not ambiguity

Of the 42.6 lost points: **144 figures (33.1 pts) fall below the
4-written-digit floor**, 53 (12.2 pts) are ambiguous, 19 (4.4 pts) are
genuinely absent. This surprised the measurement. A4 fixed
`_significant_digits` to count **written** digits where it previously
counted magnitude (`$12.49 billion` scored 11, truly 4), so rounded
figures no longer bypass the floor built for them — and a below-floor
figure returns no hits at all, so it never reaches the ambiguity branch.

**Consequence: marker coverage matters more than the design assumed.** A
tagged figure verifies at floor 2, so tagging buys back both the
floor-refusals and the ambiguity-refusals. If the model tags nothing,
coverage is 50.3%.

### ⏸ The fallback floor is deliberately left at 4, pending the live run

Swept offline against the same 27 pools. It is a **monotonic trade with no
plateau**, so neither "largest weight that costs nothing" nor "plateau
centre" picks it:

| floor | coverage | false-link (bil / mil / exact) |
|---|---|---|
| 2 | 63.7% | 0.46% / 0.19% / 0.00% |
| 3 | 60.0% | 0.37% / 0.19% / 0.00% |
| **4 (shipped)** | **50.3%** | **0.28% / 0.19% / 0.00%** |
| 5 | 38.4% | 0.00% / 0.00% / 0.00% |
| 6 | 29.0% | 0.00% / 0.00% / 0.00% |

The right answer depends on how much traffic the fallback actually
carries, which only `marker_coverage_mean` from a live run can say. The
tag path keeps floor 2 regardless — there the tag is independent evidence,
so a round `$1,000,000` may still verify inside the one chunk the model
named.

### Also shipped

- **Written-precision tolerance (A4/A5).** A figure's written form defines
  the interval it certifies: `$10.3M` → [10.25M, 10.35M]; `$10,297,300.17`
  → exactly itself; a grouped integer → ±0.5. One rule replaces the
  matcher's flat ±0.1% and reconcile's flat 1%, and it satisfies the
  format-variance requirement structurally. `13.24 + 3.53 = 16.77` no
  longer "explains" a stated `$16.83B`.
- **Matching is anchored on the figure's ABSOLUTE value** — one target,
  always; the scale ladder varies only the *source's* rendering
  multiplier. The old code anchored on the value as written, turning an
  unknown-scale figure into four targets and multiplying collisions.
- **Near-miss (A6).** A failed link reports the nearest source value and
  its relative distance — "you said $12.49B; c3's nearest value is
  12,515.4" is the actionable sentence. 152 of the 216 unverified carry
  one. **An ambiguous figure deliberately carries none**: the value is in
  the pool exactly, so `nearest_value` returns distance 0.0 and the chip
  would read "appears in 2 different documents" beside "differs by 0.0%".
  Ambiguity and not-found are different failures.
- **`marker_coverage_mean` and `tag_accuracy_mean`** on Layer 2 scoring —
  the early-warning metrics for the design's one open risk.

### Deviation from spec A1: aliases are per-CONVERSATION monotonic

The spec said per-turn. A per-turn reset would reuse `c3` for a different
chunk while the old `c3`-labelled chunk is still in the model's history, so
a model tagging from memory would verify against the WRONG chunk — the
exact failure this design exists to remove. Monotonic aliases cannot
collide; a previous-turn alias resolves to a chunk absent from the current
pool and degrades to the fallback. Strictly stronger, same observable
behaviour.

### ✅ VERIFIED LIVE, and six defects it found (2026-08-11)

**A live browser session on a keyed machine closed the design's one open
risk: the model tags reliably.** A captured turn emitted 19 markers, all
19 parsed; a second, 70 markers across 60 figures. **Marker compliance was
never the problem — the system discarding good markers was.**

Final state on a captured live transcript (60 figures, 51 chunks):
**100% coverage, 44 figures linked by TAG, zero unverified.**

| # | defect | why it mattered |
|---|---|---|
| 1 | Linking pool scoped to the TURN | A follow-up answered from context had nothing to verify against — a 9-row table came back all red. The pool is now the conversation, read off the tool messages still in history; the **untagged** fallback stays turn-scoped, because widening it to 8 turns took false-links 0.28% → 2.50% |
| 2 | Source values under $1,000 invisible | The answer side accepted `$974.6`; the source side required a comma group. A table "in millions" writes every agency under $1B without one, so most rows of a General Fund table were unmatchable. Coverage 50.3% → 55.2%, false-link unchanged |
| 3 | The tag-binding distance rule | Discarded `$12.49B (Mar 2020) [[c18]]` and `$1,574.1 million in FY 2026 [[c22]]` — a model tags the end of the NOUN PHRASE. Widened once, then **deleted**: a distance heuristic could only lose citations, never prevent a false one, because VERIFICATION is the guard |
| 4 | Accounting negatives yielded no figure | `$(0.07)B` — a whole variance column was unseen, so neither citable nor derivable. Needed three parts: extractor, source scanner, and `reconcile` comparing difference MAGNITUDES |
| 5 | Chip rendered inside the amount | `$13.98[1]B`. The scale word is part of the figure's span now |
| 6 | Unverified figures were numbered | A table read 13,14,…,20 struck through around a live 21. Only citations are numbered; unverified figures draw no chip and **no count is shown — an uncited number is already visibly uncited** (Destin's call) |

**Two findings that are NOT citation defects:**

- **`jlbc-approps-fy2026-bh26-0003` is mislabelled at the source.** It
  carries the heading of the chart above it (*"FY 2026 General Fund
  Appropriations — Where It Goes"*) while its numbers are total spending
  (AHCCCS $23,010.1M), and its labels are fused
  (`AHCCCSK-12 Education (ADE)`). A correct citation there points at a
  chart whose header contradicts its own figures. **Ingest defect.**
- **The model narrates tool mechanics** ("tagged to c22", "no cite() call
  was made") when asked how it cited something. Output hygiene bans
  exposing corpus mechanics; the prompt needs a pass.

**Process note worth keeping:** several rounds of testing measured a stale
build. `uvicorn` runs without `--reload`, so **Python changes need a server
restart** — only the SPA picks up a rebuild.

### 🟡 STILL OUTSTANDING — the full Layer 2 baseline

The live session verified behaviour on captured single turns. What has NOT
run is the **31-query Layer 2 baseline with the judge**, which is what
produces `marker_coverage_mean` / `tag_accuracy_mean` across the whole
query set and a `compare_agent_runs.py` delta against
`eval/results/agent/2026-08-02T0900Z-0b08221`. Runbook:
**[`PROMPT-attested-citation-baseline.md`](PROMPT-attested-citation-baseline.md)**
— live browser reproduction, Layer 2 smoke then full, and a decision table
gating on `marker_coverage_mean ≥ 0.80` and `tag_accuracy_mean ≥ 0.90`.

A low `tag_accuracy_mean` is the serious outcome: it would mean
attestation is not trustworthy evidence and the floor-2 concession on the
tag path needs re-thinking. That is a reason to stop, not to tune.

**Also unverified in a real browser:** the near-miss and ambiguity tooltip
copy, and chip click opening the PDF at the source rendering.

---

## Citation linking (post-hoc linker) — SUPERSEDED 2026-08-11

> ### ⬛ HISTORICAL — this design was REPLACED by attested linking
>
> Kept as the record of the defect that motivated the replacement. The
> `citation/authority.py` ranking described below is **deleted**; the
> 92.9% coverage figure measured how often a link was PRODUCED, never
> whether it was RIGHT, and that was the wrong gate. See the section
> above for what replaced it.
>
> **Three browser sessions on 2026-08-02 found eight defects; five were
> fixed, and two were fundamental and NOT fixed.** Those two are what
> attested linking exists to solve.
>
> **Full write-up:
> [`docs/superpowers/investigations/2026-08-02-citation-linking-review.md`](docs/superpowers/investigations/2026-08-02-citation-linking-review.md)**
> — old design, why it was replaced, what replaced it, every defect, and
> how to reproduce each measurement offline for free.
>
> The two unfixed problems:
>
> 1. **34.2% of linked figures match a value in more than one document**,
>    and the primary source is picked by document authority — a rule that
>    cannot see whether the chunk concerns the right agency, fund or
>    topic. Observed live: `$16.28 billion` linked to an irrelevant source.
> 2. **A rounded figure is a weak fingerprint.** An *invented* figure
>    falsely links **3.7%** of the time at the profile of `$12.49B`
>    (2.9% for millions) against **0.4%** for an exactly-written
>    `1,391,157,700`. The code treats both identically.
>
> Also unfixed: `reconcile`'s flat 1% tolerance asserts "computed from"
> on figures that are not computed (`13.24 + 3.53 = 16.77` was accepted
> as `$16.83`), and `_significant_digits` measures magnitude rather than
> distinctiveness, so the specificity floor is bypassed for exactly the
> rounded figures that need it.
>
> **The 92.9% coverage figure below measures how often a link is
> PRODUCED, never whether it is RIGHT.** That was the wrong gate, and it
> is why ~2,000 passing tests missed all of this. Any future work here
> should be accepted on the **false-link rate**, not coverage. Building
> that measurement took ten minutes against transcripts already on disk.


Spec: `docs/superpowers/specs/2026-08-02-citation-linking-design.md`.
Plan: `docs/superpowers/plans/2026-08-02-citation-linking.md`.
Branch `citation-linking`, 12 tasks, all 12 implemented.

**The system links figures now; the model cites only prose.** A new
`citation/` package runs in-process at turn end: it extracts every figure
from the final answer with offsets and scale, locates each value in the
chunks that turn retrieved (scale-aware), ranks candidate sources by
document authority (AFR > Approps > Baseline > Governor), reconciles the
leftovers as arithmetic over linked figures, and emits ONE annotation on
the `_done` frame. The webapp renders it as chips; the eval judge renders
the same annotation as inline markers, so the two cannot drift.

**Measured over the 31-query 2026-08-02 baseline, 435 figures:**

| verdict | count | share |
|---|---|---|
| linked | 357 | 82.1% |
| derived | 47 | 10.8% |
| **unverified** | **31** | **7.1%** |

**Coverage (linked + derived) 92.9%**, against the design's measured
feasibility ceiling of 93.6% locatable. Under the plan's ~10% stop
threshold.

**The specificity floor is calibrated, not guessed.** Floors 3/4/5/6 link
357/357/342/300 of 435. Floor 4 ships: indistinguishable from 3 on this
corpus, so it costs nothing measured while still refusing 3-digit
collisions. Floor 5 was rejected by READING all 15 links it would drop —
every one is correct (student counts, FTE positions, inmate counts,
average awards).

### The unverified 31 were read, and one of them is a real find

They are two honest shapes: model-computed deltas whose own inputs are
never stated in the answer ("+$18.3M"), and approximations ("caseload now
above 50,000").

**Except `lk-gf-revenue-fy2026`, which is 6 of 6 unverified — and its
retrieved chunks contain ZERO grouped numbers across 4,413 characters
while the answer states six specific dollar figures.** That is a genuine
Invariant 3 case (retrieval gap or unsourced assertion) surfaced for the
first time by this instrument, not a matcher failure. Worth its own look.

### Defects found and fixed that the plan did not anticipate

Each was caught by making the thing work, not by the tests as written:

- **`find_in_chunks` applied the context scale twice.** It walked the
  scale ladder from `fig.absolute`, so `scale_used` always returned 1 and
  a source that tabulates in millions could never match. Caught by the
  plan's own `test_scale_shifted_match`.
- **The extractor did not know "M"/"B"/"K".** Real answers write
  "+$243.5M" far more often than "$243.5 million"; scale read as 1, which
  broke the match AND made the floor treat $243 million as three digits.
- **The year guard had no word boundary**, so `within $1,000,000` and
  `margin 1,234,567` silently dropped a real figure.
- **🔴 THE ANNOTATION NEVER REACHED THE UI.** `turn_complete` closes the
  turn and `_done` — the only frame carrying the annotation — arrives
  after it, so the reducer's "no open turn, do nothing" early return
  dropped **every figure chip in production** while every component test
  passed. This is the one that would have shipped a feature that does
  nothing.
- **Annotation offsets are not safe to trust in the renderer.** They
  index the whole `finalAnswer`, but `CitedMarkdownContent` renders PER
  TEXT BLOCK and its content may have been rewritten by inline-`<cite>`
  stripping. `placeFigures()` verifies the offset before using it and
  otherwise finds the text; a figure it cannot locate gets NO chip,
  because an absence is visible and a chip on the wrong number is a false
  provenance claim.
- **Both plan test fixtures carried offsets that did not index their own
  answer** (judge figure 1 at 12:20 slices `'287.7 an'`). Both now derive
  offsets and assert they slice correctly.

### Verified offline, end to end

`tests/test_citation_end_to_end.py` drives a REAL `HarnessSession`
through the REAL SSE route with the reported defect's shape — a markdown
table, a chunk whose text fuses the agency name onto the number, and a
stated total — and asserts linked/linked/derived with `derived_from`
[1, 2], `source_text` carrying the SOURCE's rendering, indices in reading
order, and **zero `cite`/`cite_batch` calls** for a fully-numeric answer.
No key, no network.

**Suites: 1986 pytest, 451 vitest, `tsc -b` exit 0.**

### Three defects found in the FIRST browser session (2026-08-02)

All three shipped green: 1986 pytest, 451 vitest, `tsc -b` clean, and a
92.9% offline measurement. **Every one of them was invisible to all of
that**, and each is a distinct lesson about what those numbers cover.

1. **🔴 The refusal banner fired on every fully-linked numeric answer.**
   `detectRefusal` recognised only a `cite()` ack as verification. Task 7
   told the model to stop citing figures, so a linked answer has ZERO
   acks — the banner announced "This answer carries no verified citation"
   over an answer where every number was linked, and its five raw-passage
   previews filled the viewport and pushed the answer off screen. Fixed:
   a linked figure counts as verification, and is the stronger kind (an
   ack validates a quote the MODEL retyped; a linked figure is a value the
   SYSTEM located). `derived` and `unverified` deliberately do not count.
   **Lesson: the change removed a signal another component was reading,
   and nothing tested the consumer.**

2. **🔴 Clicking a figure chip could never open the PDF.** `PdfViewer`
   gates on `citation.resolved.docId` + `pageStart`; the annotation
   carried only `chunk_id`, so every chip landed on "Couldn't open source
   PDF". The design's entire payoff was dead on arrival. Fixed: the
   annotation now carries `doc_id`, `doc_type`, `doc_title`, `publisher`,
   `fiscal_year`, `page_start`, `page_end`, `bbox` per source, making it
   self-describing for the judge and any later audit too. Chunk TEXT is
   deliberately still absent — it would ship a chunk body per figure, and
   the highlighter searches `source_text` first.
   **Lesson: every test asserted the annotation was PRODUCED; none
   asserted it was USABLE by its consumer.**

3. **🔴 A real figure was silently dropped: "took in $27,362,036.72".**
   The year guard treated a preceding "in" as a year cue. Worse, the
   guard had **no true positives available to it** — `_FIGURE_RE` needs
   comma-grouping or a currency marker with a decimal, so a bare `2026`
   can never match it in the first place. It could only ever cost real
   money. Deleted, and pinned by
   `test_no_year_can_reach_the_extractor_in_the_first_place`.
   **Lesson, and the sharpest one: re-running the 31-transcript
   measurement after the fix gives byte-identical numbers — 435 figures,
   92.9% coverage, before and after.** The recorded corpus simply never
   contained that sentence shape. A clean offline measurement over a
   fixed transcript set says nothing about the shapes it happens not to
   contain, and the FIRST live answer found one.

Suites after all three: **1997 pytest, 459 vitest, `tsc -b` exit 0.**

### 🔴 OUTSTANDING — needs a machine with an OpenRouter key

Plan Task 12 Steps 3–4 could not run here: `ai_available` reports **"no
API key configured"** on this machine, and both steps spend real money.

> ⚠ **That "no API key" claim is STALE — see the note under "What's next".**
> A working OpenRouter key has been in `<data_dir>/settings.json` since
> 2026-08-09 and `/api/ai/status` reports `available: true`. This section is
> historical anyway (the design it belongs to was superseded), but the same
> stale belief was repeated in later sections and cost a session real time.
**Runbook: [`PROMPT-citation-linking-baseline.md`](PROMPT-citation-linking-baseline.md)**
— it carries the exact commands, the expected metric directions, and the
browser checks.

1. **The live reproduction** of *"what are the biggest agencies by
   budget"*. The offline end-to-end test covers its shape, but nobody has
   watched a real model answer under the new prompt.
2. **The Layer 2 re-baseline** (`--sets quick,multi,deep,refusal` — the
   retired `--subset full` is gone; ~$1.50–3 now that quick is 45 queries,
   plus the judge as a separate charge), then `compare_agent_runs.py`
   against
   `eval/results/agent/2026-08-02T0900Z-0b08221`. Expected direction:
   `figure_coverage_mean` high, `unverified_rate` low, `steps_mean` and
   `input_tokens_mean` DOWN (cite round-trips removed), `cite_pass_rate`
   no longer dominated by figure citations.

**Until that runs, the prompt change (Task 7) is unmeasured.** Everything
else in this section is measured against recorded transcripts or pinned
by tests.

**Also unverified in a real browser:** the chips themselves — derived and
unverified tone, the "Also appears in:" list, and chip click opening the
PDF at the source rendering. 22 new vitest specs cover the logic; nobody
has watched it render.

---

## Query understanding — SHIPPED (2026-08-03)

Spec: `docs/superpowers/specs/2026-08-02-query-understanding-design.md` (Q1–Q6).
Plan: `docs/superpowers/plans/2026-08-02-query-understanding.md`. Branch
`query-understanding`.

**An analyst typing the shorthand they actually use now gets that agency's
documents, of that type.** `RetrievalRequest` already carried
`agency_canonical_id` and `doc_type` filters that reached LanceDB; nothing
populated them from query text. Three parsers now do, mirroring `query_year.py`.

**Measured against a CONTROL run of unmodified master on the same machine
under the same load** — not the morning's recorded baseline, because the box
was at load 11 and the apparent latency regression was entirely contention:

| | control (master) | shipped |
|---|---|---|
| recall@5 | 73.81% | **88.10%** |
| recall@15 | 97.62% | **100.00%** |
| recall@20 | 97.62% | **100.00%** |
| refusal precision | 60% | 60% |

**+14.3 points of recall@5, and perfect recall at 15 and 20. Gate G1 passes.**
Suite 1986 → **2155**.

On the six shorthand queries that motivated the work
(`eval/navigational_check.py`, precision@5): mean agency precision 0.767 →
0.833, mean doc-type precision **0.200 → 0.833**.

### 🔴 AGENCY IS A PREFERENCE, NOT A FILTER — a measured deviation from spec Q2

The spec says an exact agency match becomes a hard filter. **It was measured
and it loses.** Same eval set, agency-filter ON vs OFF, nothing else changed:

| | recall@5 | recall@15 | recall@20 | failed lookups |
|---|---|---|---|---|
| hard filter (spec Q2) | 83.33% | 95.24% | 95.24% | q-009, q-022 |
| **preference only** | **88.10%** | **100%** | **100%** | none |

**Why the filter loses, and it is not a tuning accident: the corpus is stamped
incompletely, so a CORRECT reading of the question can still exclude the
answer.** q-009 names "the DOR Unclaimed Property Fund" and the AFR passage
answering it carries only `agency:sba`; q-022 names the Secretary of State and
its answer sits in a House document. In both the parser is right and the filter
deletes the answer anyway — **silently**, because the agency has other chunks so
the Q3 empty-result fallback never fires.

Cost: one slot on one navigational query of six (`dema ar`).

**Doc type still hard-filters** — it has no equivalent stamping gap, and it is
what took doc-type precision from 0.200 to 0.833.

**Re-open this only with a measurement, and re-run it after any re-ingest that
improves agency stamping** — the trade could genuinely reverse once the corpus
side has the aliases the query side now has.

### 🔴 The corpus has the SAME missing-alias problem, on the ingest side

This is the finding behind the deviation above and it outlives it.
`chunking/entity_stamper.py` cannot resolve "DOR" in document text any better
than the query parser could before this work: **103 of the 157 agencies carry
no alias at all**. The query side now has them. **The ingest side does not, and
fixing it needs a re-ingest.**

### Calibration

**`MATCH_PENALTY = 2.0`** (`retrieval/agency_boost.py`), penalty-shaped like the
recency boost so `top_score` can only fall. Re-swept after agency became a
preference, which routes the whole agency signal through it: recall@5 plateaus
at .8810 from 1.0 through 3.0, falling to .8333 at 0.0 and .8571 at 4.0. **2.0
is the plateau CENTRE** — the right pick when the metric degrades in both
directions, unlike the recency weight where lower was always safe.

**`REFUSAL_THRESHOLD` stays 1.46.** `calibrate_refusal.py` recommends −0.77;
rejected, with the reasoning at the constant. The penalty does not disturb the
distribution (`max_top_score` 8.6779 at every weight 0.0–4.0, because a penalty
only lowers non-matching chunks), and −0.77 trades refusal RECALL 0.60 → 0.40
for precision — it refuses LESS, which is backwards under Invariant 3.

### 🔴 The stoplist was load-bearing, and the review gate would NOT have caught it

Every JLBC slug becomes an alias unconditionally, and **13 of the 145 slugs are
ordinary English words**. **`for` is a preposition appearing as a standalone
token in 14 of the 47 eval queries** — unguarded it hard-filtered all of them
onto the Department of Forestry.

These arrive through SLUGS, not drafted aliases, so **Task 8's human review gate
could not have caught them.** Two independent derivations agreed: a frequency
count over 247,607 tokens of real budget English (`gov` 5944 · `per` 3993 ·
`tax` 541 · `for` 474, then a ~190 noise floor) and an ordinary-word scan.

Three escalation levels now exist, and the distinction is load-bearing:

| mechanism | effect | examples |
|---|---|---|
| `AMBIGUOUS_ALIASES` | demote to a boost | `doc`, `colleges`, `art`, `bar` |
| `SUPPRESSED_ALIASES` | never resolve at all | `tax`, `for`, `ban` |
| `AMBIGUOUS_PHRASES` | demote a NAME head | `insurance` |
| `AMBIGUOUS_AGENCIES` | demote an agency, every tier | `agency:gov` |

**A demotion is not always enough** — even a boost pulls the wrong agency up the
page, which is what "2024 income tax rate" did to the Board of Tax Appeals.
And `AMBIGUOUS_PHRASES` exists because the same defect occurs one tier up where
a suppressed slug cannot reach it: "Insurance, Department of" has the
single-word head "Insurance", so "health insurance premiums for state
employees" hard-filtered onto the insurance regulator.

### Four silent wrong-answer paths, all found before the eval was run

All share a shape worth naming: **a bad guess that SUCCEEDS**, so the Q3
fallback never fires and the analyst is never told a filter was inferred. A
guess returning nothing is self-correcting; a guess returning the wrong thing
is not.

- **`chapter 21 baseline`** read as a FY2021 hard filter — the JLBC shorthand
  bypassed the designator guard the four-digit rule already used.
- **`general appropriation act` → `budget-bill`.** It is the NAME OF A LAW. The
  phrase appears in **6,253 corpus chunks, ZERO of them budget-bill**, while the
  whole type is a single 136-chunk document. Cost n-003 and n-007 their ground
  truth.
- **`for` → Forestry**, above.
- **`insurance` → the regulator**, above.

Found by `tests/test_query_understanding_eval_safety.py`, which checks the
parsers against the eval set's own ground truth. **That guard is also what
forced the agency-filter deviation**: it fired on q-009, then on q-022 the
moment `for` was suppressed, and two exemptions was the signal to measure the
policy rather than keep exempting.

### Duplicate catalog entries cost a filter AND split the corpus

Found by Destin reviewing the checklist. Five agencies are recorded twice
(ASU, Child Safety ×5, Revenue, WIFA, Constable Ethics, Equal Opportunity).
A duplicated name is not cosmetic: entries resolving to two ids were treated as
ambiguous, and the duplicate ids **split the stamped chunks**.

Fixed query-side, no re-ingest: entries whose canonical name matches as a
sorted token multiset are ONE logical agency, and a match resolves to every id
in the group. Token multiset rather than string equality because the catalog
writes the same agency both ways round — "Child Safety, Department of" and
"Department of Child Safety" are five entries for one agency.

> **⚠ 2026-08-16 — "fixed query-side" is exactly as narrow as it sounds.**
> A TYPED search works. **The corpus is still split and two other readers
> still see duplicates.** Measured: Child Safety is 4 live ids
> (`dcs` 1595 chunks / `cs` 520 / `doa-csf` 19 / two empty), ASU 2, WIFA 2,
> Equal Opportunity 2, Constable Ethics 2, Revenue 2. **`list_filter_values`
> — the tool AI Mode uses to discover what agencies exist — emits raw ids
> with no grouping** (`harness/tools.py:816`), so the model sees three
> agencies and, picking one, gets 24 documents instead of 265. The Budget
> Documents agency facet has the same gap. Being merged in the DATA (Destin's
> call over read-time grouping) at Phase 4 of the identity spec.

| query | chunks reachable | years now returned |
|---|---|---|
| `asu` | 1,263 → **1,343** | 2019–2025 |
| `child safety` | 505 → **2,033** | 2018–2027 |
| `water infrastructure finance authority` | 169 → **295** | 2022–2027 |

**ASU is one university split by a naming change, not two agencies** — printed
"ASU – Tempe/DPC" FY2015–2018 then plain "Arizona State University"
FY2019–2020, while `agency:uniasu` runs FY2021–2027. Contiguous, never
overlapping.

**UA is the opposite case and needed its own mechanism.** No entry is named
plainly "University of Arizona"; Main Campus (959 chunks) and Health Sciences
Center (564) run in PARALLEL every year, so neither supersedes the other.
`CURATED_ALIAS_AGENCIES` holds aliases that deliberately name a SET of entries
— also used for `financial institutions` → {ban, dif}, since a MERGER cannot be
detected the way a rename can.

### ⏸ Aliases — eight applied, the rest deferred

Approved by Destin by name: **`adoa` `difi` `dohs` `dhs` `asu` `nau` `aph`
`dffm`**, plus `doc` and `dema` from the spec's own evidence. A test pins this
as the whole set — anything beyond an agency's own slug fails the suite.

**The 158 machine-drafted proposals in
`docs/superpowers/investigations/2026-08-02-agency-alias-review.md` are NOT
applied** and the review is deferred. That document is on master and is now
**stale in six places** (ASU, Administration, DIFI, Homeland Security, NAU,
Pioneers' Home) — regenerate it if the review resumes.

**Worth knowing before spending 35–50 minutes on it:** the generator builds
acronyms from initials only, so it proposed `nu` for Northern Arizona
University and `ph` for Pioneers' Home. Destin supplied `nau` and `aph` from
memory. On both cases he cared about, human knowledge beat the drafted list —
the document's real value may be its appendix, which surfaced the 13
ordinary-word slugs nobody knew were live.

### Catalog debris removed — 🔴 QUERY-SIDE ONLY. THE CORPUS IS STILL POISONED

> **⚠ CORRECTED TWICE. As of 2026-08-16 this IS handled — and the middle
> correction below was itself wrong.** The catalog's `canonical_name` values
> are repaired, the corpus is re-labelled, and `agency:ost` now sits at
> **0 wrong of 117 documents** (was 673 of 992). **But the causal claim in
> the paragraph below — that the corrupted catalog string is what stamped
> the corpus — was measured and is FALSE.** There is no bare `Board of`
> entry; repairing the strings changes labelling by zero. The real defect
> was `rapidfuzz.token_set_ratio` scoring 100 for any candidate whose tokens
> are a subset of a catalog name. See the identity section below.
>
> The original (now doubly-superseded) text follows.
>
> The debris was removed from the QUERY resolver. The catalog's own
> `canonical_name` was never repaired, and **that is what stamped the
> corpus.** `agency:ost`'s canonical name is still the raw TOC row
> `'Osteopathic Examiners … Arizona ...   342  Board of.....................'`,
> so the standalone phrase "Board of" still names that agency on the
> INGEST side. Measured: **`agency:ost` is stamped on 992 documents —
> more than AHCCCS or Education — and 721 of them never mention
> osteopathy (72.7% wrong)**, while every clean agency sampled runs
> 0–1.5%. `agency:apc` is 86% wrong on 28 documents, `agency:nci` 11% on
> 72. It is also reaching the MODEL: a committed agent-eval transcript
> from 2026-08-02 shows `list_filter_values` handing the model that
> corrupted name as the sixth-largest agency in the corpus.
> Full evidence:
> [`docs/superpowers/investigations/2026-08-16-identity-consistency-audit.md`](docs/superpowers/investigations/2026-08-16-identity-consistency-audit.md).
> Fix specced at
> [`docs/superpowers/specs/2026-08-16-corpus-identity-consistency-design.md`](docs/superpowers/specs/2026-08-16-corpus-identity-consistency-design.md)
> Phase 2. **A re-stamp needs NO re-ingest** — verified; see that spec's I7.

Five PDF-extraction fragments that would fuzzy-match noise: `'pp y, Economic
Security…'` (`agency:des`), a bare `'Board of'` (`agency:ost`, from a page
break — it would have hard-filtered "board of regents" onto Osteopathic
Examiners), `'p University of Arizona…'` (`agency:uniuhsc`), a leading-comma
Forestry variant, and **`'ministration, Arizona Department of…'`**
(`agency:doa-apf`) — a truncated "Administration" that registered as a
single-word phrase and HARD-FILTERED. Guarded as a class, not as five
instances.

### Follow-ups this created

- **Edition diversity in the candidate pool.** Chronological ordering is
  UNCHANGED at 0.750 and **raising the recency weight does not help** —
  measured at 0.85, 2.0 and 4.0, `ahcccs appropriations report` never surfaces
  FY2026, which exists. The newest edition is not in the RRF pool to be
  reordered: ~2,000 near-identical AHCCCS chunks span FY2005–2026 and the pool
  is capped at 20. **Do not re-tune `RECENCY_BOOST_PER_YEAR` for this.**
- **Agency stamping on the ingest side** (above) — the largest remaining win,
  and it would let the agency-filter decision be re-measured.
- **Fund resolution** has the identical gap and fix shape; deferred to keep
  this change reviewable.
- **The UI does not yet show what was inferred.** `RetrievalResult` carries
  `inferred_agencies`, `inferred_doc_types` and `dropped_filters` so it can —
  and they must be described DIFFERENTLY, since doc type filters and agency
  only prefers. The AI Mode UI redesign shipped alongside this (see the
  section below), so there is now a settled surface to add it to.
- **`AMBIGUOUS_PHRASES` candidates not acted on:** `administration`, `housing`,
  `nursing`, `senate`. Judgement calls, not clear defects.
- **The shared normalizer keeps hyphens**, so a hyphenated catalog name only
  matches tier 1 if the analyst types the dash. It belongs to
  `entity_stamper.py` and both sides must agree, so changing it is its own
  change with its own re-ingest question.

---

## AI Mode UI redesign — shipped (2026-08-02)

Spec: `docs/superpowers/specs/2026-08-01-ai-mode-ui-redesign-design.md`.
Plan: `docs/superpowers/plans/2026-08-01-ai-mode-ui-redesign.md`.
Merge `2cef0f9`. **Webapp-only** — nothing under `retrieval/`, `ingest/`,
`chunking/` or `harness/` is touched, so the CLAUDE.md eval rule does not
apply and no eval was run.

**571 vitest across 54 files** (was 432) + pytest 2012, tsc and build clean.

Started from four complaints: "the tool cards are ugly and disproportionate
to chat, there are weird extra scroll bars all over, the citation viewer
renders strangely, and there is a lot of wasted space." All four traced to
root causes and fixed — but the live browser pass changed more than the
plan did, and that part is below.

### As shipped

- **One scroll container** in the chat column. The composer floats over it
  and publishes its measured height, so messages scroll behind it.
- **Tool rows**, not cards: ~30px, capped below the prose measure,
  consecutive calls coalesced into one row, status carried by glyph shape
  so only failure spends a colour.
- **One `--ai-col` measure** governs thread, banners and composer.
- **The ask bar.** Single-line-then-wrapping composer wearing Home's
  hero-search recipe verbatim (pill, canvas fill, navy focus ring), so the
  app has ONE search-input identity instead of three. Paperclip stub +
  tools menu + Send. Grows to four lines, then scrolls with no scrollbar
  and a per-edge fade.
- **Corpus and mode are two toggles** behind the tools icon, each carrying
  the copy describing its own consequence. The tier sentences still come
  off the wire (S16). A pip on the closed icon reports any non-default
  setting, and the placeholder names the live corpus — those are the only
  permanent statements of either, now that both live behind a menu.
- **The navy hero strip is gone**; the thread has a navy-wash ground the
  composer fades INTO rather than sitting on.
- **The footer's "AI Mode available" line is gone.** A working system does
  not need to announce it. The failing case got the whole page instead,
  with the server's reason demoted and addressed to the administrator, and
  probing kept as a separate screen.
- **Header:** the row is the two corpora with AI Mode between them, plus
  one menu holding Upload, Settings and Admin. Home left (the logo goes
  there). The AI icon's spark orbits the glyph on select, and the label
  rolls out to its own measured width.

### 🔴 Five defects found by REVIEW, not by tests

Recorded because the same classes will recur, and every one of them left
the suite green:

1. **`container-type: inline-size` on the thread scroller silently
   re-clipped the citation tooltip** — including `.chat-cite-fail`, the
   panel saying WHY a citation failed (Invariant 2). Layout containment
   makes an element a containing block for `position: fixed`. Both
   existing contract specs stayed green because each was individually true
   and jointly wrong. The guard now covers `contain`, `container`,
   `container-type` and `content-visibility`, and a later spec forbids
   `mask-image` on the scroller for the same reason.
2. **A hover rule painted the azure SUCCESS tint behind FAILED citations.**
3. **A cross-branch defect neither side could see.** Master's `FigureChip`
   renders `.chat-cite-tooltip`, which this branch had made
   `position: fixed` with JS-supplied coordinates. FigureChip passed none,
   so its tooltips detached from their chips on the first scroll. The two
   changes never touched the same lines; git merged them without a murmur
   and both suites stayed green.
4. **The bottom chrome painted over the thread's own scrollbar** — it sat
   at `right:0`, so the bar looked half-drawn.
5. **The tools menu was unreachable by pointer.** Trigger and popover are
   both absolutely positioned, so the gap between them belonged to
   neither; crossing it left the subtree and fired `mouseleave`.

### 🔴 And one this work CAUSED

Removing the retired `.chat-input` block **by range** took `.chat-welcome*`
with it — the empty state lost its centring and the mascot drifted. Nothing
failed, because no spec covered that block. There are two now, verified by
re-running the exact accident. **The lesson generalises: this stylesheet
has several rules whose ABSENCE is silent, because a flex container that
stops existing just leaves its children looking approximately fine.**

### Still unverified

- **The AI-mode animations have not been confirmed on a machine with
  `prefers-reduced-motion` OFF.** The app honours it everywhere; with it on,
  the spark throw and the stop-button spinner are disabled by design and
  snap between states. Worth knowing before anyone reports them as broken.
- The bundle has not been rebuilt against this webapp.

---

## AI Mode chat history — shipped, then reviewed and tightened (2026-08-03)

Spec: `docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md`
(H1–H6 + A1, with implementation amendments). Implementation handoff:
`docs/active/handoffs/2026-08-02-chat-history-implementation.md`. Follow-up
session handoff: `docs/active/handoffs/2026-08-03-ai-mode-chat-history-followups.md`
(its "uncommitted fixes" were all committed in the branch; the three issues
it lists are resolved by commits `9d73754`/`9645e9c` (Issue 1), `6f35f7e`
(Issue 2) and `62197cc` (Issue 3 audit)). Merged via the `chat-history` PR.

Analysts can browse, search and resume their own past AI Mode conversations.
Transcripts are per-device files at `%LOCALAPPDATA%\JLBC-Insight\conversations\`
— **never the share** (Invariant 7, pinned by the AST import-allowlist test):
one analyst's questions are not ~20 colleagues' reading material.

### As shipped (decisions H1–H6)

- **H1 — files, not a database.** One JSON per conversation; the directory IS
  the index. Atomic tmp+`os.replace` writes (per-call uuid suffix, not
  per-process, so two writers on the same id can't share a tmp name). Read
  paths degrade on a corrupt file; the write path raises.
- **H2 — browsing is free.** Opening a stored chat renders it live with no
  server session and no API spend; the session is rebuilt from the stored
  transcript on the FIRST send (`resume_from` on `POST /api/conversations` —
  no parallel resume endpoint). The stored corpus wins over whatever the
  client requested, and the picker now follows it (review fix below).
- **H3 — auto-naming is one cheap LLM call after the first exchange**, ledgered
  under its own `"title"` tier, falling back to the truncated question on
  EVERY failure (no key, AI Mode off, over-limit, provider error). Manual
  renames are never overwritten by auto-naming.
- **H4 — search** scans titles and prose only; `tool` messages are excluded
  by ROLE (their content is a JSON payload of retrieved chunks, so an
  isinstance check would not exclude them).
- **H5 — a stale citation is marked, never silently dropped.** Click-time
  chunk fetch distinguishes 404 ("gone") from 200-with-quote-missing
  ("moved"); a 503 publishes nothing ("we cannot tell" beats a false "your
  source is dead"). The verified quote still renders.
- **H6 — keep everything.** No cap, no expiry, explicit delete only.
- **A1 — collapsible history rail** amends the UI redesign's D1; auto-
  collapses when the source panel opens; collapsed state persists.

### The 2026-08-03 review found real bugs; this is what was fixed

A commit-by-commit review of the branch (all 20 commits unique to
`chat-history`) found the code careful overall but with genuine logic gaps.
Fixed in the branch before the PR:

- **Resuming a chat wiped its transcript on first send.** The resume id never
  reached `conversationIdRef`, so the first send dispatched
  `CONVERSATION_STARTED`, whose reducer resets the timeline — emptying the
  rehydrated turns the analyst was looking at. Fix: the rehydrate effect
  seeds the ref and the `REHYDRATED` id; `send` detects the resume case and
  dispatches with a new `keepTurns` flag. Regression-tested.
- **The annotation persistence fix (Handoff Issue 1) had a hole on the
  interrupt path.** `_attach_annotation` sits after the interrupt breaks, so a
  STOPPED turn persisted without its figure annotation — and the amended test
  asserted a shape that path never produced. **STILL OPEN** (below).
- **Corpus mismatch on select.** The rail lists both corpora but selecting a
  chat never moved the picker, so the thread could answer out of one corpus
  while the UI showed the other. Selecting now reads the stored transcript's
  corpus and sets both in one remount.
- **Sticky stale marks.** A chip branded "source no longer available" (e.g.
  a transient 404 mid-ingest) never cleared. The viewer now publishes a
  `resolved` verdict on a clean re-check; the chip clears itself.
- **The mid-turn delete/rename race.** `persist_turn` runs AFTER `end_turn`
  in a background thread, so the rail could delete or rename a chat while its
  turn streamed. Two fixes: a turn-end write skips when the file is gone and
  this is NOT the first turn (a deleted chat stays deleted — the first-turn
  discriminator is the USER-message count, since a tool-calling first turn has
  two assistant messages), and `harness/history.py` gained a per-id write lock
  (`threading.RLock`) wrapping save/delete/rename so the turn-end write and a
  rail rename can't interleave. The lock-probe test is verified to FAIL when
  the lock is stripped.
- Smaller: the `useHistory` empty-query guard now gates on real search state,
  not a seq counter the mount fetch also bumps; the transcript tmp name is
  unique per call (`uuid` and `threading` added to the Invariant-7 allowlist
  — both stdlib, neither can reach the share).

### ✅ The 2026-08-11 second review — eleven defects, all fixed

A second review of the merged branch (this session plus a parallel
`/code-review high` over `7b4059d..47cc551`) found eleven defects. **Four
were reproduced by execution before any fix was written, and every guard
below was verified FAILING against the unfixed code** — three of them only
after the test itself was rebuilt, because the first versions passed against
master and proved nothing. Suites **2343 → 2368 pytest** (5 skips unchanged)
and **678 → 693 vitest**, `tsc -b` and `npm run build` clean.

**No eval was run, and the CLAUDE.md rule does not ask for one**: nothing
under `retrieval/`, `ingest/`, `chunking/`, `citation/` or
`harness/system-prompt.md` was touched. The changes are `harness/session.py`,
`harness/history.py`, `app/routes/conversations.py` and the webapp.

#### 🔴 The four that silently destroyed data

1. **A silent turn wiped the PREVIOUS answer's citation chips.**
   `_attach_annotation` searched backwards through the whole history, and
   `_Accumulator.annotation()` returns `{"figures": []}` — a **truthy** dict —
   so `if not annotation` never fired. A turn that appended no assistant
   message (the model returned neither text nor tool calls; a stop landed
   before step 1) walked into the previous turn and overwrote a correctly
   linked answer's annotation with an empty one. Reproduced: turn 1's figure
   count fell 1 → 0. **Fixed by bounding the SEARCH** (`since=turn_start`,
   captured right after the user message), not by filtering the payload —
   filtering would have broken the deliberate pin in
   `test_interrupt_on_a_text_only_turn_is_a_plain_interrupt`.
2. **The auto-title path erased a later turn.** `persist_turn` loaded the
   transcript, made a blocking HTTP call of up to 20 s, then saved the *stale*
   object. Reproduced: 4 messages → 2. It also **resurrected a chat deleted**
   during that window and **reverted a rename** made during it, clearing
   `title_is_manual` so auto-naming re-armed against a title the analyst
   chose.
3. **Stop lost the answer as well as the annotation.** `use-chat`'s `stop()`
   aborts the fetch first, so GeneratorExit reaches `stream_turn` and the
   end-of-turn code never runs. Reproduced: history after a stop was
   `[user, assistant(tool_calls), tool]` — the partial answer the analyst was
   watching stream in was never recorded. New `_abandon_turn()` records it and
   attaches the annotation before `_repair_history()` runs.
4. **Deleting the open chat's row made it permanently uncontinuable.**
   `create_conversation` raised 404 on `resume_from` *before* consulting the
   registry, and `Ai.tsx` never cleared `selectedChatId` on delete. Reproduced
   through the real route: every later message 404'd against a live in-memory
   session, with no escape but "+ New chat".

#### The mechanism, named once

Defects 2 and the rename clobber are one shape, and the fix is one idea:
**a lock was added where a transaction was needed.** `history.save` took the
id's lock, which makes each WRITE atomic and does nothing for the
read-modify-write around it. `harness/history.py` now exposes
`transaction(id)` (hold the lock across the whole load→mutate→save) and
`set_title_if_absent(id, title)` (re-read under the lock, write ONE field).
The title call stays **outside** the lock — holding it across 20 s of HTTP
would freeze the rail's rename and delete, and there is a guard asserting it
does not.

#### The rest

5. **A "resolved" verdict cleared stale marks it had no business clearing.**
   `moved` is decided per-QUOTE and was published per-CHUNK, so clicking a
   still-good citation cleared the stale mark on a sibling into the same chunk
   whose source really had moved — a moved source reading as verified, i.e.
   Invariant 2. `markUnresolvable` now carries a span key; `gone` stays
   chunk-wide (the chunk 404s, so every citation into it is dead).
6. **`ConversationRegistry.get_or_add` was written to make resume atomic and
   was never called** — the route still did `get` then `add`, so two tabs
   resuming one chat each built a session and the second replaced the first
   without closing it. Now wired.
7. **Resume never stopped being a resume.** `isResume` compared the id to
   `resumeFrom`, and the server returns the same id, so every message
   re-POSTed `/api/conversations`. A one-time latch; a failed handover still
   retries.
8. **`_read` degraded on malformed JSON but not on non-object JSON.** `null`,
   `[]`, `5` parse fine and then raise `AttributeError` on `raw.get`, which
   escaped and 500'd `GET /api/history` — blanking the entire rail, the exact
   opposite of "one corrupt file costs one chat".
9. **`CostsPanel` used `??` where every other tab used `||`**, so an
   unrecorded key (the empty string) painted a blank cell instead of
   "(not recorded)" — contradicting the comment directly above it.
10. **`useHistory`'s debounce cleanup hung off one branch**, so clearing the
    search box scheduled an uncancellable fetch; the rail unmounts on every
    chat switch, well inside the 200 ms window.
11. **`reload` was returned by `useHistory` and called by nobody**, so a new
    chat's row and the title generated for it seconds later never appeared
    until something remounted the rail. The panel now bumps a token when a
    turn ends.

**Also: delete now takes two clicks.** The ✕ sat beside the ✎ and destroyed a
transcript outright, under a spec (H6) with no expiry and no undo anywhere.
The armed state is a labelled word, not the same glyph — a confirmation you
can hit by reflex is not a confirmation.

**Transcripts are now stamped `version: 1`.** Nothing reads it; that is the
point. A file with no stamp reads back as **0**, so "written before
versioning" and "written today" are distinguishable — which is the only thing
that makes a future migration possible, and it cannot be added retroactively.

### Still open after that review

- **No tier on the transcript.** A resumed Deep Research chat silently
  continues at Standard. Deliberately NOT fixed here: `_Conversation` does not
  carry the tier (it is per-message), and restoring it on resume is a product
  decision about whether reopening a chat should silently re-arm Deep
  Research's ~44× cost. The schema half of this item is done (above).
- **409-on-resume-busy reads as a generic error** in the composer, though the
  server's sentence does reach the client — `api.ts` surfaces FastAPI's
  `detail`, so the analyst sees "This conversation is still answering the
  previous question", just wearing a generic prefix.
- **`harness/history.py`'s `_write_locks` dict is never pruned.** Left alone
  on purpose: it is bounded by distinct conversation ids touched in one
  process (hundreds, a few hundred bytes), and removing a lock another thread
  may be holding trades a real correctness risk for a trivial saving.
- **None of the UI changes has been seen in a browser.** jsdom applies no
  stylesheet, so the armed-delete styling, the rail's reload-on-turn-end, and
  the span-scoped chip marking are pinned by specs and unwitnessed — the same
  gap that produced this branch's original defect list.

Spec follow-ups still open: the Administrator Handbook paragraph (history
writes questions to disk in plain text; the first exchange goes to the model
for naming — a confidentiality note that `docs/HANDBOOK.md` must carry, and
the file does not exist yet), and `MAX_CONVERSATIONS = 40` may want a
revisit now that eviction is no longer data loss.

---

## AI Mode persistent conversation — shipped (2026-08-11)

Spec: `docs/superpowers/specs/2026-08-11-ai-mode-persistent-conversation-design.md`
(P1–P8). Plan: `docs/superpowers/plans/2026-08-11-ai-mode-persistent-conversation.md`.
Two things Destin asked for after using the shipped chat history: a new chat
should appear in the rail the moment it starts, and the conversation should
survive clicking Budget Documents. **Webapp-only** — nothing under `app/`,
`harness/`, `retrieval/`, `ingest/`, `chunking/` or `citation/`, so the eval
rule does not apply and no eval was run. **742 vitest / 73 files, `tsc -b`
exit 0** (baseline 693: +18 here, ~30 from master since branching).

### As shipped

- **The new-chat row is a CLIENT-SIDE placeholder, never a file (P1).** It is
  replaced by IDENTITY, not timing — the synthetic row renders while the
  current conversation's id is absent from `/api/history`'s list, so there is
  never a moment with two rows or with none. Writing an empty transcript was
  rejected: it re-creates the zero-message rows deleted as debris hours
  earlier, and contradicts H2's browsing-is-free.
- **The conversation moved above the router (P4).** `AiSessionProvider` owns
  corpus / selected chat / nonce; a headless `ChatEngine` owns `useChat`.
  A route change is no longer an unmount, so nothing aborts. **Closing the tab
  still aborts (P5)** — the page unloads and the socket drops, which is the
  whole safety argument, since abort-on-close exists because a closed tab once
  left a model streaming and billing into a dead socket.
- **The key `${corpus}:${selectedChatId ?? "new"}:${nonce}` survives unchanged**
  and still remounts on a corpus switch. `Ai.test.tsx`'s wire assertions
  (`createdCorpora` → `["budget","fiscal_notes"]`) pass **unedited** through
  the hoist — they are the wrong-corpus guard and were not allowed to move.

### 🔴 The plan's own code was wrong in three places, each found by RUNNING it

Worth keeping as the record of what a plan's finished-looking code block is
actually worth:

1. **A hook after an early return.** The new `useMemo` was placed below
   `HistoryRail`'s `if (collapsed) return`, a conditional hook. Caught by a
   PRE-EXISTING suite that toggles the rail — the plan's own new tests passed.
2. **`chat.id === draftId` was not a sufficient render guard.** Once the real
   row lands with that same id the predicate is still true, so the real titled
   row would have rendered as a dead "New chat" span with no rename or delete.
3. **The whole architecture diagram.** A keyed host wrapping `Header` +
   `<Routes>` remounts the CURRENT ROUTE on a corpus switch, resetting
   `Ai.tsx`'s unrelated `useAiStatus` probe and flashing the availability gate
   over the composer. The remount boundary had to narrow to `ChatEngine`.

### 🔴 P4's own scenario did NOT work when this first went green

697 specs passed and the feature's headline behaviour was broken. `Ai.tsx`
still unmounts on navigation and `useAiStatus()` had no cache, so returning to
`/ai` re-probed from `null` and rendered the availability gate **over the live,
surviving answer** — and a hiccuped probe rendered "AI Mode is currently
unavailable" while a paid turn streamed invisibly behind it. Every spec mocks
`aiStatus` with an already-resolving promise and then awaits the panel, so
nothing could see it. Fixed both ways: the probe seeds from a module-level last
verdict, and the gate yields to a conversation that already has turns.

### The mirror is `useLayoutEffect`, and that is load-bearing

`ChatEngine` reports its `useChat` result up to a stable provider. With a
passive `useEffect` a rendered frame can exist where the picker reads "Fiscal
notes" while `chat.send` is still the budget instance's closure — `send` bakes
the corpus in at hook level. `useLayoutEffect` commits it in the same commit,
before paint. The dep list names all eight members of `UseChatResult`
individually; passing the whole object re-creates an infinite loop.

### `chatDeleted` has been written three ways and two were wrong

A functional updater (correct, but impure — StrictMode double-invokes it); a
plain closure read (pure, but its only caller runs it AFTER an await, so
deleting chat A then clicking chat B mid-flight discarded B); and the shipped
`selectedIdRef`. **A fix for a style nitpick cost a real data-visible race.**
Both that race and `INERT_CHAT.send`'s synchronous throw are now pinned by
specs verified failing against the exact broken versions.

### ✅ Browser-tested by Destin and accepted (2026-08-11)

Destin drove the merged build at `:9300` against the real corpus and signed it
off ("this looks good. safe to merge"). **One defect came out of that session
and is fixed** — see below. What he did NOT do is walk the seven-item
checklist item by item, so treat the individual rows below as *unconfirmed
rather than failed*; they are worth a look next time someone is in there.

Automated, on the merged build: headless Chrome confirmed all five routes
render, `ai-fullpage` stays scoped to `/ai`, and **zero
`POST /api/conversations`** across every route — so the hoisted `useChat` is
genuinely inert on every page and H2's browsing-is-free holds.

Still worth eyes, none of it reachable by jsdom:

1. **Close the tab mid-turn** → the server should log the turn ending rather
   than streaming on. **This is P5, the only safety property in this change,
   and no test on this branch can reach it.** The highest-value unchecked item.
2. Deep Research streaming → leave to Budget Documents, wait, come back: no
   availability gate over the live answer.
3. Corpus switch mid-conversation → thread clears, tier back to Standard, and
   watch what an open source panel does (that is the second Minor below).
4. Add an API key to an install that had none, then visit `/ai` → watch for a
   stale "unavailable" flash (third Minor below).

### 🔴 The one defect browser testing found: two rows looked selected

`:hover` and `.is-active` both painted `background:var(--card)` — identical —
so pointing at any row in the history rail lit **two** rows and the rail
stopped answering the one question it exists to answer: which chat am I in?

Fixed by suppressing the ACTIVE row's highlight while the pointer is over some
other row (`.history-rail-list:hover .history-rail-item.is-active:not(:hover)`),
covering background, shadow AND the gold title colour. Re-tinting hover was
rejected: a second colour still leaves two lit rows. `:not(:hover)` is what
keeps the open chat lit when you point at it, the common case. The
rename/delete actions deliberately keep their opacity — they are an affordance,
not a selection signal, and hiding them mid-reach would move a click target out
from under the pointer.

Pinned by a spec in `chat-css-contract.test.ts` that also asserts the
**precondition** — that hover and active still share a background — so anyone
who later re-tints hover is told to re-read this rule rather than left with a
suppression that has silently stopped doing anything.

**This is the fourth time on this feature that something passed every test and
was wrong on screen**, after the three plan-code defects above. 742 vitest did
not see it; one minute of pointing at the rail did.

### Four known Minors, deliberately carried

- **A seam defect the parallel split created.** Deleting the row for a chat you
  reached by asking (so `selectedChatId` is null) leaves the "New chat"
  placeholder over a full thread: `chatDeleted` correctly does nothing, but the
  id vanishes from `chats` so the placeholder re-renders. Not data loss — the
  next send still works. The clean fix touches the P3 boundary, so it is
  written down rather than fixed blind.
- **`AiModePanel`'s own state now survives a corpus switch** (open PDF panel,
  composer draft, rail collapse), because only `ChatEngine` is keyed now. P6/P7
  read slightly false as a result. No wrong-corpus fetch is possible — the old
  chips are gone from the thread.
- **The verdict cache can show a stale definitive "unavailable"** where the old
  code showed "Checking…" — the admin-just-added-a-key case. Self-corrects on
  the round trip.
- ✅ **The unseen auto-title is FIXED 2026-08-22** (easy-wins batch), and the
  mechanism recorded here was wrong: the away case never needed a fix (the
  rail refetches on every `/ai` remount — the suggested provider hoist was
  investigated and is inert). The real gap was a timing race while the panel
  stays MOUNTED: `persist_turn` plus the blocking auto-title call run after
  the SSE stream closes, so the one bump always fetched before the title
  existed. A second bump now fires at `TITLE_GRACE_MS` = 21 s, DERIVED from
  `harness/titles.py::_TIMEOUT_S` (after which the title is final on every
  path) with an anti-drift spec reading that Python constant at test time.
  Known trade: a fast title still appears only at the ~21 s bump.

---

## Plan 7 — batch extraction: Tasks 1–4 shipped (2026-08-01)

Plan: `docs/superpowers/plans/2026-08-01-standalone-plan-7-batch-extraction.md`.
Measurement: `docs/superpowers/investigations/2026-08-01-mineru-batch-mode.md`.
Merges `71ac0ae` (runner), `6a78d64` (worker), `516542e` (spike), `10f7a50`
(poison-pill fix). **Default-off**: `JLBC_INGEST_BATCH` unset = today's exact
per-document behaviour, which is what made it safe to merge while the office
is live on the ingest path.

### Ground truth 2 of the plan was FALSE — found by the spike, as designed

**A truncated PDF aborts the ENTIRE `mineru -p <dir>` batch**, zero output for
every batch-mate. It fails in MinerU's pdfium preflight *before* any
extraction, so it costs ~3.3 s rather than a wasted batch — but at
`JLBC_INGEST_BATCH=40` one bad file would mark 40 documents failed.

Fixed by probing every candidate with **pypdfium2 before staging** and
excluding bad ones individually. **Do not "simplify" this to
`ingest.dispatcher._pdf_page_count`** — that uses PyMuPDF, which is more
tolerant than pdfium and therefore does not predict MinerU. Measured: a real
PDF cut to 90% of its bytes opens fine in PyMuPDF and reports all 6 pages,
while pdfium rejects it; **an HTML 404 body renamed `.pdf` reads to PyMuPDF as
a valid 1-page document**, and that is a shape azjlbc.gov has actually served.
Pinned by `test_the_probe_catches_what_pymupdf_would_have_waved_through`.

A second hazard the plan did not anticipate: zero-byte and garbage PDFs are
**silently dropped** by MinerU — `rc=0`, batch completes, filename never
mentioned in 46 log lines. Already covered, because `_demux_one` fails any
staged document that produced no output (the FY2024-AFR shape).

### Measured, not projected

**3.55×–4.64× at 20 documents** (~4.0× at the batch mean). Reported as a range
because the two batch runs disagree 23.5% — page-cache warmth on ~5.5 GB of
weights; the *second* was faster despite higher load. The serial half is
corroborated externally at 41.6 s/doc / 87 docs/hr against this file's
independently recorded ~40 s/doc / 93 docs/hr.

| batch | s/page | docs/hr | peak tree RSS |
|---|---|---|---|
| 1 (serial) | 10.67 | 87 | 3.9 GB |
| 5 | 3.19 | 282 | 4.5 GB |
| 10 | 2.38 | 378 | 5.1 GB |
| 20 | 3.01 / 2.30 | 307 / 401 | ~8 GB |
| 40 | 1.55 | 625 | 11.7 GB |

**No knee found** — 40 was the edge of the measurement, not a plateau.

**Two plan claims corrected.** `WORKERS=12 BATCH=20` is NOT runnable here
(12 × 8.1 GB ≈ 97 GB on a 121 GB box); use `WORKERS=4`. And "3.7 h → roughly
one hour" was optimistic — **~2 h is the defensible claim**.

**Extraction is not perfectly reproducible across batch sizes.** 17 of 20
documents were byte-identical; the 3 that differ do so by **exactly one
character** each in table HTML, with **every numeric token identical**. Isolated
by experiment, not guessed: batch-20-vs-batch-20 is 20/20 identical, while
batch-3 and both single-document forms agree with each other and all differ
from batch-20. So it is batch *composition*, not run-to-run noise. No dollar
figure moves, but a document's chunk text depends slightly on what it was
batched with.

### Task 4 — live validation, JLBC Baseline FY2021 (2026-08-01)

`WORKERS=4 BATCH=20`. **134 queued → 132 live, 2 failed, in 964 s = 500
docs/hr.** Peak memory 47 GB of 121 GB.

Both failures are **azjlbc.gov 404s** (`21baseline/legsen.pdf`, `otr.pdf`) —
the sources do not exist, not a code defect.

Audited rather than assumed: documents.json count == distinct doc_ids in
LanceDB (132 == 132), 0 duplicate chunk_ids, 0 chunks missing page or bbox,
0 documents with zero passages. **Chunks-per-page 3.52, dead centre of its
siblings (FY2022–27 span 3.24–3.66)**, and 0 documents in the FY2024-AFR
shape. Spot-read 3 documents: `adc` is Corrections, `acc` is Community
Colleges, `dps` is Public Safety — each document's text is genuinely its own,
which is the only check that catches a stem-collision demux bug.

**12 empty-text chunks (0.65%) are PRE-EXISTING, not a batch regression** —
proven by control: FY2022 0.45%, FY2023 0.46%, FY2024 0.58%, FY2025 0.53%,
all ingested without batch mode, all on page 2. (FY2026/27 have none.) Worth
its own look; not caused by this work.

**Ingest is per-machine and default-OFF since Plan 5 Track 4**, so a backfill
run must set `JLBC_INGEST_ENABLED=1` or the queue silently will not run.
`~/backfill-scripts/restart_batch.sh` does this.

### 🔴 A STOLEN INGEST LOCK NEVER HEARTBEATED — fixed, merge `6c7c19b`

**S6 single-writer invariant violation, observed live, not theorised.**
`IngestLock.acquire()` had two paths that take the lock; `_start_heartbeat()`
had exactly ONE call site, on the ordinary-create path. **The stale-steal path
set `_held = True` and returned without starting the beat.**

Consequence on the shared drive: a lock taken by stealing keeps its
`heartbeat_at` frozen at acquisition, so after the 120 s stale window **every
other machine correctly judges it stale and steals it while the first is still
writing** — two writers on one corpus. It is also **self-perpetuating**: once
one steal happens, each later holder also acquires by stealing, so the
heartbeat never runs again for that corpus's lifetime.

Found by accident: a mid-write server restart left a stale lockfile, the new
worker stole it, and the heartbeat then sat frozen for **866 seconds** while a
live holder did real work and 147 threads queued behind it. Neither existing
lock suite caught it because both exercised only the ordinary-create path.

Fixed with a single `_take()` helper both success paths call, deliberately
rather than a second `_start_heartbeat()` call — two paths independently
assigning `_held` is the *shape* that allowed the omission. Guard:
`tests/test_ingest_lock_heartbeat.py` (3 specs, verified failing before the
fix, incl. a rival that collected 13 successful steals against an expected 0).
Intra-process double-write was never possible — `_process_mutex` covers that —
so the exposure was strictly cross-machine.

### Task 5 — the backfill is DONE (2026-08-02)

**Every ingestable JLBC book edition is in the corpus.** 4,957 book documents
live, 7 failed — all of them azjlbc.gov 404s where the PDF does not exist.

| | session start | final |
|---|---|---|
| `budget_chunks` | 28,530 | **77,574** |
| documents | 3,533 | **7,434** |
| book editions | 11 | **38 (all ingestable ones)** |

Quality audited across all 21 editions, not assumed: **0 documents in the
FY2024-AFR shape** (<0.5 chunks/page) anywhere, 0 missing titles, and the seven
oldest editions (FY2005–2011) land at 3.65–4.84 chunks/page against the
pre-existing FY2022–27 range of 3.24–5.24. Spot-reads confirmed each document's
text is its own — the only check that catches a stem-collision demux bug.

**Snapshots restored to normal, bulk env discarded.** One fresh verified
snapshot (4.34 GB, 353 entries); the five stale pre-fix archives were deleted,
taking `backups/` from 54 GB to 4.1 GB.

### Task 6 — recency RE-CALIBRATED against the finished corpus (2026-08-02)

**`RECENCY_BOOST_PER_YEAR` 2.064 → 0.85, `REFUSAL_THRESHOLD` 1.04 → 1.46.**
Sweep `eval/results/recency-sweep-2026-08-02T1101Z-c9c16b7.json`; eval
`eval/results/2026-08-02T1109Z-f7ff858.json`.

**Verified the instrument BEFORE trusting it:** 0 of 61 ground-truth chunk_ids
across all three query sets had gone missing. The backfill was purely additive
(`source_url` dedup), so none of the 41%-fallback damage of the last re-ingest
recurred.

| weight | recall@5 | chronological order |
|---|---|---|
| 0.000 | 73.8% | 59.1% |
| 0.700 | 73.8% | 91.0% |
| **0.850** | **73.8%** | **92.5%** |
| 1.000 | 71.4% | 93.4% |
| 1.169 | 71.4% | 94.1% |
| 2.064 (was shipped) | 69.0% | 97.7% |

**0.85 is the largest weight that costs NOTHING** — recall@5 identical to the
boost being off, while ordering clears the 90% target. The cliff starts at 1.0.

**The sweep's own recommendation (1.169) was GRID-LIMITED, not principled.**
`sweep_recency` derives its grid from the score spread — 13 steps of 0.585 here
— so 0.70 and 0.85 were never tested and the smallest grid point clearing 90%
won by default. **Always pass an explicit `--weights` grid before believing the
recommendation it prints.**

**Why the old 2.064 was wrong:** it was picked by the same "costs nothing" rule
on 2026-08-01, but against an eval set where 32 of 34 queries named a year and
never executed the code. The flat recall column justifying it was evidence the
set never ran the boost, not evidence of safety.

**The coupling bit in the counter-intuitive direction, and the guard caught
it.** LOWERING the weight RAISES `top_score` (a smaller penalty depresses less),
so the threshold had to go UP. Refusal query q-030 went −1.17 → +1.42 and
answered a question it should have refused until 1.46 landed.
`test_the_shipped_weight_and_refusal_threshold_move_together` failed exactly as
designed.

**Final eval: recall@5 73.81%, recall@15 97.62%, recall@20 97.62%, refusal
precision 60%, p95 852 ms. Gate G1 passes.** recall@5 is up 7.1 points on the
same corpus.

**One genuine regression, and it is the CORPUS, not the weight.** `q-009` was
passing at rank 17 and its ground truth now sits outside the top 20, pushed
out by a newly-ingested FY2024 document. `cur@20` is 97.6% at weight **0.000**
too, so switching the boost off would not recover it. Re-point or accept that
query; do not read it as a ranking regression.

### 🔴 THE PDFIUM PROBE WAS NOT THREAD-SAFE — it failed 224 VALID PDFs

**Introduced by the poison-pill fix earlier the same day, caught in the live
run.** `pypdfium2` has global state and is not thread-safe. The pre-stage probe
runs inside `run_batch`, which runs on a worker thread, so at
`JLBC_INGEST_WORKERS=4` several threads probed concurrently, corrupted pdfium,
and rejected **perfectly valid** PDFs with `PdfiumError: Data format error`.

Proven, not inferred: all 224 rejected files open fine single-threaded, and
their mtimes showed they had been byte-final on disk since 2026-07-31 — two
days before the failure. Nothing was wrong with the files.

Reproduced on demand with the same 80 real PDFs in one process:

| | failures |
|---|---|
| serial | **0 / 80** |
| 4 threads | **60, 80, 80 of 80** |

Fixed with `_PDFIUM_MUTEX` around the whole open→count→close sequence, mirroring
`_EMBED_MUTEX`. Merge `71e85a7`.

**The regression test is size-dependent and that matters.** With the suite's
existing 662-byte fixture PDFs the unlocked code passed 0 failures out of 600 —
a test that would have proven nothing. The guard only arms at realistic file
sizes, so the fixture is 500 pages (~62 KB, the real corpus median) and the
docstring says never to shrink it for speed.

**Office exposure was nil** — the default is one worker. Only parallel
backfills could hit this.

### 🔴 SNAPSHOTS ARE THE INGEST BOTTLENECK, and Task 5's premise was wrong

Plan 7 Task 5 says per-batch snapshots removed the O(n²) that justified
`JLBC_INGEST_SNAPSHOT=off`. **They did not — they moved it.** Per-batch cut the
count from ~3,775 to 29, but `store/backup.py::snapshot()` zips the WHOLE
corpus with single-threaded Python `ZIP_DEFLATED` **while holding the ingest
lock**, and the corpus grows all run.

Measured 2026-08-01 mid-backfill:

| symptom | measurement |
|---|---|
| snapshot archives | 2.3 → 10.8 → 16.8 → **17.4 GB**, one per edition |
| lock held per snapshot | 7–15 min, single core, all other workers blocked |
| corpus on disk | **13 GB for 37,709 rows** |
| live LanceDB versions | **522** |
| throughput with snapshots on | 370 docs/hr |
| throughput with `SNAPSHOT=off` + `RETENTION=2` | **727 docs/hr**, corpus 12.5 → 6.1 GB while running |

**Root cause of the 13 GB is version pileup, not row count.** `optimize()`
prunes versions older than `JLBC_LANCE_RETENTION_MINUTES` (default 10). Writes
land every ~1.3 s during a bulk run, so ~460 versions are always inside the
window — 522 observed is arithmetic, not a defect in `optimize()`.

**Bulk-run settings are supervised-only and live in the environment** (they die
with the process). `~/backfill-scripts/restart_batch.sh` sets both with the
reasoning inline. **Do NOT make the 2-minute retention an office default** —
the prune compares version timestamps against the *pruning* machine's clock and
~20 machines read this corpus off a shared drive.

**This DOES degrade the OFFICE experience, now measured rather than predicted.**
The final post-backfill snapshot — a healthy corpus at normal retention, not
the bloated one — took **3 minutes 30 seconds** to zip 4.7 GB into 4.34 GB, one
core, single-threaded. In the office that is what one analyst uploading one
document costs: a 3.5-minute apparent hang with the ingest lock held, growing
with the corpus. Office write rates will not pile up 500 versions, so the
corpus stays smaller there — but zip-the-whole-corpus-per-write does not scale.
An incremental or copy-on-write snapshot is the real fix. **Follow-up, not
done, and it should be done before the office relies on uploads.**

---

## Plan 5 Track 4 (cleanup) — shipped (2026-08-01)

Tasks 18–20 plus the three orphaned bundle requirements. Handoff:
`PROMPT-plan5-track4-cleanup.md` (now retired — do not execute).

**Plan 5 is 20 of 27 tasks done.** Remaining: Track 5 (handbook, 21–23) and
Track 6 (gates, 24–27).

### Task 18 — the retired architecture is GONE

`web/`, `mcp-server/`, `db/`, and `retrieval/{api,bm25,dense,rerank,sql}.py`
plus their suites: **~36,000 lines deleted.** Every directory in the repo is
now live code.

`setup.sh` went from eight steps to four. It used to run `npm ci` twice, a
tsc build, and 277 vitest specs across two directories Plan 4 retired, plus
bring up a Postgres container and run `db.validate` against it — on every
fresh clone, including the G3 cold-start install.

**The known test-isolation defect is gone with it, not worked around.**
`setup.sh` sourced `.env.local` before pytest, which leaked `DATABASE_URL`
into the process and un-skipped the Postgres suites mid-run against a schema
they did not own. Both the suites and the sourcing are deleted.

- **`eval/synthesize_queries.py` was PORTED, not deleted** — eval-set
  expansion is a live Phase 3 need. Both samplers pushed their randomness
  into SQL (`ORDER BY RANDOM()`, a self-join for comparison pairs) and
  LanceDB has neither, so the sampling happens in Python over one projected
  scan. Adds `--corpus fiscal_note_chunks`. Verified against the real corpus:
  25 seeds balanced across all four publishers, 5 valid cross-FY pairs.
- **`retrieval/sql.py` was not on the deletion list but is orphaned by it** —
  its only consumers were bm25.py and dense.py. `tests/test_retrieval_sql.py`
  became `test_retrieval_types.py`: half of it covered `RetrievedChunk.from_row`,
  which is still live (search_lance.py builds RetrievedChunk from Lance dicts —
  same column names psycopg rows had, which is why the adapter survived).
- **`docs/corpus-recovery.md` advertised a one-command recovery** running a
  script this deleted. Rewritten: the acquisition trail is still what makes
  recovery possible, but the flow is manual and now says so, and the two
  recovery-posture checks are re-expressed against `documents.json`. Verified
  on the live corpus — 0 missing `source_url`, 0 out-of-tree paths.

> ⚠ **THE ONE REAL CAPABILITY LOST.** `eval/refresh_chunk_ids.py` was the tool
> that re-bound stale eval chunk_ids after a re-ingest. It never ran against
> LanceDB and was deleted per the handoff. **Nothing replaces it.** What
> absorbs the damage is `eval/scoring.py`'s dimensions fallback — which is
> loose, and can credit a different chunk of the same document. `anchor_text`
> is still recorded for every expected chunk and is the manual repair path.
> **This bit within hours** (see the eval note below). Written up at
> `eval/README.md` → "After a re-ingest", `eval/schema.py` and `eval/scoring.py`.

**Verified from a FRESH CLONE, not the working tree:** `bash setup.sh --verify`
→ **exit 0**, 1559 pytest + 426 vitest, four steps.

### Task 19 — one `documents.json` reader

`store/documents.py` replaces what the brief called four readers and was
actually **five** — `app/routes/admin.py::_document_count()` hand-rolled its
own parse that nobody had listed. They had already drifted three ways, and
each divergence is preserved deliberately rather than averaged away:

1. **mtime resolution** — one stamped float seconds, one nanoseconds.
   Nanoseconds wins; a rewrite inside one filesystem tick is what a fast
   local ingest looks like, and the float version served stale titles with no
   symptom.
2. **corrupt-file policy** — read paths degrade to `{}` so search keeps
   working; the WRITE path RAISES. Not fastidiousness: the writer does a
   read-modify-write, so degrading there writes a sidecar containing one
   document and orphans every PDF in the viewer.
3. **the `ingested_at` title gate — OPTIONAL, defaulting OFF.** Measured
   before choosing: 378 live documents lack `ingested_at`, and gating them
   turns *"JLBC FY2027 — AHCCCS"* into *"JLBC Baseline FY 2027 Axs"*. The
   gate is right on the search page (mockup index is primary, this is the
   tiebreak) and wrong in AI Mode (sidecar is the only source, and an ugly
   title lands in the ANSWER). **A consolidation that picked one policy
   would have silently degraded 378 documents.**

Also `GET /api/corpus/counts` (ungated — it feeds a footer every analyst
sees) and the footer states a true corpus size again: **3,527 documents /
24,841 budget chunks / 13,278 fiscal-note chunks**. The number renders only
once the server has answered; first paint and a failed fetch both show
nothing rather than guessing.

### Task 20 — the remaining ingest defects

| Defect | Evidence |
|---|---|
| **Dead LanceDB versions never pruned** | Live corpus measured at **1.91 GB on disk holding 0.14 GB of live data**, 105 versions. `optimize()` *was* pruning — `cleanup_older_than` just defaults to **seven days**, so on a bulk run where every version is minutes old it pruned nothing and returned successfully. Retention now 10 min (`JLBC_LANCE_RETENTION_MINUTES`). Measured 98% reclaimed on an ingest-shaped run. |
| **`DownloadCache` concurrency** | Per-instance tmp path, a lock, and — the part locking alone would not have fixed — **re-read-merge-write**, because each instance wrote its own in-memory copy back wholesale. Verified on the REAL 7,482-entry manifest: 12 concurrent writers, zero lost. |
| **`IngestLock` heartbeat** | `_write` beat before `write_doc`, not during; `build_fts_index` + `optimize` will pass the 120s window as the corpus grows, so a **live, healthy writer** gets its lock stolen. `acquire()` now runs a daemon beat at ¼ the stale window. Verified at production ratios: held through a 6s write against a 2s window, rival judged it stale 0 times in 22 checks. |
| **Per-batch snapshots** | One restore point per book edition / note session instead of per document — 1 zip instead of ~130. `JLBC_INGEST_SNAPSHOT=off` still wins outright. |

Two chosen defaults worth not re-litigating: the version retention is **10
minutes, not 0**, because ~20 machines read this corpus and the prune compares
version timestamps to the *pruning* machine's clock; and `delete_unverified`
stays False because LanceDB's own docs say it is only safe when no other
process is touching the dataset, which a shared drive cannot promise.

### The three orphaned bundle requirements — now built

Session B filed four; Session A merged with two unbuilt and one half-noted.
(`docs/superpowers/investigations/2026-08-01-bundle-app-requirements.md`.)

- **Per-machine `ingest_enabled`, default OFF.** One bundle on ~20 PCs and
  `launcher.pyw` calls `create_app()` with no arguments, so all twenty would
  start a worker on one queue. Resolution order mirrors the data dir:
  `JLBC_INGEST_ENABLED` > `machine.json` > False. A machine.json without the
  key reads as False (that is install.cmd's file — silence is not consent);
  an unrecognised env value falls through to the FILE, because a typo on the
  one machine doing the work would otherwise stop the office silently.
  **`set_data_dir` is now read-modify-write** — it wrote `{"data_dir": …}`
  wholesale, so using the repair screen would have switched off the ingest
  machine.
- **The "nobody is processing uploads" warning**, which is not optional: OFF
  by default re-creates the silent pile-up the one-bundle decision existed to
  avoid. Fires only when something is queued AND nothing is running AND
  ingest is off here. The server owns both the decision and the sentence.
- **`python -m app.machine_config`** so `install.cmd` stops hand-writing JSON.
  Silent exit 0 on success; a validation failure is a WARNING and **still**
  exit 0, because a network drive that is not connected during setup is
  normal and refusing to record the path would strand the user.

### Eval — retrieval-neutral, but the corpus moved under it

**recall@5 62.07%, recall@15 96.55%, recall@20 100%, p95 832ms. Gate G1
passes.** recall@5 is 21 points below the last recorded run and **none of it
is Track 4** — proven by control, not asserted: the same eval on
`origin/master` with none of this branch's code, same corpus, produced
identical figures (`eval/results/2026-08-01T0934Z-6cd522e`). Nothing here
touches ranking.

**The fallback rate is 41% of passes** — two in five ground-truth chunk_ids
no longer resolve and are matching on dimensions instead. That is the
re-ingest hazard above, arriving within hours because the parallel session's
User-Agent fix re-fetched and re-ingested documents. **Do not read 62% as a
retrieval regression; re-point the stale chunk_ids first.**

### Found and fixed on the way (neither caused by Track 4)

- **Three `/api/me/usage` specs went red at midnight.** They seeded a
  hardcoded `2026-07` shard and called an endpoint that always reads the
  CURRENT month, so they passed only while the wall clock was in July.
- **`test_the_query_set_is_honestly_marked_as_unbaselined` was red on
  `origin/master`** — the parallel session filled in fiscal-note ground truth
  but left the guard asserting the old "NOT YET FILLED IN" marker. Re-pointed
  at the DRAFT / PENDING HUMAN REVIEW banner the file now carries; the
  property it protects is unchanged.

### Follow-ups this work created

- **`pyproject.toml` still DECLARES the retired stack** even though the tree
  is gone: `psycopg`, `pgvector`, `voyageai` have zero importers, and
  `python-dotenv` had exactly one (`retrieval/api.py`, deleted). Not dropped
  here on purpose — it changes the wheel closure that Session B's 3.33 GB
  bundle was verified against on real Windows hardware, and that verification
  cannot be re-run from this machine. **Whoever next rebuilds the bundle
  should drop them and re-verify.** `psycopg` has one remaining consumer,
  `scripts/migrate_to_lancedb.py`, kept as the migration-era record.
- **Provenance comments across ~35 files cite `web/…` paths** ("ported from
  web/components/ChatThread.tsx"). They resolve against git history and are
  honest attribution, so they were left alone; CLAUDE.md now says so
  explicitly, with the `git log --diff-filter=D` incantation that recovers
  the deleted trees.
- **The admin queue warning and ingest toggle are unverified in a real
  browser.** Same gap Session A recorded for the rest of that page.
- **`data/cached-pdfs/` vs `<data_dir>/pdfs/` is still two homes for the same
  bytes** — untouched here (it is a decision, not a defect).

---

## Plan 5 Track 3 (packaging) — shipped, running on Windows (2026-08-01)

Session B of the three parallel Plan 5 sessions. Tasks 14–17 complete. Merges
`92028c5`, `74747e9`. (Written while Session A was still in flight — Tasks 1–13
have since landed; Tasks 18–27 remain. Two of the four app-side requirements
this track filed are still unbuilt: see the Session A section below.)

**The bundle exists and runs.** `python packaging/build_bundle.py --version X` produces
`dist/JLBC-Insight-X.zip` — **3.33 GB unzipped / 2.11 GB zipped**, 36,102 files —
containing an embeddable CPython, the Windows wheel closure, a vendored Temurin JRE, the
app source, the built SPA, and every model weight pre-seeded. **It builds on Linux**;
`uv` resolves real Windows wheels for a foreign platform and everything else Windows-
specific is a download rather than a compile.

**Verified on Destin's work laptop, 2026-08-01** — a machine that had never had Python,
standard user account, no admin rights: all 36,102 files extract; the full core and
ingest closures import; `app.main` imports; the bundled JRE runs; `install.cmd` completes
with no elevation and no endpoint-security prompt; the shortcut starts the server and
serves the SPA; several clicks leave exactly one `pythonw.exe` (S8 relaunch-reuse);
and **the acceptance criterion passed — an offline cold start with WiFi disconnected.**

**Shape decision: one bundle everywhere** (~20 PCs), not the split the plan hedged
toward. Vendoring a 47 MB Temurin JRE removed the need for an IT request for Java, which
was the split's main argument; ~500 GB free per machine removed the disk argument. Two
artefacts would have meant somebody eventually installing the search-only one on the
ingest machine, with uploads queueing forever and no error anywhere.

**S8 amended 2026-08-01:** the launcher opens an ordinary browser tab, not Chrome
`--app` mode. Reversed within seconds of the first real user seeing it — this is a
reference tool used alongside a dozen research tabs, not a program you live inside.

**Four findings the plan did not anticipate**, all handled, all detailed in
`docs/superpowers/investigations/2026-08-01-bundle-size.md`:
- `opendataloader-pdf` shells out to `java` and bundles no JRE → JRE vendored
- `mineru==3.1.6` cannot resolve wheel-only (`antlr4` 4.9.x is sdist-only) → one
  pure-python wheel pre-built at build time. **`>=3.1.6` silently resolves to 3.4.4**,
  which un-declines the corpus-wide re-ingest the plan rejected; it is pinned
- `tiktoken` downloads its encoding at runtime and **fails soft** to different chunk
  boundaries → cache pre-seeded, `TIKTOKEN_CACHE_DIR` set by the launcher
- fastembed's model cache defaults to `%TEMP%`, which Windows deletes → `FASTEMBED_CACHE_PATH` set

**Open, blocking nothing:**
- **Real retrieval is untested.** Every Windows run so far had an empty data dir, where
  `create_app()` serves stub fixtures. Needs the 4.9 GB corpus copied to the laptop —
  deferred while the backfill is writing to it.
- ~~Session A owes two changes~~ ~~`install.cmd` writes `machine.json` by hand~~
  **ALL THREE BUILT in Track 4, 2026-08-01** — per-machine `ingest_enabled`
  (default OFF), the "nobody is processing uploads" admin warning, and
  `python -m app.machine_config`, which `install.cmd` now calls instead of
  emitting JSON by hand. See the Track 4 section above.

## Z13 backfill — COMPLETE (2026-07-31 → 2026-08-02)

Runbook: [`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md). Spec: S20 (scope),
S21 (recency). **Historical live-run record — the run is COMPLETE.** The
backfill itself finished **2026-08-02** and the recency re-calibration
(Phase D) landed the same day; see the phase summary's "Volume ingest / S20
backfill" row and the Plan 7 section for the finished state and the shipped
`RECENCY_BOOST_PER_YEAR 0.85` / `REFUSAL_THRESHOLD 1.46`.

**Machine:** Ryzen AI MAX+ 395, 32 threads, 121 GB RAM, Linux. Repo at
`~/YouCoded/Projects/ask-the-budget-az-dev`, corpus at `data/insight-data/`.

| Phase | State |
|---|---|
| A — setup + parity gate | ✅ **PASSED**, exact reproduction of the Windows baseline: recall@5 72.41 / @15 96.55 / @20 100.00, refusal precision 40.00. Latency p95 **821 ms vs 3,187 ms** on the office box (3.9× faster). Results committed. |
| B — recency machinery (S21) | ✅ **MERGED** (`4c75f2c`). Year-parser hard filter + `inferred_fiscal_years` + recency boost shipped OFF (0.0) + prompt guidance. **Eval improved to recall@5 82.76% (+10.35pp) and refusal precision 60% (+20pp)** from the year filter alone. |
| C — the backfill | ✅ **DONE (2026-08-02).** Every ingestable JLBC book edition is in the corpus — 38 editions, 7 failures all azjlbc.gov 404s. (The "~65% fiscal notes, books not started" text that used to sit here was the mid-run snapshot.) |
| D — calibration | ✅ **DONE (2026-08-02).** `RECENCY_BOOST_PER_YEAR` 2.064 → **0.85**, `REFUSAL_THRESHOLD` 1.04 → **1.46**; sweep + eval committed under `eval/results/recency-sweep-2026-08-02T1101Z-*` and `eval/results/2026-08-02T1109Z-*`. Recall@5 up 7.1 points on the same corpus. See Plan 7 Task 6. |
| E — wrap | ✅ Canonical corpus declared; this run is recorded and closed. |

**Corpus right now:** `budget_chunks` 7,808 · `fiscal_note_chunks` 8,438 ·
1,770 documents (was 382 / 7,755 / 0 notes at the start).

**Throughput work done during the run** (all merged; measured, not estimated):

| change | effect |
|---|---|
| Bulk snapshot mode (`JLBC_INGEST_SNAPSHOT=off`) | 89 → 96 docs/hr and, more importantly, flattened an O(n²) decay curve |
| Parallel ingest (`JLBC_INGEST_WORKERS`, merge `f4ddf1d`) | 95 → 700 docs/hr at N=8, 840+ at N=12 |
| Worker cap raised 8 → 16, sized from measured CPU draw (`502841b`) | knee is ~8; N=12 is the practical setting |
| Thread-unique job temp files (`1f63393`) | closed a save() race that failed 1 document per ~100 at N=14 |
| **Net** | **95 → ~945 docs/hr (10×); remaining work 67 h → ~6 h** |

**Live operating config** (all three processes detached, restartable via
`~/backfill-scripts/restart_stack.sh <workers> <omp> <shared_mineru>`):
`JLBC_INGEST_WORKERS=12`, `JLBC_INGEST_SNAPSHOT=off`, `OMP_NUM_THREADS=3`,
shared mineru-api DISABLED. Progress log: `~/backfill-progress.log`.
Restore points: `~/pre-backfill-corpus.zip` (pre-run) and
`~/corpus-before-parallel.tgz` (1.5 GB, pre-parallel, 2,956 notes in).

**Data quality verified under 8-way and 12-way parallelism** (audited, not
assumed): documents.json count == distinct doc_ids in LanceDB; 0 documents
with zero chunks; 0 orphan chunks; 0 duplicate chunk_ids; 0 rows missing page
or bbox; 93/93 sampled titles real and content-derived. 1 known
zero-passage document — azleg.gov published a literal test file
("THIS IS A TESTT"), not an extraction failure.

---

## Standalone consolidation — Plan 1 shipped (2026-07-30)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(decisions S4/S5). Plan: `docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md`.

- **Store:** new `store/` package — embedded LanceDB at `<data_dir>/lancedb`
  (`JLBC_DATA_DIR` env override; dev default `data/insight-data/`, gitignored).
  Vector search (cosine) + native Lance BM25 FTS + DataFusion filters, one
  table per corpus (`budget_chunks` live, `fiscal_note_chunks` reserved for
  Plan 3). No server, no Docker on the retrieval path.
- **Models (local ONNX via fastembed, CPU):** embeddings
  `snowflake/snowflake-arctic-embed-m` (768-dim, query-instruction prefix
  applied query-side), reranker `Xenova/ms-marco-MiniLM-L-12-v2`. Fused
  RRF pool lowered 50 → 20 so the rerank stage stays ≤ ~3s interactive
  (measured 2.7s mean / 3.1s max at 20; 4.9s at 50).
- **Score scale changed:** reranker scores are raw cross-encoder logits
  (≈ −10..10), not Voyage's 0..1. No-results sentinel is
  `NO_RESULTS_TOP_SCORE = -1e9` (0.0 would outrank a genuinely-bad hit).
  Refusal threshold recalibrated 0.65 → **1.9** in
  `mcp-server/system-prompt.md` (sweep: precision 0.67 / recall 0.40 /
  pass-rate 0.97).
- **Gate G1 — passed as amended.** The original gate (recall@5 ≥ 0.80)
  was missed by both local embedder candidates (best 0.69–0.72; every
  local cross-encoder ranks worse than Voyage rerank-2.5) and the
  plan's stop rule fired. Destin reframed G1 mid-execution (spec commit
  `835900f`): **recall@15 ≥ 90% and recall@20 ≥ 95%**, with recall@5
  tracked and reported in every run so the gap stays visible. Final
  numbers: recall@5 72.41%, recall@15 96.55%, recall@20 100%, latency
  p95 ~3.0s (Voyage baseline: 86% / — / 100%, p95 2.6s). **Future
  sessions: the recall@5 gap vs the Voyage baseline is a known,
  accepted trade — do not rediscover it as a regression.** The consuming
  model reads all 15 returned chunks, which is what the amended gate
  measures.
- **Migration:** `scripts/migrate_to_lancedb.py` (one-time; re-runnable;
  `--docs-only` refreshes metadata without the ~50-min re-embed).
  Chunk_ids preserved verbatim; eval ground truth unchanged. G2 spot
  checks: exact chunk-id parity, 60-row full-column diff clean,
  provenance (page+bbox / source_anchor) intact corpus-wide.
- **Sidecar (`retrieval/api.py`):** same endpoints/shapes on LanceDB —
  no `VOYAGE_API_KEY`/`DATABASE_URL`; preflight = data-dir writable +
  corpus non-empty; `/health` reports `corpus_chunks`,
  `documents_metadata`, and returns 503 `degraded` with the real error
  when the store is unreachable. `top_k` validates ≥ 1 (422).
- **documents.json:** per-doc metadata sidecar (title, source_format,
  source_blob_path, source_url) written by the migration next to
  `lancedb/`. This is what lets the web PDF viewer open sources; if it's
  missing, `/health` shows `documents_metadata: 0` and
  `migrate_to_lancedb.py --docs-only` regenerates it in seconds. Titles
  fall back to a doc_id humanizer when absent.
- **Eval harness:** now computes recall@15 alongside 5/20;
  `calibrate_refusal.py` derives its sweep grid from the observed score
  distribution (survives future model swaps); a crashed retrieve can no
  longer masquerade as a confident refusal.
- **Still Postgres/Docker:** ingest only (until Plan 3). Legacy modules
  (`retrieval/bm25.py`, `retrieval/dense.py`, `retrieval/rerank.py`,
  `db/`) stay in-tree unused; removal is Plan 5.
- **Known follow-ups:** web PDF route can't distinguish "metadata
  missing" from "actually DOCX" (415 either way — Plan 2 web-side fix);
  lancedb `table_names()` deprecation (pagination-shaped `list_tables()`
  migration pending); stale data-file versions accumulate after
  `optimize()` (`cleanup_old_versions` not exposed — matters for the SMB
  share); ingest-side title quality is poor for a few docs ("GOVERNOR
  FY2027 fy2027") — Plan 3; expose fastembed `parallel=` for faster bulk
  re-embeds — Plan 3; PRE-EXISTING test-isolation debt (predates Plan 1,
  verified on pre-merge master): when `.env.local` exists, dotenv loading
  during the api tests leaks `DATABASE_URL` into the process env, which
  un-skips the legacy Postgres suites (test_connection/test_loader/
  test_embeddings) mid-run and they fail with UndefinedTable against a
  schema they don't own — run suites without `.env.local` (fresh-clone
  behavior) or fix the skip gates to snapshot env at collection time.

---

## Standalone consolidation — Plan 2 shipped (2026-07-30)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S1, S9, S12). Plan: `docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md`
(its frozen API-contract block is what Plans 3/4 build against — note the
Task 3 amendments recorded there: `fiscal_note_url` on bills, real
`leg_session()` names, non-unique `bill_number`).

- **App server (`app/`, port 9300):** FastAPI factory serving the built SPA
  (SPA fallback for client-side routes, JSON 404s under /api/, traversal-safe
  static serving) + `POST /api/search` + `GET /api/fiscal-notes` + `/health`.
  Provider seam: `_default_provider()` probes the LanceDB corpus once at
  startup — real `LanceSearchProvider` (Plan 1 stack) when `budget_chunks`
  has rows, fixture `StubSearchProvider` otherwise with the reason on stderr.
  Startup-only by design: a share outage mid-session surfaces as an honest
  JSON 503 from the search route, never a silent swap to fake rows. Run:
  `uv run uvicorn app.main:create_app --factory --port 9300` (set
  `JLBC_DATA_DIR` for a non-default corpus location).
- **Webapp (`webapp/`):** Vite + React 18 SPA ported from the JLBC Website
  Revamp mockup per S12 (verbatim `:root` tokens; page-scoped CSS convention
  documented in `webapp/src/styles/app.css` — the three mockup sources
  conflict on ~74 shared selectors). Pages: Home (hero search + gateway
  cards), Budget Search (see next bullet), Fiscal Notes (28-session /
  2,126-bill directory from the committed snapshot — Plan 3 swaps in the live
  corpus behind the same contract; safe `<strike>/NOW:` title rendering;
  session rail tuned live with Destin).
- **Budget Search — FINAL UI (iterated live with Destin 2026-07-30; the
  "As shipped" section of the Plan 2 doc + the spec's S12 amendment are the
  baseline for Plans 3/4/5):** results group by report family; each card =
  a linked headline row (best agency document, title ONLY — the mockup
  index's display title via exact source-URL join, 373/382 docs; `doc_url`
  from Plan 1's documents.json; "Open" pill; NO relevance display — number
  and bar both removed, ranking speaks through result order) → a collapsed "Matching
  passages" card (snippets + page pills, `data-chunk-id` stubs for Plan 4's
  viewer) → a bottom "Part of the FY YYYY <family>" card with collapsed
  sibling documents and the **Full report** chooser (the mockup's modal:
  Linked TOC vs Single File PDF, hand-verified URLs per family in
  `webapp/src/reportFamilies.ts`). NO publisher pills, NO taglines, NO
  percentages (removed at Destin's direction). Filters: publisher chips +
  curated type buckets + FY dropdown; retry + stale-while-revalidate states.
- **Fiscal-notes snapshot:** `scripts/export_fiscal_notes_snapshot.py`
  (parser transcribed from the vendored mockup generator) → committed
  `app/data/fiscal-notes-snapshot.json`, exact-count pinned (28 / 2,126).
- **Vendored references:** `webapp/reference/` now holds the mockup pages
  (including the GENERATED `subpage-fiscal-notes.html` — base.html's body is
  a superseded scaffold, do not port from it) plus the mockup's in-browser
  search engine (`assets/search/search.js` — report families, curated
  buckets, ranking blend) and its 419-doc URL index (`index-lite.js`), kept
  as input for retrieval tuning and the report-format chooser follow-up.
- **UI score display:** none — scores (raw cross-encoder logits) drive
  ordering only; the relevance number and bar were both removed at Destin's
  direction (2026-07-30).
- **Tests:** 24 app pytest (`tests/test_app_server.py`, `test_search_route`,
  `test_fiscal_notes_route`, `test_fiscal_notes_snapshot`,
  `test_lance_provider`) + 39 webapp vitest. `setup.sh` now installs/builds
  `webapp/` and `--verify` runs its suite.
- **Known follow-ups:** book-vs-agency-page open actions SHIPPED as external
  azjlbc.gov links (agency rows via the sidecar URL, whole books via the
  chooser modal) — the remaining piece is Plan 4 swapping them to the in-app
  viewer over `pdfs/` (offline-first per spec S7); doc titles come from the
  mockup-index URL join (373/382 docs) with the slug humanizer covering the
  9 unmatched — Plan 3's ingest should write real titles into
  `documents.json` for docs the website never indexed; filter-chip counts
  need a facets endpoint (corpus-wide numbers, not per-search); Nunito is
  named but never loaded by the mockup (one `<link>` if the approved look
  was really Nunito); `db/migrations/0001` doc_type enum comment is stale
  vs live data (`baseline-agency` vs `baseline-per-agency`).

---

## Standalone consolidation — Plan 3 shipped (2026-07-31)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S6, S7, S10, S17, Invariant 8). Plan:
`docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md`.

**Postgres and Docker are now needed for NOTHING.** They were ingest-only
after Plan 1; ingest no longer touches either. The legacy `db/` modules stay
in-tree unused (removal is Plan 5), and `scripts/migrate_to_lancedb.py`
remains as the migration-era record.

- **Queue (`ingest/`):** `jobs.py` (one JSON file per job under
  `<data_dir>/jobs/`, atomic writes, state machine, crash-resume),
  `lock.py` (SMB-safe single-writer lock via exclusive-create + heartbeat
  stale-steal — S6), `worker.py` (one daemon thread in the app process:
  extract → chunk → embed → write), `mineru_runner.py` (streamed per-page
  progress, timeout, cooperative cancel that kills the child, `JLBC_MINERU_*`
  offline pinning — S7), `lance_writer.py` (Chunk→Arrow row, idempotent
  per-doc replace, documents.json merge, real titles), `validate.py`
  (advisory post-ingest checks ported from `db/validate.py`).
- **Resume granularity is the stage, and inside extraction the page range.**
  MinerU runs 1–3 min/page on an i5-1245U, so a 210-page book is an overnight
  job that WILL be interrupted. Extraction output lands on the share
  (`<data_dir>/extractor-output/<doc_id>/`) so any machine can continue.
  Chunking and embedding are re-derived rather than journalled — minutes, not
  hours.
- **Write phase, every time:** ingest lock → S17 `snapshot()` →
  `delete_doc` → `upsert_chunks` → `build_fts_index` → `optimize` →
  documents.json merge. The FTS rebuild is not optional: new rows are
  invisible to BM25 without it, which looks like a working ingest with
  silently broken keyword search.
- **Upload API + page:** `POST /api/upload` (multipart) with the Invariant 8
  gate enforced SERVER-side (400 without the public-record confirmation),
  content-hash dedup against both documents.json and pending jobs (409 with
  when/who + an explicit re-process option), `GET /api/jobs`,
  retry/cancel. `webapp/src/pages/Upload.tsx`: always-visible Invariant 8
  notice, required checkbox, filename-heuristic metadata form, live queue with
  per-stage progress. Copy states the real cost — "large books process
  overnight" — deliberately not softened.
- **Real titles.** `build_title()` retires the migration's
  "GOVERNOR FY2027 fy2027" strings for new ingests, and
  `app/search_provider.py` now consults documents.json's title (gated on
  `ingested_at`, so migration-era junk titles still lose to the humanizer) and
  re-reads the sidecar when its mtime changes. Both gaps were found by the
  end-to-end run, not by a test.
- **Fiscal notes are live (S10).** `POST /api/fiscal-notes/refresh` queues a
  `refresh`-kind job that scrapes `azjlbc.gov/fiscal-notes/?Year=`, diffs
  against the directory, downloads only new note PDFs, and feeds them to the
  normal queue. `GET /api/fiscal-notes` now serves
  `<data_dir>/fiscal-notes-directory.json` when present (mtime-checked; the
  Plan 2 `lru_cache` is gone — it would have pinned the pre-refresh copy for
  the process lifetime) and falls back to the committed snapshot otherwise, so
  a fresh install shows 28 sessions on day one. Scraper breakage degrades to
  last-good LOUDLY: a session that returns zero rows when notes are already on
  file fails the refresh instead of deleting them. The FiscalNotes rail's
  reserved search box is now a real semantic search over `fiscal_note_chunks`,
  disabled until the corpus reports passages.
- **Add a JLBC book (Task 15).** `data/jlbc-book-sources/` vendors the website
  mockup's verified URL harvest (read-only, snapshot 2026-06-16);
  `scripts/build_book_catalog.py` turns it into the committed
  `data/jlbc-book-catalog.json` — **41 approps (FY1984–2026) + 21 baseline
  (FY2007–2027) editions**, pinned by test. `ingest/book_discovery.py` is
  catalog-first (zero network on a hit) and falls back to a HEAD-verified
  candidate ladder for editions published after the snapshot, walking BOTH the
  agency index and the linked TOC (their children are disjoint). Dead hosts
  rewritten, URLs never re-encoded, case-insensitive dedupe, and a rolling
  `/budget/` guard that refuses an index whose links belong to another year.
  `GET /api/books/catalog`, `POST /api/books/discover` (no downloads),
  `POST /api/books/ingest` (one job per document, URL-only — each job fetches
  its own PDF when its turn comes).
- **Tests:** 772 pytest + 71 webapp vitest green.
- **Corpus counts** are unchanged for the shared dev corpus (382 documents /
  7,755 budget chunks); Plan 3 adds no documents on its own.

### Verified end-to-end on 2026-07-31 (real network, real MinerU)

- A real 2-page PDF uploaded through `POST /api/upload` ran
  `extracting → live` with per-page progress, produced 6 passages, took an
  S17 snapshot, copied the source into `<data_dir>/pdfs/`, and came back in
  search titled **"FY 2027 Baseline — Industrial Commission of Arizona"** —
  a title derived from the document's CONTENT, not its filename.
- The validation gate correctly flagged that document as only 17%
  agency-stamped (it is the Industrial Commission's page; the filename said
  AHCCCS) — advisory, non-fatal, visible on the queue.
- A live fiscal-note refresh scraped azjlbc.gov, detected two withheld 2026
  notes (HB 4049, HB 4092), downloaded them, ingested both, and the rail
  search returned their real text. Directory restored to 112 bills.
- A live dry-run of book discovery (listing only, nothing ingested) found the
  **FY2027 Appropriations Report** — which the harvest recorded as
  expected-but-unpublished — via the probe ladder and walked **139 documents,
  0 unreachable**. That is the exact scenario Task 15 exists for.
- Budget eval re-run against the real corpus: **recall@5 72.41%, recall@15
  96.55%, recall@20 100%** — identical to the Plan 1 baseline. No retrieval
  regression. Results committed under `eval/results/`.

### Known follow-ups

- **The fiscal-note eval set has queries but no ground truth.**
  `eval/fiscal_note_queries.yaml` holds 12 coordinator-triage-shaped queries
  and `eval/run_eval.py` takes `--corpus fiscal_notes` (with its own results
  filename prefix so a fiscal-note run can never be diffed against a budget
  one). Ground truth is deliberately empty: it must be real chunk_ids from a
  populated corpus, and populating the 2,126-note back catalogue is an
  overnight MinerU run that has not happened. The file says so at the top.
  **This is the one part of Plan 3 that is not finished.**
- The search provider's corpus probe is still startup-only (Plan 2's
  documented trade), so the FIRST ever ingest into an empty data dir needs a
  restart before search leaves the stub. Every later ingest is picked up live.
- Large historical backfills (dozens of books) are smartest run on Destin's
  machine before departure — office CPUs make it a weeks-long grind. The
  catalog + picker make it possible either way.
- FY2024/25 approps summary-section titles were partly unextractable in the
  mockup harvest; the PyMuPDF walk may recover them, humanized filenames are
  the fallback.
- `db/migrations/0001` doc_type enum comment is still stale vs live data.

---

## Standalone consolidation — Plan 4 shipped (2026-07-31)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S2, S3, S9, S13-read, S15, S16, S19, Invariants 7 + 8). Plan:
`docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md` — see its
**"Task 8 amendments"** block for the as-shipped HTTP contract, which is what
Plan 5 builds against.

**MCP and YouCoded are gone.** AI Mode is an in-process Python tool loop
talking to OpenRouter. No `ws://localhost:9900`, no PTY, no per-conversation
`.mcp.json`, no separate Node process, no dependency on a running desktop app.
`mcp-server/` and `web/` remain in-tree, unused and still passing their own
tests; deleting both is Plan 5.

- **Harness (`harness/`):** `settings.py` (the shared `settings.json` —
  provider triple per S15, tier→model map per S16, admin username, S19 limits),
  `constants.py` (**`REFUSAL_THRESHOLD = 1.9` is now the single source**;
  three contradictory numbers used to reach the model — 1.9 in the prompt,
  0.65 and 0.30 in stale tool descriptions), `tools.py` (the five tools as
  OpenAI function schemas + `ToolExecutor`), `documents.py` (`create_document`),
  `ledger.py` (S19), `session.py` (the loop), `prompt.py` + `system-prompt.md`.
- **The first-call cap is per-conversation, not per-process.** The Node
  original used a module-level flag because there was one process per session;
  one process now serves the whole office, so that shape would have left user
  B's first question uncapped because user A had already asked one.
- **`retrieval/citations.py`** — cite validation lifted out of the FastAPI
  sidecar module so the harness can call it in-process for either corpus. The
  dead alignment heuristics (6 functions, 2 thresholds, ~10 regex tables, 16
  tests) are deleted; the endpoint-level regression guards that assert the
  check stays dead are kept.
- **Routes (`app/routes/`):** `conversations.py` (create + SSE messages +
  stop + `/api/ai/status`), `pdf.py` (Range-streaming + `/api/chunks/{id}`),
  `documents.py` (token downloads). Conversation registry is in-process,
  LRU-capped at 40, and never evicts a conversation with a turn in flight.
- **Webapp:** the chat stack ported from `web/` into `webapp/src/chat/` and
  `webapp/src/pdf/` — citation extraction (~70 carried specs), chat reducer,
  citation bus, chips, markdown, tool cards, mascot, PDF viewer with
  strict-bbox highlighting, cited-text panel. AI Mode toggle on Budget Search
  and Fiscal Notes (**superseded 2026-07-31** — see the deviation note below);
  Home's AI card goes live when a key is present.
- **Tiers (S16):** Standard (step cap 15, `deep_dive` ignored) and Deep
  Research (cap 50, `deep_dive` allowed). Tier explainer copy lives
  **server-side** in `/api/ai/status` so Plan 5's admin page and the webapp
  cannot drift. Every new conversation starts on Standard.
- **Cost (S19):** month-sharded JSONL ledger on the share, per-user limits with
  overrides and exemptions, warn at 80%, block at 100%. Blocked users get the
  ledger's exact sentence, emitted from one place. Limits are inactive on a
  custom endpoint (S15) because exact costs are unavailable, and that state is
  distinguishable from "allowed because under limit".
- **Invariant 7 is structural, not aspirational.** No tool schema takes a path;
  `harness/documents.py` does not import `store.config`, so it has no way to
  learn where the share is; AST-based tests pin the import allowlist.
  `create_document` writes only to `%LOCALAPPDATA%`.
- **Tests:** 1209 pytest / 36 skipped, 297 webapp vitest. `setup.sh --verify`
  green (it also still runs the retired `mcp-server` 57 and `web` 220 suites).

### Verified end-to-end on 2026-07-31 (real OpenRouter key, real corpus)

Tiers as configured: Standard = `qwen/qwen3.7-plus`, Deep Research =
`moonshotai/kimi-k3`. Driven through the real SSE route, not in-process fakes.

| Check | Result |
|---|---|
| Standard lookup ("ADC General Fund, FY 2025") | 3 retrieves → 1 passing cite. **$0.0127, 50s.** Answer volunteered the AFR-vs-Baseline accuracy hierarchy from the prompt without being asked |
| Refusal (out-of-scope question) | Named its corpus, cited nothing, fabricated nothing, **did not retrieve** (correct — out-of-scope needs no search). $0.0018, 13s |
| `create_document` | Real `.docx` in `%LOCALAPPDATA%\JLBC-Insight\documents\` — Title style, memo header, Heading 2 sections, List Bullets. **Nothing written to the share (Invariant 7 held)** |
| Deep Research (3-year AHCCCS comparison) | 4 retrieves / 41 chunks → a correct 3-year table, 5 passing cites. **$0.563, 295s** |
| Ledger | 20 rows, one per step, real per-call cost, `month_total` $0.61, **0 rows with unknown cost** |
| Key removed | `/api/ai/status` → `available: false`, `"no API key configured"`; **search still returned 20 results**. Restoring the key re-enabled AI Mode with no restart (the mtime cache works) |

**Not verified — needs a human at a browser.** Chip click → PDF opens at the
highlighted bbox, and the source panel's visual behaviour. The logic underneath
has 298 vitest specs, but nobody has watched it render.

### Problems the live run surfaced (model/prompt behaviour, not code defects)

- **Citation discipline is unreliable on memo-shaped asks.** Two identical runs
  of the same `create_document` prompt produced 20 citations (12 passing) and
  then **zero** — the second wrote a memo full of specific dollar figures and
  cited nothing, which is an Invariant 1 failure in practice. The UI degrades
  honestly (this is exactly the shape `RefusalBanner` detects: complete turn,
  retrieved, no verified citation), so an analyst sees "This answer carries no
  verified citation" plus the passages rather than false confidence. But the
  prompt and/or the Standard model needs work before this is trustworthy.
- **Cite failure rate is high when cites ARE emitted** — 12/20 and 5/7 passing
  across runs. Worth reading the failure reasons in a longer dogfood.
- **The download token leaked into answer prose.** The model wrote the raw
  `token: 2DZz_Lf…` into the answer instead of leaving the UI to render the
  link. Output-hygiene rule, not a code bug.
- **Meta-narration still leaks** — "let me search the corpus", "I have what I
  need. Let me write the memo". Note `finalAnswer` concatenates *every* prose
  block including pre-tool narration by design, so it reads worse in the audit
  record than on screen.
- **Deep Research costs ~44× Standard and takes ~5 minutes.** $0.563 vs $0.0127
  on comparable questions. The tier split is doing its job, but the copy should
  probably set the time expectation.

### What review caught that tests didn't

Recorded because the same classes will recur:

- **Starlette never closes a `StreamingResponse` body iterator.** It relies on
  garbage collection, and on the disconnect path the iterator sits in a
  reference cycle. A closed browser tab left a model streaming and billing into
  a dead socket, and left a PDF file handle open (which on Windows also blocks
  re-ingest from overwriting the cached file). Cleanup rides a `BackgroundTask`
  in both routes now. `TestClient` cannot catch this — it buffers a "streamed"
  response into a `BytesIO` before returning it, so `tests/live_request.py`
  drives the real ASGI stack.
- **An abandoned SSE stream used to corrupt the conversation permanently** —
  the assistant `tool_calls` message was in history with no matching reply, so
  every later turn 400'd. `_repair_history()` back-fills cancelled results.
- **`UnicodeDecodeError` is a `ValueError`, not an `OSError`.** One mis-encoded
  byte in a month's ledger shard crashed the spend gate for every user.
- **The old system prompt was lying about the refusal threshold** — it said
  `top_score` is "between 0 and 1" and to refuse below 0.30. Both false since
  the Plan 1 model swap (raw cross-encoder logits, roughly −10..10).
- **A dropped tool call rendered as a successful, empty answer** — Invariant 3's
  exact failure shape.
- **The refusal banner denied citations the analyst could see.** It counted
  tool-block cites only, but the renderer also extracts inline `<cite>` tags,
  which open-weight models emit more often than the models that fallback was
  written for.

### 2026-07-31 — AI Mode moved to its own tab (deliberate deviation from S9)

**Do not "restore fidelity" to S9.** Spec S9 says *"Every corpus page =
zero-inference semantic search + an AI Mode toggle (same search box; off =
results list, on = cited chat answer)."* That is what Plan 4 shipped, and after
using it Destin asked for the opposite: *"I hate that 'AI Mode' is part of the
budget search tab."*

As of 2026-07-31:

- **AI Mode is a destination, not a mode.** New route `/ai` (`webapp/src/pages/Ai.tsx`),
  reached from an **icon-only sparkle pill on the right end of the nav**
  (`.nav-item.nav-ai`, accessible name "AI Mode" via `aria-label` + `title`,
  built to the house glyph's exact recipe). Home's AI card points there too.
- **`Budget Search` is renamed `Budget Documents`.** The route is still
  `/search`; only the pill label and the page's identity changed — it is the
  document browser now, and nothing else.
- **The per-page toggles are gone** from Budget Documents and Fiscal Notes.
  Both pages render their browse surface unconditionally; neither imports the
  chat stack. `AiModeToggle` still exists in `webapp/src/chat/AiModePanel.tsx`,
  imported by nothing (deletion belongs to whoever next edits that file).
- **A corpus picker replaces the two toggles.** Budget documents / Fiscal notes,
  chosen inside `/ai`. This is not cosmetic: the fiscal-note coordinator is a
  primary user in the spec, and dropping the fiscal-notes toggle without a
  replacement would have deleted their "have we written a note like this
  before?" triage path.
- **Switching corpus starts a NEW conversation**, by remounting the component
  that owns `useChat` (`key={corpus}`). This is load-bearing: `useChat` reads
  the corpus only when it lazily creates the conversation and then holds that
  `conversation_id` for the hook's lifetime, so a prop change alone would keep
  answering fiscal-note questions out of the BUDGET corpus — cited and
  confident. Three specs in `webapp/src/pages/Ai.test.tsx` fail if the remount
  is removed. It also gives S16 for free: the tier resets to Standard.
- **AI Mode's gate is now a page, not a dimmed pill.** With no key configured,
  `/ai` renders the server's own explanation and no composer, rather than a box
  that would swallow the analyst's question.
- Webapp suites: **304 vitest** (was 297/298).

### Known follow-ups (Plan 5 unless noted)

**Found during the 2026-07-31 Z13 backfill run (see `~/backfill-progress.log`
on that machine and the ROCm investigation doc). These degrade the office
experience silently. Everything marked ✅ is on master — the lock-steal fix in
`f4ddf1d`, the worker-never-started and `make_doc_id`-collision pair in
`ingest-defects`, all 2026-07-31. Those code fixes ship at the app server's
next restart, since the running backfill has its modules already loaded.
Entries still marked 🔴 are genuinely open.**

- **✅ FIXED — the ingest lock could be STOLEN FROM A LIVE HOLDER, giving two
  writers on one corpus.** `IngestLock._try_create` created the lockfile and
  then wrote its JSON payload in a separate buffered step. A second machine
  that read the file inside that window saw it empty, judged it corrupt,
  treated it as stale, and stole the lock — defeating the entire S6
  single-writer invariant. **Reproduced, not theoretical:** a 24-thread race
  produced 8 simultaneous "winners" before the fix. Both halves of the fix are
  on master: `_try_create` now creates and writes in a single `os.write` on a
  raw fd (`ingest/lock.py`, with the WHY comment at that line), and a reader
  waits out `_SETTLE_PATIENCE_S = 1.0` before judging a lockfile corrupt.
  Landed 2026-07-31 in merge `f4ddf1d` ("Merge branch 'parallel-ingest' —
  opt-in parallel extraction + atomic job claiming"), so it is in regardless
  of whether parallel ingest is ever enabled. Guards:
  `tests/test_ingest_lock.py::test_corrupt_lockfile_is_treated_as_stale` and
  `tests/test_ingest_parallel.py::test_the_process_mutex_stops_a_sibling_thread_stealing_a_stale_lock`.
  **This entry said "not merged" until 2026-07-31** — it had in fact shipped
  earlier the same day, and the stale text caused a later session to report it
  as still-open work. Verify with `git merge-base --is-ancestor`, not prose.
- **✅ FIXED — `IngestWorker` was constructed at startup but never
  `.start()`ed.** Only the upload POST route started it, so on the shared
  drive a colleague's queued job sat untouched until somebody on *that*
  machine uploaded something — ingest appeared to hang for no visible reason.
  The app now starts it from a **lifespan handler** (`app/main.py::_lifespan`
  → `ingest.worker.ensure_started`), so any running server drains the queue.
  A lifespan handler rather than a line in `create_app()` because *building*
  an app object (every route test does) must not spawn threads — only
  *serving* should; Starlette runs lifespan on real startup and when a test
  opts in with `with TestClient(app)`. Starting is idempotent (the upload and
  books routes still call `start()` and get the same pool), a failure to start
  is caught and reported on stderr with the real error rather than taking the
  whole server down, and `create_app(ingest_worker=None)` is the explicit
  opt-out for a process that must not run ingest. Guards:
  `tests/test_app_server.py` — a job queued with no upload activity reaches
  `live`, double-start yields one pool, an exploding worker still boots the
  app, a missing `JLBC_DATA_DIR` still boots the app.
- **✅ FIXED — `make_doc_id()` collision silently DROPPED a document.** It
  filed `detailed-list-pdf` under "approps" regardless of family, so a
  baseline and an approps doc could generate the same doc_id; because a write
  is an upsert, the second replaced the first and one document vanished with
  no error. `make_doc_id()` now takes `family=` and, for JLBC book documents,
  the family wins wherever it disagrees with the class the `doc_type` implies.
  Wired at both mint sites that know the family: `app/routes/books.py`
  (`plan.family`) and `ingest/driver.py::_entry_to_item` (via `_family_of`,
  reading the plan target's already-family-prefixed doc_type). Callers that
  genuinely don't know the family — a person uploading a file by hand,
  singleton publishers — omit it and get byte-identical legacy ids.
  **Two collisions, not one.** The original audit ran against
  `data/jlbc-book-catalog.json` and found exactly one in 5,320 in-scope
  documents (FY2026 `26ar/508.pdf` vs `26baseline/508.pdf`, both
  `jlbc-approps-fy2026-508`). A second one exists that the catalog-based audit
  could not see, because the approps linked-TOC walk yields sections the
  catalog snapshot doesn't list: `26AR/capitaloutlay.pdf` is already in the
  corpus as `jlbc-baseline-fy2026-capitaloutlay` (`topic-pdf` hardcodes the
  baseline class), and the FY2026 Baseline book's **own** `capitaloutlay.pdf`
  is in the catalog, in scope, and not yet ingested — it would have minted the
  same id and overwritten it. That second collision is in the
  approps-filed-as-baseline direction, so a fix that only moved the baseline
  side would not have caught it. Guards: `tests/test_driver.py` (both
  collision pairs mint distinct ids; real non-colliding ids pinned unchanged;
  omitting `family` reproduces the legacy id exactly) and
  `tests/test_books_route.py` (enqueue both FY2026 books, assert zero doc_id
  reuse).
- **~~Six~~ TWENTY-TWO already-ingested documents would mint a different id on
  a from-scratch re-ingest** — the cost of the fix above, and the reason it was
  scoped to the misfiled shape only. They are the documents whose family
  disagreed with their `doc_type`'s class: `jlbc-approps-fy2027-{502,507,517,522}`
  (baseline sections filed as approps) and `jlbc-baseline-fy2026-{crr,capitaloutlay}`
  (approps sections filed as baseline).
  > **⚠ CORRECTION 2026-08-16 — the count is 22, not 6.** Checked every
  > document's own `source_url` rather than only FY2026/FY2027, which is all
  > the original audit looked at: FY2022 ×5, FY2023 ×3, FY2024 ×4, FY2025 ×2,
  > FY2026 ×3, FY2027 ×4, plus `jlbc-baseline-fy2026-crr`. Every one has an
  > id saying one book and a URL saying the other. **The prevention shipped**
  > (`make_doc_id(family=)`, 2026-07-31) so no NEW document can do this;
  > these 22 are legacy. Being renamed at Phase 5 of the identity spec, with
  > the eval re-pointed rather than worked around (Destin: *"if the eval is
  > pinning a broken thing, we should fix the eval"*). The rename is
  > deterministic — `chunk_id = f"{doc_id}-{idx:04d}"` — and every re-pointed
  > entry is verified against its own `anchor_text`.
  **Nothing rewrites them today** —
  `documents.json` entries and `chunk_id`s are written once, and
  `/api/books/ingest` de-dupes on `source_url`, so re-running an edition skips
  them rather than re-minting. The exposure is a full corpus rebuild:
  `eval/queries.yaml` q-001 pins `jlbc-baseline-fy2026-crr-0013`, which would
  become `jlbc-approps-fy2026-crr-0013`, and `eval/refresh_chunk_ids.py` — the
  tool that would re-bind it from `anchor_text` — is unported and still
  imports the retired Postgres `db.connection`. **Port the refresh tool before
  any from-scratch rebuild**, or re-point q-001 by hand at that time.
- **Pre-fetched PDFs landed in the wrong directory for ingest.**
  `ingest/cache.py`'s `DownloadCache` writes `data/cached-pdfs/` but the
  worker reads `<data_dir>/pdfs/`. Worked around during the backfill by
  hardlinking 7,479 blobs (0 extra GB). Decide on one canonical location —
  two caches for the same bytes is a trap for whoever maintains this next.
- **🔴 Shared `mineru-api` server: TRIED, CRASHED, ROLLED BACK — do not retry
  at high concurrency.** The idea was sound and the measurement was real: a
  per-document `mineru` invocation spends ~33 s of ~38 s loading models, and a
  warm shared server via `--api-url` took a document from 38 s to **8 s** with
  **byte-identical output** (block counts, text and bboxes verified on 3 docs).
  It also freed ~15 GB by keeping one set of models resident instead of one per
  worker. **But MinerU's server is not memory-safe under concurrency:** at
  `MINERU_API_MAX_CONCURRENT_REQUESTS=12` it died with a glibc
  `corrupted double-linked list` — native heap corruption, not something a
  setting can fix — and every in-flight worker then failed with
  `httpx.ConnectError`. 101 documents failed before rollback; all 101 were
  re-queued and recovered, no data was lost, and the pre-experiment archive
  (`~/corpus-before-parallel.tgz`) was never needed. The code seam survives:
  `JLBC_MINERU_API_URL` (merge `57035a8`, default unset = spawn-per-document =
  today's behavior). **If anyone revisits this, cap it at ~3 concurrent (the
  MinerU default) and expect roughly N=3 throughput, or wait for an upstream
  fix.** The per-invocation model load remains the single biggest theoretical
  win in ingest — batch mode (`-p <directory>`, measured **2.85×** on 4 docs)
  is the safer way to claim it, since it keeps one process per batch.
- **Measured parallel scaling curve (Z13, 32 threads / 121 GB, MinerU 3.1.6
  CPU).** Use these numbers, not guesses, when sizing any future bulk run:

  | workers | docs/hr | per doc | vs serial | notes |
  |---|---|---|---|---|
  | 1 | 93 | 40.0 s | — | extraction is ~92% of a document (39.0 s of 42 s) |
  | 4 | 413 | 8.7 s | 4.4× | |
  | 8 | ~700 | 5.1 s | 7.5× | **the knee** — 14.6 of 32 cores, 12 GB |
  | 14 | 750 | 4.8 s | 7.9× | +7% only; 18 cores, 25 GB; exposed the job-journal race |

  Past ~8 workers the machine is NOT CPU-bound (18 of 32 cores at N=14) — the
  limit is MinerU's own serial phases and I/O, so more workers buy very little.
  The FTS rebuild inside the serialized write cost 0.25 s at 4.7k rows (a
  ~14,000 docs/hr ceiling, not binding then) but **grows with table size**, so
  on a much larger corpus the serialized write becomes the wall and a
  per-batch FTS rebuild is the fix. The remaining real lever on extraction
  itself is **MinerU 3.4.4** (measured 1.35× on plain CPU).
- **Parallel ingest is LIVE and VERIFIED (2026-07-31).** Merged (`f4ddf1d`)
  and enabled on the Z13 backfill at `JLBC_INGEST_WORKERS=4`. **Measured 385
  docs/hour vs the 95/hr serial baseline = 4.05x** — above the 2.5-3.5x
  projection; remaining backfill fell from ~67 h to ~17 h. Verified live, not
  just in tests: 4 concurrent extractions with distinct doc_ids and zero
  duplicates, 0 failed jobs, 0 `ingest lock held by` errors, load 13.9/32.
  Data quality on 93 parallel-ingested documents audited: 93/93 real
  content-derived titles (incl. the `<strike>`/`NOW:` amended-bill form),
  0 missing source paths, 0 chunks missing page provenance across 400
  sampled, 0 empty text, 0 documents with zero passages. Default remains
  N=1 for the office; every invalid value means 1; clamped to
  `min(8, cpu_count/4)` so a 4-core office PC gets 1 and says so.
  **Superseded design note kept for Plan 5:** the prior entry below described
  this as awaiting a decision.
- **[superseded] Safe parallel ingest was BUILT AND TESTED, awaiting a decision** — branch
  `parallel-ingest` (`85ecccb`), not merged, not deployed. Design: parallelize
  extraction (the ~78–90% of wall clock that needs no lock), keep the write
  phase serialized under the existing `IngestLock`, serialize embedding behind
  one process mutex (one shared ONNX model). New `ingest/claim.py` gives
  atomic per-job ownership keyed on BOTH job_id and doc_id (the doc_id key
  guards the `make_doc_id` collision above), with heartbeat/PID stale-steal.
  Opt-in via `JLBC_INGEST_WORKERS=N`, default 1 = byte-identical to today;
  every invalid value means 1; clamped to `min(8, cpu_count/4)` so the same
  variable on a 4-core office PC clamps to 1 and says so. **196 tests pass**,
  asserting no double-run, no lost jobs, same-doc serialization, writes
  serialized, extraction never holding the lock, crash-recovery in both
  directions, and N=1 identical. Measured from the live run to size it:
  ~2.1 GB RSS / ~3.2 cores per extraction. Reasoned projection **~2.5–3.5× at
  N=4** (95 → 240–330 docs/hr) — NOT measured against real MinerU, since that
  would have competed with the live backfill. Verified prerequisite: the
  backfill maintainer (`~/backfill-scripts/maintain.py`) already takes
  `IngestLock` and heartbeats during `optimize`, so it is safe alongside a
  worker pool. Before enabling mid-run also: re-export
  `JLBC_INGEST_SNAPSHOT=off` and kill orphaned `mineru` trees after the
  restart. (The old "POST something to start the pool" step is gone — since
  the `ensure_started` fix above, a restart alone starts it.)
- **MinerU 3.4.4 vs the pinned 3.1.6** — measured 1.35× faster on plain CPU
  (28.5s vs 38.5s on an 8-page doc; beats the ROCm GPU path outright),
  device-invariant output, and it fixes a table row-misalignment seen at
  3.1.6. Changes chunk text corpus-wide ⇒ needs an eval-gated evaluation and
  a re-ingest decision. Worth ~16h on a full backfill.
- **ROCm GPU MinerU: tested, rejected, do not re-litigate without new
  evidence.** Works trivially on gfx1151 (torch 2.13+rocm7.2, no
  `HSA_OVERRIDE`), but break-even is ~5 pages against a 2-page corpus median
  (CPU ≈61h vs GPU ≈63h over the real backfill mix — it's an APU sharing one
  power budget), and at MinerU 3.1.6 it produced device-dependent table
  extraction that put a real dollar figure on the wrong budget line. Full
  evidence: `docs/superpowers/investigations/2026-07-31-rocm-mineru-benchmark.md`.

- ~~**Prompt caching is not requested.**~~ ~~**Quote-not-found cite failures
  on faithful quotes.**~~ **Both SHIPPED 2026-07-31 (S22 + S23, merge
  `5e1ae3b`) — see "AI Mode hardening" below.**
- **`--chat-*` / `--mascot-*` tokens on `:root`** (16 of them) deviate from
  S12's one-palette rule. The mockup palette is monochrome navy — `--az-red` is
  `#2f55c4`, a blue — so there is no error/warning colour, and a failed-citation
  chip rendered in navy would regress Invariants 1–3. **Worth Destin's eye.**
- **[v2, DEFERRED 2026-07-31] Drop the AI Mode corpus picker; let relevance
  choose the corpus.** Destin: "I really don't want a toggle for two distinct
  budget/fiscal-note corpus modes — I'd rather the model pull the right
  documents based on its own determination." Deferred to a v2 pass, not
  rejected. The investigation is recorded here so it isn't re-done:
  - **The UI is the cheap part** (~20 min): delete the picker, the `key={corpus}`
    remount, and 3 specs in `webapp/src/pages/Ai.test.tsx`.
  - **The cost is the system prompt** — `harness/system-prompt.md` carries **20
    `{{#when corpus=…}}` blocks across 1,107 lines** (corpus-specific retrieval
    recipes, filter dimensions, doc-lifecycle guidance). Merging them into one
    both-corpora prompt is real prompt engineering with eval risk.
  - **Nothing is needed in `retrieval/pipeline.py`** — `RetrievalRequest.corpus`
    already exists, so retrieval is per-call corpus-aware today.
  - **Preferred design: search BOTH corpora, don't make the model choose.**
    Embed the query once (the embedding is corpus-independent), run both hybrid
    searches concurrently, merge into ONE rerank pool (top-10 each, so the pool
    stays at today's 20 and the cost is nearly unchanged), and label each result
    with its corpus. This removes the failure mode rather than relying on the
    model to avoid it — a mis-classified question currently answers out of the
    wrong corpus, cited and confident. It also makes the S22 cache prefix
    corpus-independent.
  - **The subtle piece is `cite`.** `validate_cite(body, corpus=…)` needs to
    know which corpus a chunk came from. Do NOT ask the model to re-state it —
    have `ToolExecutor` record chunk_id → corpus from every retrieve result it
    already sees, and resolve from that map. `/api/chunks/{id}` (which takes a
    `corpus` query param) needs the same treatment.
  - **Prerequisite:** build ground truth for `eval/fiscal_note_queries.yaml`
    (~1 h against the now-complete note corpus). Without it a merged-retrieval
    change is protected by the budget eval only.
- Conversation persistence is in-memory per app run (accepted).
- The faithfulness verifier (WS3) and audit-log writer (WS5) remain unbuilt —
  citation enforcement is still chunk-id + quote-in-text + span sanity.
- **Bulk-ingest mode exists (`JLBC_INGEST_SNAPSHOT=off`, 2026-07-31)** — it
  suppresses the per-document S17 snapshot for supervised backfills, because
  zipping the whole corpus once per document is O(n²) (measured: ~54 MB zip
  every ~40 s at 68 MB of corpus; projected 60–90 s/doc after the books).
  Default is unchanged (`per-doc`) and only the literal `off` disables it. The
  better long-term design is a per-BATCH snapshot — once per book edition /
  fiscal-note session rather than per document — which keeps a restore point
  without the quadratic cost.
- **Parallel ingest exists (`JLBC_INGEST_WORKERS=N`, branch
  `parallel-ingest`, 2026-07-31)** — N worker threads each claim their own
  job and extract concurrently; the write phase stays strictly serialized
  behind `IngestLock`. Default is 1 = today's behaviour, and anything that
  isn't a number above 1 (typo, blank, `0`) means 1. The request is clamped
  to `min(8, cpu_count/4)` so the same variable typed on a 4-core office PC
  clamps to 1, and the clamp is announced on stderr. Ownership is decided by
  `ingest/claim.py` — an atomic exclusive-create claim file per job AND per
  doc_id, with a heartbeat thread and stale-steal, mirroring `ingest/lock.py`.
  Measured input: a MinerU extraction averages ~3.2 CPU cores (peak ~7) and
  ~2.1 GB RSS (peak ~3.0 GB) across its 2–3 processes, and is ~90% of a
  document's wall clock. Two pre-existing concurrency defects were fixed on
  the way: the old lock-based claim was a non-atomic read-then-write (two
  workers could both take a job) and it stopped claiming entirely whenever
  any machine held the write lock; and both the lock and claim files could be
  read empty by a racing acquirer mid-create, which read as "corrupt" → "stale"
  → **steal**, i.e. two writers on one corpus. Creation is now a single
  `os.write` and an unreadable file gets 1s to settle before it is judged
  corrupt.

---

## AI Mode hardening — S22 + S23 shipped (2026-07-31)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S22, S23). Handoff: `PROMPT-parallel-ai-hardening.md` (now retired — do not
execute). Merge `5e1ae3b`. Done in parallel with the running Z13 backfill;
touches only `harness/` and `retrieval/citations.py`, nothing on the ingest
path.

### S22 — prompt caching

The ~40 KB (~13.5K-token) system prompt was resent uncached on every step,
up to 50 steps in one Deep Research turn, while every candidate model prices
cache reads roughly 10× below fresh input.

- **The cacheable prefix is now a pinned PROPERTY, not a coincidence.**
  `tests/test_harness_prompt_caching.py` asserts the system message + tool
  schemas are byte-identical across steps of a turn, across turns, and across
  conversations and users, plus a guard that today's date never appears in
  the prefix. That guard is the point of the file: the obvious way a future
  edit breaks caching ("tell the model what day it is") is one line, and it
  has NO symptom — answers stay correct, tests stay green, the bill silently
  goes back up ~10×.
- **Anthropic-style models get an explicit `cache_control: ephemeral`
  breakpoint** on the system content part; OpenAI/DeepSeek/Moonshot-style
  models rely on implicit prefix caching and still get a plain string.
  Anthropic orders a request tools → system → messages, so ONE breakpoint at
  the end of the system block covers the tool schemas too. Selection is a
  substring table (`ANTHROPIC_STYLE_MODEL_MARKERS` in `harness/session.py`),
  because the same model arrives under more than one id. Gated on
  `provider == "openrouter"` for the same reason `usage: {include: true}` is
  — S15's custom endpoint may reject unknown fields outright.
- **`cached_tokens` now rides on every ledger row** and sums into
  `MonthUsage`. Visibility, not arithmetic: `cost_usd` is OpenRouter's own
  exact figure and already reflects the discount. Pre-S22 rows have no such
  key and read as 0.
- **Defect fixed on the way:** the context-window budget passed
  `len(system["content"])` as `reserved`, which reads **1**, not ~40,000, once
  the prompt is wrapped in content parts — the history window would have
  silently grown by the whole prompt's budget and pushed requests over the
  model's context limit with no local error. A test pins that the window is
  identical with and without the wrapper.
- **NOT VERIFIED LIVE.** No OpenRouter key is configured on this machine, so
  nobody has yet seen a real `cached_tokens > 0` or the per-step cost drop
  after step 1. **The next person with a key should run one multi-step turn
  and check the ledger rows** — that is S22's acceptance criterion and it is
  outstanding.
- **Known limit, accepted per S22:** context-window truncation breaks the
  prefix when it fires. Rare, and noted in a comment rather than engineered
  around.

### S23 — normalization-tolerant quote validation

Models emit quotes that are faithful to the chunk and differ from it only by
formatting — a smart quote, a collapsed line break, casing, an em dash
retyped as a hyphen, MinerU's `\$` escape. Exact-substring validation called
every one of those "quote not found" and burned a retry round-trip.

- `retrieval/citations.py` falls back to normalized matching **after** exact
  match fails, so a quote that appears verbatim still binds to the verbatim
  occurrence.
- **`resolved_span_start` / `resolved_span_end` always reference the ORIGINAL
  chunk text**, via an index map. The PDF bbox highlighter and the
  cited-text panel slice `chunk.text` with those offsets, so a normalized
  offset leaking out would highlight the wrong words while reporting success.
- The normalizer is a **port of the webapp's `normalizeForMatch`**
  (`webapp/src/chat/citation-extract.ts`), not a second dialect — the same
  chunk text is normalized on both sides of the wire.
- **Formatting-tolerant, never semantically looser.** Reordered words and
  paraphrases are still rejected; ambiguity rejection still applies
  post-normalization, with positions reported as ORIGINAL-text offsets.
  Invariant 2 is unchanged.
- System-prompt nudge added: quote SHORT, distinctive spans copied exactly.
  The prompt's "Format equivalence" paragraph previously described a
  normalization that **did not exist** — it now describes what the check
  really does.
- Two defects caught in self-review and fixed: `'İ'.lower()` is two code
  points in Python, which desynchronized the index map (every citation later
  in that chunk would have mis-highlighted); and the markdown-link scan was
  O(n²) on a bracket-heavy chunk. Both pinned by tests.

**Tests:** 1394 pytest / 36 skipped (was 1392 before this work — 38 new
specs across two new files). The webapp was not touched, so its 304 vitest
were not re-run.

**Eval not re-run, deliberately.** `harness/system-prompt.md` changed, which
normally triggers the eval rule in CLAUDE.md — but `eval/run_eval.py` calls
`retrieve()` directly and never reads the system prompt, so it cannot
measure this change; and the corpus is actively changing under the running
backfill, so any number produced now would be meaningless. Re-run it after
Phase C for the recency work, not for this.

### Follow-ups this work created or found (for Plan 5)

- **S22 live verification is outstanding** (above).
- **Only the SYSTEM prefix is cached.** In a long Deep Research turn the
  conversation history — every prior tool result — is also resent every step
  and is often larger than the prompt. A rolling `cache_control` breakpoint
  on the last history message is the standard next win. Deliberately not
  attempted here: it is outside S22's scope, and OpenRouter's translation of
  content parts on `tool`-role messages is unverified.
- **The webapp and server normalizers can still drift.** Two known
  divergences, both benign today and both worth knowing about: the server
  applies NFKC **per code point** (exact index map) where the TS normalizes
  the whole string and approximates the map proportionally when the length
  changes; and Python's `str.isspace()` covers a few characters JS's `\s`
  does not. Neither occurs in this corpus. There is no shared test fixture
  pinning the two implementations against each other — that would be the
  real fix.
- `MonthUsage` gained `cached_tokens`; Plan 5's admin usage panel should
  render it, otherwise the number is recorded and never seen.
  **Resolved in Plan 5 Session A, but not as written** — see that section's
  "cached tokens are watched, not displayed".

---

## Standalone consolidation — Plan 5 Session A shipped (2026-08-01)

**Tracks 1 and 2 (tasks 1–13).** Track 3 (packaging) shipped separately from
Session B — see its own section. Track 5 (handbook, tasks 21–23, Session C)
is not started. Track 4 (legacy deletion + remaining ingest defects, tasks
18–20) waits on Session C, so `web/`, `mcp-server/`, `db/`, and the legacy
`retrieval/` modules are **still in-tree and still unused**.

> ✅ **RESOLVED in Track 4 (2026-08-01) — all three open items are built.**
> Kept below as the record of what was owed and why. See
> `docs/superpowers/investigations/2026-08-01-bundle-app-requirements.md`.
> Status as of this merge: **#1 (per-machine `ingest_enabled` flag + the
> "nobody is processing uploads" admin warning) — **BUILT, Track 4**. **#2
> (`/health` returns 200 whenever the process serves) — already satisfied;**
> the route is a plain dict with no status logic and the ladder deliberately
> lives at `/api/health/detail`, so no change is needed. **#3
> (`python -m app.machine_config --set-data-dir` so `install.cmd` stops
> hand-writing JSON) — **BUILT, Track 4**. #4 is informational.
>
> **#1 is the consequential one.** `launcher.pyw` calls `create_app()` with
> no arguments, which starts the ingest worker — on ~20 office PCs that is 20
> workers racing for one queue. `IngestLock` keeps it safe, but the winner is
> arbitrary and may be an analyst's laptop that then spends six hours at 100%
> CPU. Defaulting the flag to OFF re-creates the opposite failure (uploads
> queue on the share and nothing drains them, silently), which is why the
> admin warning is not optional.

### What shipped

- **Admin identity + soft gate** (`app/identity.py`). Keyed on the Windows
  username. **This is not authentication and must never be described as
  such** — it keeps a curious analyst out of the settings page, nothing
  more. First run claims the admin slot one-way.
- **Break-glass recovery.** A file named `RESET-ADMIN.txt` in the data dir
  clears the admin slot; it is consumed on read, so it works once.
- **Settings API** (`app/routes/admin.py`) — reads never return the API key
  (only `api_key_set` and a last-4 hint); writes take a `"__unchanged__"`
  sentinel so a round-trip cannot blank the key.
- **Ledger breakdown** by user / model / tier, plus `/api/me` and
  `/api/me/usage`.
- **OpenRouter catalog** (`harness/catalog.py`) — tool-calling filter, 8
  curated recommendations, 6-hour cache, offline-first with a bundled
  fallback list.
- **S13 model fallback** — a per-process runtime override with a persisted
  notice. Deliberately **not** a settings write: a transient provider fault
  must not silently rewrite what the admin chose.
- **Corpus health + guarded one-click restore**; snapshot listing.
- **Admin page + Settings page** (`webapp/src/admin/`, `webapp/src/pages/`).
- **S18 per-machine data-dir pointer** below the env override.
- **Launch health ladder + repair screen** — five short-circuiting rungs in
  plain English.
- **Corrupt-settings preservation** — an unparseable `settings.json` is
  copied to `settings.json.corrupt-<timestamp>` before being overwritten.
  Those bytes may hold the only recoverable copy of the API key.

### The admin page was rebuilt across seven review rounds

The first version passed its tests and was still wrong on the page. What
Destin's review changed, in order: eliminate "unknown cost" at source; drop
jargon; group into nested cards; make AI Mode a chain of switches; replace
the orphaned Save button; fix toggle hitboxes; rebuild the model picker with
cost and capability; keep it a dropdown rather than a list; replace "pages at
once" with a real capability measure.

### Decisions worth not re-litigating

1. **A custom endpoint must declare both per-million prices.** This is not
   cosmetic. `check_limit` previously treated *any* custom endpoint as
   "limits structurally inactive", so an office on a custom endpoint had **no
   spending cap at all**, silently. The gate is now `has_pricing`, and a
   custom endpoint without prices is refused at save time.
2. **AI Mode is a chain of switches**: master switch → API key → per-mode
   switch → model choice. Each step unlocks the next.
3. **In `ai_available()`, "no model configured" is checked BEFORE the
   per-mode switch.** Saving resolves the unset sentinel, so without this
   ordering a save-and-reload turned "never configured" into "explicitly
   switched off" — two different things to an admin trying to fix it.
4. **The model picker is a dropdown, not a list.** A radio list showed
   eight rows permanently; this is a twice-a-year setting.
5. **Intelligence is a percentage of a fixed ceiling** (`INTELLIGENCE_CEILING`
   in `harness/catalog.py` — Opus 5's Artificial Analysis Intelligence Index
   plus 10% headroom), not the raw index. The headroom is deliberate: a
   leader at 100% would claim "as good as models get", which expires the week
   a better model ships. Nothing on the shortlist may reach 100% — there is a
   test that fails when it does.
6. **No speed or latency rating anywhere.** OpenRouter publishes those fields
   but returned `null` for every shipped recommendation on 2026-07-31. A
   spec test asserts the words "latency", "throughput", and "speed" never
   appear in the picker.
7. **Cached tokens are watched, not displayed.** The prior follow-up asked
   for a "cached input" column; "cached input" is meaningless to a
   non-technical admin, so `cached_tokens` instead drives a
   `cacheLooksBroken` health warning. The number is used, never shown.
8. **First-party flagships stay off the shortlist** (S16). For scale, at the
   prices and question profile in `TYPICAL_QUESTION`, Opus 5 costs ~42¢ for
   a Standard lookup against ~1¢ on Qwen3.7 Plus.

### What review caught that tests didn't

The suite mocks the API and jsdom applies no stylesheet, so wire-format,
layout, and paint-order bugs are **structurally invisible** to it. Every one
of these came from opening the page:

- **`ai_enabled` never reached the API.** It was added to the TS types and
  the UI but not to `_redacted()`/`_merge()`, so the client read `undefined`
  → falsy → a working install rendered AI Mode OFF. All vitest passed.
- **Toggle hitboxes only worked on the label text.** `.adm-toggle-track` is
  `position: relative`, so it painted above the `inset: 0` input and ate the
  click; the statically-positioned text did not. Fixed with a `<label>`
  wrapper — reverting it fails 4 of 8 specs.
- **The picker popup was clipped by three separate contexts** —
  `.card{overflow:hidden}`, `.adm-card{overflow:hidden}`, and
  `.adm-panel{overflow-x:auto}`. The identical bug and fix already existed in
  the same stylesheet for `.page-search .big-search-card`.
- **`data_dir()` creates the directory as a side effect**, so the health
  ladder could never detect a missing share — it conjured one and passed.
  Split into a pure `resolve_data_dir()` for the check.
- **`limits_active` was computed from the calling admin**, so an exempt admin
  saw "limits inactive" for the whole office. Now probed against an org view.
- **An empty corpus failed the health gate**, which would have locked a fresh
  install behind a failure screen with no route to Upload. It is an OK rung.
- **`tsc -b` (the production build) is stricter than `tsc --noEmit`** and
  rejects unused imports the dev check allows.

### Follow-ups this work created

- **The whole page is unverified against a real browser on a JLBC machine.**
  It was reviewed in a browser here against a synthetic data dir.
- **Three recommendations tie at 66% intelligence** (raw 44.4 / 44.3 / 44.2).
  Honest — that gap is noise — but the picker shows three identical numbers
  and only cost separates them.
- **The intelligence scale spans 50–85% in practice**, so the bottom half of
  every bar is dead space. Rescaling to the shipped range would use the full
  width at the cost of a fixed reference point.
- **`INTELLIGENCE_CEILING` is a hardcoded constant** and goes stale when
  Artificial Analysis re-scores. The re-derivation recipe is in its comment.
- **Error-message standards were not audited** across the admin surfaces.
- ~~**Two of Session B's four app-side asks are unbuilt**~~ **DONE in
  Track 4, 2026-08-01** — the per-machine `ingest_enabled` flag, its admin
  warning, and the `app.machine_config` CLI entry point all shipped.

---

## Layer 2 agent-loop eval harness shipped (2026-08-01)

### First live baseline — smoke, 2026-08-01

`eval/results/agent/2026-08-01T1157Z-25399b1/` — 11 queries, Standard tier
(`z-ai/glm-5.2`), **0 errors, $0.43, ~4 min**. Derived artefacts committed;
transcripts are gitignored by policy. This is the number every future
`compare_agent_runs.py` delta on the smoke set is measured against.

| metric | baseline | reading |
|---|---|---|
| key-fact rate | **0.91** | the answers are largely correct |
| refusal correctness | **1.00** | both out-of-scope questions correctly refused, nothing fabricated |
| `cite_pass_rate` / `first_try_cite_rate` | **0.99 / 1.00** | citations essentially never fail or retry |
| citations per answer | **9.0** | ⚠ far more than "a smaller number of high-value citations" |
| median quote length | **131 chars** | ⚠ wide; the goal is narrow, targeted spans |
| retrieval efficiency | **0.34** | ⚠ two thirds of retrieved chunks go unused |
| input tokens / answer | **83.6k** (60.3k cached) | ⚠ the dominant cost driver |
| steps / retrieves per answer | 3.5 / 2.1 | already tight |
| cost per answer | $0.039 | ~3× the $0.0127 STATUS recorded for a Plan 4 lookup |
| meta-narration | 1 of 11 queries | the known leak, now measured |

**The four ⚠ rows are the improvement backlog** and they map onto the goals
this harness was built to serve: citation volume and quote width (goal 4),
retrieval efficiency (goal 3), and prompt tokens (goal 1). Accuracy and
citation *reliability* are already strong, so the work is about doing the
same job with less — not about correctness.

**S22 prompt caching is VERIFIED LIVE by this run** — closing the acceptance
criterion left open on 2026-07-31. Of 39 billed steps, 35 report
`cached_tokens > 0`; the first step of each conversation reads 0 and every
later step is ~90% cached (e.g. 13,835 in / 13,760 cached). The caching is
real and is already saving roughly 72% of input tokens.

**Superseded by the full baseline** — `eval/results/agent/2026-08-02T0900Z-0b08221/`,
31 queries, 0 errors, $1.20. Key figures: key-fact rate 0.81, refusal
correctness 1.00, `cite_pass_rate` 0.84, `first_try_cite_rate` 0.90,
citations/answer 10.1, retrieval efficiency 0.44, 138k input tokens/answer.
Judged by **`z-ai/glm-5.2`**: `claim_coverage_precision` 0.578,
`claim_coverage_recall` 0.969, holistic 4.13.

**The judge is glm-5.2 for everything from 2026-08-02** (Destin's call).
Measured against claude-sonnet-5 over these same 31 answers: 0 errors, every
disagreement within one point, rank correlation 0.89, comparable claim counts
(144 vs 135), ~8x cheaper — so every run can be judged, not just merge gates.
Accepted risk: glm-5.2 is also the model under test, so it grades its own
output. Evidence and the rejected alternatives:
`docs/superpowers/investigations/2026-08-02-judge-model-comparison.md`.
**Judge results are not comparable across judge models** — now enforced by
`compare_agent_runs.py`, which withholds the judge section when they differ.

**Still not run:** the 4-query Deep Research probe.

Spec: `docs/superpowers/specs/2026-08-01-agent-loop-eval-design.md`
(the Layer 1 spec, `2026-05-20-retrieval-eval-harness-design.md`, is where
the Layer 2 goal was first deferred from — it is NOT what this was built
against). Nine tasks: query schema + transcript format,
the money-spending runner, the free mechanical scorer, the LLM judge, and
the run-comparison tool. Full usage docs, cost guide, and the experiment
loop are in `eval/README.md` → "Layer 2 — agent-loop eval"; this section
is the shipped-status record.

**What it measures that Layer 1 cannot.** Layer 1 (`run_eval.py`) calls
`retrieve()` directly and scores chunk recall — fast, free, and a strong
regression detector, but blind to everything downstream of retrieval.
Layer 2 (`run_agent_eval.py`) drives the REAL `HarnessSession` — the
production tool loop, no HTTP server — against open-ended analyst
questions and measures agent turns, tokens, cost, whether the final
answer actually contains the right key facts, citation discipline (cite
attempts vs. first-attempt passes), and output-hygiene leaks (meta-
narration, internal vocabulary, a leaked download token). **The two
layers' numbers are not interchangeable and must never be diffed against
each other** — different query sets, different things measured.

**It costs real money — unlike every eval that came before it.** A
`smoke` run (11 queries) runs roughly $0.15–0.30 on Standard tier, a
`full` run $0.50–1.50, and the 4-query `dr-probe` subset $2–3 (Deep
Research runs ~44× the per-query cost of Standard — see the Plan 4
dogfood numbers above). The LLM judge is a second, separate charge
layered on top of a run.

**`full` is all 31 STANDARD-tier queries and contains no Deep Research
query** — spec Decision #4, "Standard for the full set + a fixed 4-query
Deep Research probe", which explicitly rejected full-set DR runs. The
four DR queries briefly carried a `full` tag as well (fixed 2026-08-01):
that put ~$3 of Deep Research into a run priced at $0.50–1.50, moved
`wall_p95_ms` onto a ~295-second DR answer so Standard latency
regressions became invisible, and made `--subset full` refuse to start
on an install with Standard configured and Deep Research off — a
configuration `harness/settings.py` explicitly allows.
`tests/test_eval_agent_queries.py` now pins the exclusivity in both
directions.

**The runner writes its own ledger and never touches the office one.**
`check_limit` is stubbed to always-allow and `record_usage` writes into
the run directory's own `ledger.jsonl`, not the shared office spend
ledger — an eval run is pre-authorized by the human who started it, so
it must not be blocked by S19 office limits, and it must not silently
accrue against them either. **Eval spending will never show up in the
office usage totals** — that is by design, not a bug to chase.

**Single runs are stochastic.** `--repeats N` exists because model
output varies run to run; `compare_agent_runs.py` prints an explicit
warning whenever either side of a comparison is a single run, so a
small delta doesn't get mistaken for a real regression.

**The experiment loop the harness exists to serve** (for any change to
`harness/`, `retrieval/citations.py`, or `harness/system-prompt.md`):
cheap layer first (Layer 1 + free re-scoring of old transcripts), then a
live `smoke` run compared against a baseline `smoke` run, then before
merging a `full` run plus the judge, with the compare report committed
alongside the code change.

**Results-committing policy, implemented and verified against real
files, not just described.** Raw transcripts (`<query_id>-r<N>.jsonl`)
embed full retrieved-chunk text — large, and derived from the corpus
rather than from the change under test — so `.gitignore` now excludes
`eval/results/agent/*/*-r*.jsonl` and `eval/results/agent/*/ledger.jsonl`.
`manifest.json`, `scores.json`, `scores.md`, `judge.json`, and any
`compare-*.md` report are NOT excluded — they're the derived regression
record, at a fraction of the transcripts' size, and that's what a future
diff needs. Verified with a throwaway run directory containing one file
of each kind: `git status --porcelain` showed the untracked directory,
`git check-ignore -v` confirmed the transcript and ledger files matched
the new `.gitignore` lines and the five derived files matched nothing,
and `git add -n` staged the five derived files while refusing the two
ignored ones. The throwaway directory was deleted afterward — nothing
from the verification is in this commit.

**Final-review fix batch, 2026-08-01** (all pre-baseline, so no committed
results were invalidated):

- **`full` is Standard-only** — see the paragraph above.
- **`manifest.json` now carries `queries_sha256`**, a content hash of the
  queries a run actually asked, and `compare_agent_runs.py` refuses a
  comparison across differing query sets exactly the way it already refused
  one across differing corpus counts (`--force` overrides both, and a forced
  report says so). The id list alone was byte-identical when a query's
  key_facts were EDITED between two `full` runs, so the whole delta was
  authoring drift with nothing on the page saying so.
- **Two metrics were renamed and two added** — anything reading `scores.json`
  must follow. `first_attempt_cite_rate` was never a first-attempt rate; it is
  now **`cite_pass_rate`** (passes ÷ all attempts). The genuine measure is the
  new **`first_try_cite_rate`** (intended citations that passed on the first
  try), with **`retries_per_citation`** beside it. The spec's promised
  filter/corpus-parameter usage counts are now emitted too
  (`filtered_retrieve_rate`, `filter_dimension_counts`, and friends —
  informational, no better/worse arrow).
- **`retrieves_after_sufficient_mean` publishes its population**
  (`..._n` / `..._eligible_queries`) and the compare tool withholds the
  better/worse arrow when that population moved. The metric only exists for
  queries where the facts were eventually found, so a genuine retrieval
  improvement could otherwise render as a ▼ regression.
- **`total_cost_usd` is not the authoritative spend number** — a query that
  crashes mid-turn produces an error frame with no usage at all, so its
  already-paid tokens are invisible. `cost_missing_queries` counts those
  queries; `ledger.jsonl` (one row per step, written as it happens) is the
  real record, and `eval/README.md` now says so instead of presenting the two
  as equivalent.
- **Transcripts are written tmp+replace**, like every other artifact here. The
  reader's torn-file degradation stays — but a run should not manufacture the
  damage it tolerates, since a torn transcript scores as a failed query.

**Second fix-batch (small, post-review), 2026-08-01:**

- **`compare_agent_runs.py` now keys `total_cost_usd` on `cost_missing_queries`
  too**, the same population-dependent-arrow-withholding mechanism the first
  batch built for `retrieves_after_sufficient_mean`. A crashed query sums $0
  into `total_cost_usd` despite real spend, so a regression that crashes
  10-of-31 queries could render as a green cost improvement — reproduced
  before the fix (`cost_missing_queries` 0→10 alongside `total_cost_usd`
  1.2→0.81 showed a bare ▲). Deliberately NOT extended to `cost_mean_usd`,
  `steps_mean`, and the other means, which are equally population-dependent on
  `errors` — `errors` already carries its own visible ▼ on the same table,
  and over-applying the suppression would strip arrows off most of the
  report.
- **`retrieves_after_sufficient_eligible` held two types under one name** —
  a bool on each `per_query` row, an int count in `summary` (confirmed in
  real output: `true` vs `2`). Anything reading `scores.json` generically
  trips on it. The summary-side key is renamed
  **`retrieves_after_sufficient_eligible_queries`**; the per-query bool is
  unchanged. Safe to do now because no baseline run has been committed yet.

**No live baseline run has happened yet.** The harness is built and
unit-tested (110 pytest specs, synthetic fixtures throughout —
transcript read/write, scoring, the judge's JSON parsing and error
handling, the comparison tool's corpus-count and query-set refusals, and
a runner→scorer seam test that drives the REAL `HarnessSession` over a
fake transport and then scores the transcript it produced) but nobody
has pointed it at a real OpenRouter key. `eval/agent_queries.yaml` — the
query set itself (now 53 queries under the consolidated `set:` tags:
45 quick / 3 deep / 5 refusal, all on the BUDGET corpus, with
machine-checked key facts) — is committed. **The acceptance step for
whoever has a key next:** run `--sets quick,multi,refusal` (the retired
`--subset smoke` from this historical note is gone), score it, and commit
the result as the first baseline — every later `compare_agent_runs.py`
call needs one to diff against.

---

> ## ⚠ HISTORICAL FROM HERE DOWN
>
> Everything from this point through the end of the
> "Recently fixed — verify in next dogfood pass" section describes the
> **RETIRED pre-consolidation architecture** — the sidecar on `:9200`, the
> Budget MCP server, the Next.js `web/` UI, Voyage reranking, and Postgres.
> None of it is running code anymore; it is kept only as the historical
> record of what Phase 1c shipped. **Current state is the four
> "Standalone consolidation — Plan N shipped" sections above.** In
> particular: the live refusal threshold is **1.9** in
> `harness/constants.py` — the 0.65 mentioned below is the dead Voyage
> 0..1 score scale.

## What's shipped (Phase 1c)

### Retrieval sidecar (`retrieval/api.py`)
- FastAPI service on `127.0.0.1:9200`
- `POST /retrieve` — BM25 + dense + RRF + Voyage rerank. Accepts optional `intent: "lookup" | "compare" | "analyze"` (resolves to default top_k 5 / 12 / 18 when no explicit top_k passed) and echoes intent in the response. Default `top_k` when no intent + no explicit value is 15 (was 20 through 2026-05-19; lowered after dogfood showed spillover at top_k=20).
- `POST /cite/validate` — chunk_id existence + quote-in-chunk-text + span sanity (negative / inverted / oversized). **The content-word-overlap alignment check was DROPPED 2026-05-20** — it was a string-overlap heuristic that produced ~40% false rejections on faithful-but-differently-worded claim_spans. Real faithfulness validation will come from WS3 (NLI verifier, unbuilt).
- `POST /cite/validate_batch` — validates N citations in one round-trip with bulk DB fetch (one `WHERE chunk_id = ANY(%s)` query for all unique chunks). Powers the MCP `cite_batch` tool.
- `POST /list_values` — returns canonical_id slugs with chunk counts + sample doc titles
- `GET /docs/{doc_id}` — document metadata for the PDF viewer
- Sidecar startup loads `.env.local` via python-dotenv; lifespan preflight validates `VOYAGE_API_KEY` + `DATABASE_URL` + chunks-table-non-empty before accepting requests, exiting with a clear stderr message on any failure.
- **55 pytest passing**

### Citation `cite()` / `cite_batch()` behavior
- `cite()` accepts either explicit `span_start`/`span_end` offsets OR a `quote: string` field (server scans chunk.text for the quote and derives the offsets). Quote is the preferred path; offsets are legacy. `claim_span.max` is 2000 chars on the schema; server soft-clamps to 500 with `truncated: true` flag.
- `cite_batch({citations: [...]})` is the multi-citation companion: collapses N serial round-trips into one. The model's tool_use carries an array of single-cite shapes; the response is a parallel array of single-cite results. System prompt steers toward `cite_batch` whenever an answer has more than one citation.
- Both tools return `resolved_span_start` / `resolved_span_end` on success — the sidecar-derived position of the cited text inside chunk.text. The web UI uses these for precise PDF text-layer highlighting.
- The locked schema decision doc (`docs/superpowers/decisions/2026-05-06-citation-tool-schema.md`) has a 2026-05-20 amendment header documenting all of the above.

### MCP server (`mcp-server/`)
- Four tools registered: `retrieve`, `cite`, `cite_batch`, `list_filter_values`
- Per-conversation `.mcp.json` materialization with `alwaysLoad: true` on the budget MCP server (eliminates ToolSearch round-trips for the budget tools). Per-conversation `.claude/settings.json` allow/deny — allow: Bash, Read, the four budget MCP tools; deny: Grep, Write, Edit, MultiEdit, NotebookEdit, Glob, PowerShell, WebFetch, WebSearch, ToolSearch, plus glob denies for unrelated MCP servers (`windows-control`, `gmessages`, `imessages`, `todoist`, `spotify-services`).
- `retrieve()` first-call cap: the FIRST retrieve() of any session is capped to 5 chunks regardless of input top_k/intent. Response carries `first_call_capped: true`. Bypassable with `deep_dive: true` for explicit thorough-coverage requests. Subsequent retrieves are uncapped.
- System prompt (~1300 lines) covers: constrained-agent contract, "tools are preloaded — do NOT call ToolSearch" notice, **progressive retrieval pattern** (first call samples, model expands if needed), **Route-the-question-first classifier** (lookup/compare/analyze → answer FORMAT, not retrieve breadth), **Output hygiene** (banned leak categories: internal vocabulary, corpus mechanics, retry narration), cite() quote recipe, filter dimensions + agency cheat sheet, doc lifecycle (Governor → Baseline → Approps → AFR), 3-year table structure, AFR accuracy hierarchy, retrieval recipes, refusal cases.
- Structured per-call JSONL logging at `~/.claude/ask-the-budget-az/bridge.log` (timestamp, endpoint, duration, outcome, httpStatus, errorCategory, retrievalId). One line per /retrieve and /cite/validate(_batch) call.
- **57 vitest passing**

### Web app (`web/`)
- Next.js multi-turn chat UI on `127.0.0.1:3000`
- Citation rendering:
  - Inline-underlined chips for successful cites; red-X wavy-underline for failed
  - Retry chips collapse via two-pass dedup: (1) chunk_id + substring-chain union-find; (2) FIFO-pair fail→ok across blocks for the same chunk_id (handles claim_span-rewritten retries). Suppresses pairing within a single `cite_batch` (same `batchId`) — sibling claims in a batch are intentional distinct citations, not retries.
  - Tooltip shows verbatim quote (success) or claim-vs-actual-cited side-by-side (failure)
  - MCP zod errors humanized (not raw JSON)
  - Markdown table-row claims inject sentinel inside the last cell
  - Citation `spanStart`/`spanEnd` resolution order: ack's `resolved_span_start/end` (preferred) → explicit input offsets (legacy) → `(0, claim_span.length)` sentinel (only for in-flight or pre-fix calls; produces "couldn't pinpoint" badges in the PDF viewer).
- Tool cards: friendly labels (Search corpus, Cite claim, Cite claims, Browse filters, Shell, …) with per-tool body views (RetrieveView, CiteView, ListFilterValuesView, EditView, ShellView, …). Single status indicator on the header (pixel-glyph color encodes running/complete/failed); pulses while running.
- PDF viewer (`web/components/PdfPage.tsx`):
  - pdfjs-dist canvas render with bbox-restricted text-layer search
  - Multi-pass match strategy: chunk.text\[span_start:span_end\] → full chunk.text → individual currency tokens; bbox-restricted first, then unrestricted
  - "Couldn't pinpoint" badge instead of misleading chunk-bbox fallback when all matches fail
  - "Couldn't open source PDF" error when chunk's source isn't a PDF (DOCX legislative bills currently — DOCX viewer is Phase 2)
- ChatThread auto-scroll: event-driven detection, only follows bottom when the user is at bottom. Messages anchor to the BOTTOM of the viewport.
- UI refresh + JLBC mascot (shipped 2026-05-19, branch `ui-prettify-mascot`):
  - Civic-warm theme tokens; single-mascot architecture with pixel-aligned variant swaps (idle / typing / presenting / refusal); seated typing scene with 12-second behavior loop; welcome hero on empty thread; suggestion chips; speech-bubble assistant messages; page pinned (only chat thread + PDF viewer scroll); footer honesty line.
- Sidecar `/health` probe at session start; renders a `SystemHealthBanner` above the chat thread when the probe fails (e.g. sidecar not running). Returned inline from `startConversation` as `{conversationId, health}` — no event-subscription plumbing.
- **197 vitest passing**

### Eval harness (`eval/`) — Layer 1 retrieval eval

- 34 LLM-synthesized queries (`eval/queries.yaml`) with hybrid ground truth (chunk_id + dimensions + anchor_text)
- `eval/run_eval.py` — calls retrieve() directly, emits JSON + Markdown to `eval/results/<UTC-ISO>-<git-sha>.{json,md}`, computes delta vs previous run
- `eval/refresh_chunk_ids.py` — post-reingest stale-chunk_id fixer (anchor match → cosine fallback)
- `eval/calibrate_refusal.py` — sweep refusal thresholds + recommend
- `eval/synthesize_queries.py` — LLM-driven query generator (Anthropic SDK; subagent-driven path is also documented when no API key)
- **44 pytest passing** across 6 test modules
- **First baseline (committed under `eval/results/`)**: recall@5 86%, recall@20 100%, latency p95 2561ms on the 34-query set. Refusal precision was 0% at the hardcoded 0.30 threshold (Voyage rerank scores sit at 0.56-0.93 — calibration recommends moving the prompt threshold to 0.60 for perfect separation on this eval set).

---

## 2026-05-19 → 2026-05-20 hardening pass

Substantial reliability + UX work landed across this window. Each item ships as a feature branch merged with `--no-ff`; the merge commit is the entry point for the audit trail. All work in worktrees per CLAUDE.md convention, cleaned up after merge.

### Items 1-7 of the original dogfood-hardening plan (merge `1939347`, 2026-05-19/20)

| Item | What | Most-relevant file(s) |
|---|---|---|
| 1 | Per-session `.mcp.json` (alwaysLoad:true) + `.claude/settings.json` allow/deny (eliminates ToolSearch) | `web/lib/youcoded-session-provider.ts`, `web/lib/mcp-config-loader.ts` |
| 2 | `cite()` accepts `quote` (server derives offsets); `claim_span` relaxed 500→2000 with server soft-clamp | `mcp-server/src/tools/cite.ts`, `retrieval/api.py` `http_cite_validate` |
| 3 | `DEFAULT_PIPELINE_TOP_K` lowered 20→15 (measurement-gated by `scripts/measure_retrieve_size.py`) | `retrieval/pipeline.py` |
| 4 | `intent` parameter on `retrieve()` (lookup/compare/analyze → top_k 5/12/25); routes table in system prompt | `mcp-server/src/tools/retrieve.ts`, `retrieval/api.py` |
| 5 | Output-hygiene prompt rewrite — three banned leak categories + dogfood-test plan | `mcp-server/system-prompt.md`, `docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md` |
| 6 | Bridge JSONL logging + session-start `/health` probe + SystemHealthBanner | `mcp-server/src/lib/bridge-log.ts`, `web/components/SystemHealthBanner.tsx` |
| 7 | Sidecar `python-dotenv` auto-loads `.env.local` + startup preflight + README "Daily startup" checklist | `retrieval/api.py` `lifespan`, `README.md` |

Plan doc at `docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md` (historical — captures the pre-execution design + open-question resolutions Q1/Q2/Q3).

### Follow-up fix waves (after Items 1-7 shipped)

Each wave responded to specific issues surfaced during dogfood verification of the previous wave.

**Wave A — Citation-extract patches (commits `5981dbb`, `4620ec3`).** Quote-only cite() calls were being silently dropped at the UI extraction layer because the extractor required numeric offsets. Patched to accept quote-only with a sentinel range; added FIFO-pair-fail→OK dedup for retries that rewrite claim_span entirely.

**Wave B — `cite-batch` branch (merge `3c6bf04`).** Dropped `_check_alignment` from `/cite/validate` (~40%→~5% false-rejection rate; removed the dominant retry-loop latency source). Added the `cite_batch` MCP tool + matching `/cite/validate_batch` sidecar endpoint with bulk DB fetch — collapses N serial cite round-trips into one for analyze-shaped answers. Web `citation-extract.ts` walks the batched input/output arrays; new `batchId` field disambiguates same-batch siblings from cross-block retries in the dedup pass.

**Wave C — `cite-resolved-offsets` branch (merge `2c570e6`).** Threads sidecar-derived `resolved_span_start` / `resolved_span_end` through the cite + cite_batch tool responses to the web UI, fixing the "Citation is on this page — exact text couldn't be pinpointed" badge cluster. Also denies `ToolSearch` in `.claude/settings.json` (alwaysLoad wasn't fully eliminating model-side ToolSearch habit), tightens the route classifier to default-to-Lookup for "Show me X" / "What is X" wording, lowers analyze top_k 25→18 to stay under Claude Code's spillover threshold.

**Wave D — `first-call-cap` branch (merge `af6a673`).** Progressive retrieval: first retrieve() of any session is capped to 5 chunks regardless of intent/top_k. Bypass via `deep_dive: true` for explicit thorough-coverage requests. After the first call, pass-through behavior. Route classifier rewritten to be about answer FORMAT, not retrieve sizing — breadth comes from iterative follow-up retrieves, not one-shot top_k.

**Wave E — `citation-accuracy` branch (merge `400d674`).** Three connected improvements to citation handling. (1) Per-sentence chip placement: `planCitationPlacements` walks every sentence and places a chip wherever the claim_span or the citation's key-fact token (largest currency / percentage) appears, with anti-duplicate guard. `CitationPlacement` gains an optional `column` field; `injectCiteSentinels` splices sentinels mid-line via right-to-left injection. Restated facts across multiple sentences now each get their own chip. (2) Strict-bbox PDF highlight: text-layer search extracted into a new `HighlightStrategy` interface (`web/lib/highlight-strategy.ts`) with `TextLayerSearchStrategy` as the default and a `CoordMapStrategy` placeholder for the #57 follow-up. When a chunk has a bbox, search is strictly bbox-restricted — no whole-page fallback. A miss surfaces "couldn't pinpoint" instead of a silent wrong highlight. (3) Always-visible `CitedTextPanel` below the PDF page renders the chunk's verbatim text with the cited span underlined — verify-by-eye surface for both happy and miss cases. Plus a sidecar-side change: `_validate_one_cite` now rejects quotes that appear multiple times in chunk.text, returning up to 3 positions in the error so the model picks a longer, unique quote on retry. Plan at `docs/superpowers/plans/2026-05-20-citation-accuracy-and-per-sentence-chips.md`. Spec at `docs/superpowers/specs/2026-05-20-citation-accuracy-and-per-sentence-chips-design.md`.

---

## What's open

### Modeling / behavior gaps
- **Model meta-narration leaks** ("Retrying the cites…", "All cites anchored", "Task tracking isn't relevant…") still appear in user-visible answer prose despite Task 12's Output-hygiene rewrite. The prompt-only fix isn't sufficient; needs another pass and possibly a mechanism-level intervention (e.g. stripping retry-narration text in the renderer before display).
- **Model occasionally writes verbose `claim_spans` that don't substring-match the rendered answer** — soft-fixed by the cite_batch + resolved-offsets work but not eliminated; chip attachment still fails when the model rewrites prose between cite() and final emission.

### PDF viewer accuracy (failure mode catalog — updated post-Wave E)
- **A. Source isn't a PDF (DOCX legislative bills).** UI still shows "Couldn't open source PDF" but the new always-visible `CitedTextPanel` below the viewer now shows the chunk's verbatim text with the cited span underlined, so the analyst can verify the cite even without a PDF viewer. #55's broader DOCX viewer is still a separate concern.
- **B. PDF exists, text-layer search fails to find the quote.** "Couldn't pinpoint" badge — same surface, but now the CitedTextPanel underneath shows the cited span in chunk text, so a miss is recoverable rather than dead-end. **Architectural fix still queued (#57):** capture chunk_text→PDF-coord mapping during ingest. Wave E added the `HighlightStrategy` interface so #57 can drop in as a `CoordMapStrategy` without rewriting `PdfPage`.
- **C. PDF exists, chunk's stored bbox is wrong** (MinerU mis-detection). Now produces an honest "couldn't pinpoint" badge instead of a silent wrong highlight, since Wave E removed the unrestricted-search fallback. Ingest QA still out of scope.
- **D. Citation references a chunk_id from a prior turn with no metadata** in the current turn's retrieve. `buildConversationResolvedChunkMap` exists for cross-turn fallback but is sometimes missing chunks. **Diagnosis queued (#56):** verify whether the cross-turn map is consulted, identify where the lookup fails.
- **E. Quote is ambiguous (appears multiple times in chunk.text).** Used to silently bind to the first occurrence → wrong-bbox highlight. Wave E rejects these at validate time so the model must pick a longer, unique quote.

### Not yet implemented (per the Phase 1c plan)
- **Faithfulness verifier (WS3).** Post-generation NLI-style check that strips claims whose cites don't actually back them. Core Invariant 2 says "citations are verified, not just emitted" — current enforcement is chunk_id + quote-in-chunk-text (catches invented chunks/quotes, not semantic faithfulness). The dropped `_check_alignment` was a string-overlap proxy, not real faithfulness. WS3 is the real fix.
- **Audit log writer (WS5).** No persistent record of `(retrieval_id, citation_id, claim_span, intent)` tuples for offline review. Schema-side hooks are in place — `retrieval_id` flows through retrieve() responses, `intent` echoes back, JSONL bridge log captures call-level data — but no DB writer.
- **Layer 2 eval (open-ended analyst queries, LLM-as-judge or rubric scoring).** Layer 1 (chunk-recall regression detector) shipped 2026-05-22 — see "Eval harness" subsection above. Layer 2 is what measures real analyst usefulness: open-ended queries like "spending on homelessness projects?" with multiple acceptable chunks per answer. Deferred until WS3 (faithfulness verifier) ships, since end-to-end scoring depends on it. See [eval/README.md](eval/README.md) for the framing.
- **DOCX viewer (Phase 2).** Bills are DOCX; the Phase 2 plan adds an inline DOCX viewer. Until then, #55 (text-only fallback) is the stopgap.

### Volume ingest — current corpus
**382 documents / 7,755 chunks** as of 2026-05-12. These counts are
pre-Plan-3: the GUI ingest queue adds documents whenever someone uploads,
so the live numbers come from `/health` and `GET /api/jobs`, not this
table. Coverage at the 2026-05-12 snapshot:

| Publisher | FY 2025 | FY 2026 | FY 2027 |
|---|---|---|---|
| JLBC | Approps Report (111 per-agency) | Baseline (110 per-agency + 6 bd-pdf + 7 bh-pdf + 16 detailed-list + 2 topic) | Baseline (110 per-agency + 15 s-pdf + 2 topic) |
| Legislature | — | budget-bill | — |
| Governor | — | — | Executive Budget |
| AGAO | AFR (1) | — | — |

**Known gaps to fill** (none blocking but worth scoping):
- Older FYs entirely — FY24, FY23, FY22 baselines + approps reports + AFRs
- FY 2026 Approps Report (summarizes what actually passed in 2025 session)
- FY 2027 Approps Report / Budget bill (if/when it passes)
- Older Governor's Budgets (FY26, FY25)
- AGAO AFRs for FY24 and FY23

Backfill now goes through [`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md)
(`PROMPT-volume-ingest.md` is retired — superseded by the Plan 3 GUI queue).

### Open follow-up tasks (tracked in TaskList)
- **#45** — Investigate `(unknown)` tool card after Item 1 ships (verification-only; needs a fresh dogfood transcript)
- **#55** — DOCX chunk fallback (render chunk text inline when no PDF backing)
- **#56** — Diagnose cross-turn metadata gap
- **#57** — Capture chunk→PDF coord map during ingest (architectural PDF-accuracy fix)
- **#58** — Post-mortem: 2026-05-20 dogfood revealed 4 distinct fix categories worth documenting

### Recently fixed — verify in next dogfood pass
- BM25 query parser crashed on apostrophes (#47) — fixed by sanitizing tantivy/Lucene special chars before query string reaches pg_search. 14 of 34 eval queries previously aborted; now 0 crash.
- MCP refusal threshold raised from 0.30 → **0.65** in mcp-server/system-prompt.md (2026-05-22). Old 0.30 was effectively dead — Voyage rerank scores on the current corpus sit at 0.56–0.93, never below 0.56. Calibration recommended 0.70 (refusal recall 0.80, precision 0.67, retrieval pass-rate 0.93); 0.65 picked as a slightly more conservative starting point (refusal recall 0.60, retrieval pass-rate 0.93). Dogfood for real failure modes; re-calibrate after any meaningful corpus or rerank-model change.
- Restated facts across multiple sentences only chipped the first occurrence (per-sentence placement + key-fact-token rule)
- Wrong yellow rectangle when bbox-restricted search missed (strict-bbox, no whole-page fallback)
- Source text only visible inside the PDF (always-visible `CitedTextPanel` below the page)
- Quote-ambiguity silent wrong highlights (sidecar duplicate-quote rejection)
- Citation chips weren't rendering at all (citation-extract required offsets; now accepts quote-only)
- Failed retries weren't collapsing with their successful replacements (FIFO-pair-fail→OK dedup)
- 40% cite() false-rejection rate (dropped alignment heuristic)
- 60s+ tool round-trips on analyze-shaped answers (cite_batch single round-trip)
- "Couldn't pinpoint" PDF badges (resolved-offsets passthrough)
- ToolSearch round-trips at session start (added to deny list)
- "Show me X" classifying as Analyze and pulling 25 chunks (route-classifier defaults to Lookup; analyze lowered 25→18)
- First retrieve always pulling too many chunks regardless of question shape (progressive-retrieval first-call cap)

---

## Repo + portability

### Single git repo
Everything lives in `ask-the-budget-az-dev` →
`github.com/itsdestin/ask-the-budget-az-dev`. No multi-repo workspace,
no submodules.

### What's tracked vs not
- **Tracked:** all source, the MinerU manifests, the JLBC primer, agency/fund catalogs, raw DOCX user uploads (samples/raw-docx/), test fixtures
- **Gitignored:** `node_modules/`, `.venv/`, `db/data/` (Postgres volume), `data/cached-pdfs/`, `data/extractor-output/`, `data/chunks/*` (except MANIFEST.md), `data/insight-data/` (LanceDB corpus + documents.json), `.env.local`, build outputs

### What must travel for a fresh device
1. **The LanceDB corpus** — copy the whole `data/insight-data/` directory
   (the `lancedb/` folder AND `documents.json` — the sidecar is what lets
   the PDF viewer locate sources; without it search still works but PDFs
   won't open, visible as `documents_metadata: 0` on `/health`). Retrieval
   is then live with zero external services — no Docker, no keys.
2. **`data/cached-pdfs/`** — the PDFs themselves (the viewer streams from
   here; re-downloadable from public URLs if lost).
3. **`<data_dir>/settings.json`** — only if AI Mode should work on the new
   machine. It carries the OpenRouter key, the tier→model map, the admin
   username and the spend limits. Without it the app runs fine and AI Mode
   reports `no API key configured`, which is the honest state, not a crash.
   It is plain JSON on the share by design (spec S11) — the protection is a
   hard monthly credit cap set on the OpenRouter dashboard, not file secrecy.

**Nothing else travels.** Post-Plan-3 there is no `.env.local` and no Postgres
volume on any path — ingest, retrieval and AI Mode all run off `data_dir()`
plus one optional key.

See [README.md → Moving to a new device](README.md#moving-to-a-new-device) for the exact commands.

### What's installed externally (NOT in the repo)
- Node 20+ and npm (build-time only — the shipped app serves a static bundle)
- Python 3.12 and `uv` (`pip install uv`)
- **Nothing else.** Docker/Postgres were ingest-only after Plan 1 and unneeded
  after Plan 3. The YouCoded/Claude Code dependency (`ws://localhost:9900`)
  died with Plan 4 — AI Mode is an in-process OpenRouter tool loop. An
  OpenRouter key unlocks AI Mode and nothing else; search, fiscal notes and
  upload all work with zero keys, which is a hard spec constraint ("no paid API
  is load-bearing").

---

## Working conventions

- `setup.sh` — one-shot installer for everything regenerable. Run after `git clone`.
- `bash setup.sh --verify` — runs all suites (pytest + 3× vitest). Use before
  merging non-trivial work. Two of those suites (`mcp-server/`, `web/`) cover
  code Plan 4 retired; Plan 5 deletes the suites and the directories together.
  **Capture its exit code directly** (`bash setup.sh --verify > log 2>&1; echo $?`)
  — piping it into `tail` returns `tail`'s status and hides a failure.
- **One process now.** `uv run uvicorn app.main:create_app --factory --port 9300`
  serves the API and the built `webapp/dist`. `npm` is used to build `webapp/`;
  `mcp-server/` and `web/` are dead weight until Plan 5.
- The launch order is: build `webapp/`, then start the one server. There is no
  Docker step, no sidecar, no MCP registration, and no desktop app to run first.

---

## Doc map

Current architecture first:

- [docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md](docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md) — **the consolidation spec** (S1–S21, Invariants 7–8, gates G1–G3). Read this before non-trivial changes.
- [docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md](docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md) — Plan 1: LanceDB + local models (shipped 2026-07-30)
- [docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md](docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md) — Plan 2: app server + search UI (shipped 2026-07-30; its frozen API-contract block is what later plans build against)
- [docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md](docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md) — Plan 3: GUI ingest queue (shipped 2026-07-31)
- [docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md](docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md) — Plan 4: AI Mode (shipped 2026-07-31; see its "Task 8 amendments" for the as-shipped HTTP contract)
- [docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md](docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md) — recency-ranking plan (S21; pending)
- [docs/superpowers/specs/2026-08-12-admin-extensions-design.md](docs/superpowers/specs/2026-08-12-admin-extensions-design.md) — admin extensions design (E1–E6; E4 and E5 are future direction, nothing was built for them)
- [docs/superpowers/plans/2026-08-12-admin-extensions.md](docs/superpowers/plans/2026-08-12-admin-extensions.md) — admin extensions plan, 14 tasks (shipped 2026-08-13, merge `b108d13`). Its task checkboxes were never ticked and its code blocks are sketches — several were wrong about this codebase and were corrected during execution. **Read the STATUS section above for what actually shipped**, not this plan
- [PROMPT-z13-backfill.md](PROMPT-z13-backfill.md) — ~~the only active handoff~~ **COMPLETE — historical runbook** (backfill + recency calibration finished 2026-08-02)
- [README.md](README.md) — how to run it, links
- [STATUS.md](STATUS.md) — this file (current state)
- [CLAUDE.md](CLAUDE.md) — workspace conventions for Claude Code sessions
- [eval/README.md](eval/README.md) — Layer 1 retrieval eval harness: when/how to run, scoring rules, caveats, calibration interpretation

Historical (retired architectures; kept as record, do not build against):

- [docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md) — original design spec (invariants live on; architecture superseded)
- [docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md](docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md) — twelve interlocking decisions for Phase 1b/1c (superseded by the consolidation spec)
- [docs/superpowers/decisions/2026-05-06-citation-tool-schema.md](docs/superpowers/decisions/2026-05-06-citation-tool-schema.md) — locked `retrieve()` + `cite()` schema (semantics carried into `harness/tools.py`; MCP/sidecar transport gone)
- [docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md](docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md) — dogfood-hardening pass against the retired stack
- [docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md](docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md) — dogfood-test plan for the output-hygiene rewrite
- [docs/superpowers/plans/](docs/superpowers/plans/) — phase plans (not kept in sync with shipped features)
- [data/chunks/MANIFEST.md](data/chunks/MANIFEST.md) — Phase 1a → Phase 1b hand-off contract (live ingest contract is `ingest/` + `store/schema.py`)
- [docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md](docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md) — eval harness spec (Layer 1; amended 2026-05-22 with what shipped vs diverged)
- [docs/superpowers/plans/2026-05-20-retrieval-eval-harness.md](docs/superpowers/plans/2026-05-20-retrieval-eval-harness.md) — eval harness implementation plan (shipped 2026-05-22, merge `3a26c19`)
- [PROMPT-volume-ingest.md](PROMPT-volume-ingest.md) — retired volume-ingest handoff (superseded by the Plan 3 GUI queue)
