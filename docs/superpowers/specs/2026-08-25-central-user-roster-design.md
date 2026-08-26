# Central user roster — design

**Date:** 2026-08-25 (revised same day after review)
**Status:** design approved by Destin; spec revised after review; **UI shape
approved from the mockup 2026-08-25 (G-U0 passed)** — ready for an
implementation plan
**Decisions:** U0–U16 · **Gates:** G-U0, G-U1, G-U2, G-U3

**Revision note (2026-08-25).** The first draft had two design defects and
one broken promise, all found by checking it against the code: (1) U2's
"append a hash when sanitising changed anything" gave `DMOSS` and `dmoss`
DIFFERENT files, defeating U9; (2) hide/unhide had the admin's machine
rewrite another person's roster file while that person's machine could be
touching it — two writers, no lock, and a daily touch could silently
un-hide someone; (3) U6 put a shared-drive read on `/api/me`, the request
U4 promised would never wait on the share. All three are fixed below.
`hidden` now lives in `settings.json`, roster files are observation-only
and single-writer, and username identity is decided by ONE rule (U0).

---

## The problem, as measured

The app has never recorded that a person exists. Every request asks the
operating system "who is running me right now", uses the answer once, and
forgets it. There is no user record on the share, in the corpus, or in
settings.

Five surfaces consume a username. Three of them require the administrator
to type it by hand, having first asked the person what Windows calls them.

| Surface | Today | Failure when wrong |
|---|---|---|
| Who may open Admin (`settings.admin_username`) | free-text box, `webapp/src/admin/AdvancedPanel.tsx:59` | locks **both** people out; recovery is hand-creating `RESET-ADMIN.txt` on the share |
| Per-person spend limit (`settings.user_limits`) | two boxes per row, `webapp/src/admin/ProviderPanel.tsx:261` | row matches nobody. Saves cleanly, looks set, does nothing. **No warning anywhere.** |
| No-limit list (`settings.exempt_users`) | one comma-separated box, `ProviderPanel.tsx:310` | same silent no-op |
| "Who spent what" table | read-only, raw usernames, `CostsPanel.tsx:147` | admin must decode `bjw2` unaided |
| Issue-report inbox | read-only, raw `submitted_by`, `IssuesPanel.tsx:136` | same |

**Matching is exact and case-sensitive by deliberate choice**, in TWO
places: `harness/settings.py::limit_for` and `app/identity.py::is_admin`.
`dmoss` and `DMOSS` are two different people to both. Both comments justify
it on the grounds that folding would silently merge two rows *an admin
typed* — sound reasoning while rows are typed, and the reason U0 below can
reverse it once they are not.

**Windows itself does not keep the casing stable.** `getpass.getuser()`
reads `%USERNAME%`, which reflects how the person typed their name at
logon. The same analyst can therefore arrive as `DMOSS` one day and
`dmoss` the next. Today that splits their ledger rows, misses their limit
row, and — for the admin — is the `destin` vs `Destin` lockout the
`is_admin` docstring already warns about.

**Real names exist and are stranded per-machine.** `app/machine_config.py`
stores `display_names` in `%LOCALAPPDATA%\machine.json`, explicitly not on
the share (spec M6), because `save_settings` is a read-modify-write on a
file ~20 machines share that also holds the OpenRouter key. The
consequence is that the administrator **cannot see anyone's real name**,
which is the direct cause of "go ask them their username".

**The nearest thing to a roster today is an accident.** `harness/ledger.py`
stamps a username on every AI call, so `breakdown(month, by="user")`
incidentally enumerates people — but only those who used AI Mode, only
within one month shard, and the list resets when the month rolls over.

**Four separate implementations answer "who is this?"**
`app/identity.py::current_user` honours the `JLBC_USER` override and falls
back to `""`; `ingest/jobs.py:667`, `ingest/claim.py:366` and
`ingest/lock.py:408` each carry a private `_current_user()` that ignores
the override and falls back to the string `"unknown"`. Nobody sees this
today, and it means an uploaded document can be stamped with a different
name than the same person's AI usage.

---

## Scope

**In:** a shared user roster, automatic registration, central names, an
admin People panel (sortable, with spend and limit editing), dropdowns
replacing every typed username, one canonical username resolver, one
canonical username-identity rule.

**Out:** authentication of any kind. This roster is an accounting and
convenience record, exactly as S11 says of the ledger. The admin gate
stays SOFT and nothing may be moved behind it that would be harmful if
bypassed. Also out: a non-admin roster surface (U15), deleting the
by-person spend tab (U16), any change to how conversations or transcripts
are stored.

---

## Decisions

### U0 — ONE rule decides whether two usernames are the same person

Stated once, in `users/whoami.py`, used everywhere a username is compared:

    same_person(a, b)  ⇔  a.strip().casefold() == b.strip().casefold()

and its key form, `roster_key(username)`, is what U2 derives a filename
from. Every consumer below uses this rule and NO other:

| Consumer | Today | After |
|---|---|---|
| `Settings.limit_for` (`user_limits`, `exempt_users`) | exact | U0 |
| `app.identity.is_admin` | exact | U0 |
| roster filename (U2) | — | U0 |
| the ledger ↔ roster ↔ settings join in `GET /api/admin/users` | — | U0 |
| the "does this stored key belong to someone in the roster?" check (U14) | — | U0 |
| the transfer picker's "is this the current admin?" | — | U0 |

**Why one rule and not a fold at each call site:** the CLAUDE.md audit
lesson — when a field has more than one producer, the defect is the
producers disagreeing. Four independently-written folds WILL drift (one
strips, one doesn't; one folds, one lowercases). A source-level guard
pins that `.casefold()` and `.lower()` are not called on a username
anywhere outside `users/whoami.py`.

**Why folding is now right when it was wrong before.** The two exact-match
comments refused folding because it would silently merge two rows an
admin *typed*. Once every row comes from a dropdown keyed on the roster,
the UI cannot create two rows for one person, so the thing folding
protected against cannot happen — and the thing it caused (a limit or an
admin seat that silently fails to apply on a day Windows capitalised the
name differently) is the larger cost.

**The guard is not optional:** where two stored keys fold to one person
(a legacy `user_limits` with both `DMOSS` and `dmoss`), the exact match
wins and the People panel renders a warning on that row naming both keys.
Silently picking one is what the original comments were right to refuse;
saying so on screen is the honest version.

**Scope of the fold is the app's own comparisons only.** The ledger keeps
writing the observed username verbatim (an accounting record must not
rewrite what it saw); the fold happens when the People panel groups those
rows. `harness/settings.py` implements U0 as a self-contained three-line
fold with no new import — **Invariant 7 unchanged**.

### U1 — The roster is one small file per person, holding OBSERVATIONS only

`<data_dir>/users/<key>.json`. **Not** one shared list.

A single shared list would mean ~20 machines rewriting one file, which is
precisely the risk that kept names off the share in the first place (M6).
One file per person makes collision structurally impossible **because a
file is only ever written by the machine its own user is sitting at** —
and that property is load-bearing, which is why nothing an ADMIN decides
lives in these files (see U7). Two existing precedents take the same
shape for the same reason — `ingest/jobs.py` (one JSON per job) and
`app/issue_reports.py` (one JSON per report), both of which say in their
docstrings that a folder of small JSON files is chosen so a colleague with
no code access can read it in Notepad.

A torn file therefore costs one person's row, not the roster, matching
`app/issue_reports.py`'s degradation model rather than
`harness/settings.py`'s.

Row shape:

```json
{
  "version": 1,
  "username": "dmoss",
  "display_name": "Danielle Moss",
  "name_source": "windows",
  "first_seen": "2026-08-25T09:14:03-07:00",
  "last_seen":  "2026-08-25T09:14:03-07:00"
}
```

No `hidden` field — that is admin intent, and it lives in `settings.json`
(U7). `version: 1` is stamped for the reason the chat transcripts stamp
it: a file with no stamp reads back as 0, so "written before versioning"
and "written today" stay distinguishable, and that cannot be added
retroactively.

### U2 — The filename is the U0 key; the file holds the observed username

Windows SAM names disallow `" / \ [ ] : ; | = , + * ? < >`, but a
domain-qualified name can carry a backslash, and Windows filenames are
case-insensitive while Linux (dev, CI) filenames are not. Deriving the
filename from the raw username would fold cases on one platform and not
the other.

`roster_key(username)`: take `username.strip().casefold()` (the U0 form),
replace every character outside `[a-z0-9._-]` with `-`, truncate to 64
characters, and append an 8-character hash **of the casefolded form** when
the replacement or truncation changed anything.

**The hash is of the casefolded form, not the original — this is the
correction from review.** Hashing the original would give `DMOSS` and
`dmoss` different files, which is the exact split U0 exists to remove.
Pinned by test: `roster_key("DMOSS") == roster_key("dmoss")`, and a name
needing sanitisation still yields one key for all its casings.

The `username` field inside the file is the **most recently observed**
spelling, updated on each touch, and is what dropdowns display. Case
folding is thus a deliberate, cross-platform-identical decision (U0), not
an accident of the filesystem.

### U3 — Registration happens on `GET /api/me`, at most once per person per day

`webapp/src/components/Header.tsx:45` calls `/api/me` on every page load on
every route, to decide whether the Admin pill renders. That is already the
one request every user makes, so it is where a person gets written down.

`last_seen` is bucketed to the **calendar day** (Arizona-local, matching
`harness/ledger.py`'s fixed UTC-7 shard rule). A write happens only when
the day changed, the observed username spelling changed, the Windows name
changed (to a NON-EMPTY value — see U5), or the person is new. Twenty
people is therefore ~20 tiny writes per day office-wide, not one per page
load.

### U4 — Registration is background, never blocking, never raising — and so is the READ that decides it

The touch — **including the read of the person's existing row that
decides whether anything changed** — runs in a Starlette `BackgroundTask`
on the `/api/me` response, so a slow or unreachable share cannot delay the
request that decides whether the nav renders. Every failure is caught,
printed to stderr with the real error, and dropped. **`/api/me` must
behave identically whether or not the roster write succeeds.**

This is the opposite posture to `harness/ledger.py::record_usage`, which
raises — and deliberately so. A missing ledger row means money was spent
and not recorded, which the caller must know. A missing roster touch means
a `last_seen` date is a day stale.

`/api/me` is a plain `def` route returning a dict today; it becomes a
`JSONResponse(..., background=BackgroundTask(...))` with the same body.

### U5 — A name auto-fills from Windows and is never overwritten once typed

Resolution order for what the roster records:

1. A name the person typed on their Settings page → `name_source: "typed"`.
   **Never** overwritten by a later Windows read.
2. Otherwise, `GetUserNameEx(NameDisplay)` — the AD full name the app
   already reads for memo signatures (`app/identity.py::_windows_display_name`)
   → `name_source: "windows"`, refreshed on each touch **only when the read
   returns a non-empty string.** `_windows_display_name()` returns `""` on
   ANY failure (no domain, no `secur32`, a transient error), and a blank
   must not erase a good name.
3. Otherwise, no name. The row shows the username alone.

**Clearing a typed name.** `machine_config.set_display_name` already
treats a blank save as "forget it" so that "never set" and "cleared" are
one state. The roster does the same: a blank save removes the typed name
and `name_source` falls back to `"windows"` or none on the next touch.

On a domain-joined office the roster therefore arrives populated with real
names with nobody typing anything.

### U6 — `display_name()` gains the roster as its top source; the local file becomes a fallback — and the read must be CHEAP

New order: **roster typed name > local typed name > Windows > username.**

This preserves M5's reversal (a typed override must beat auto-detection,
because a *wrong* AD name is likelier than a missing one) and preserves
M6's reason for the local file — it is still what answers when the share
is unreachable.

**The cost, and the rule that bounds it.** `display_name()` is called on
the request path of `/api/me` (`app/routes/admin.py:194`, every page load
on every machine) and of every new conversation
(`app/routes/conversations.py:384`). The first draft put an unbounded
share read there, contradicting U4. So:

- It reads **only the caller's own file** — one `open()` on a known path,
  never a directory listing.
- The result is **cached on the file's `(mtime_ns, size)` stamp**, the
  shape `store/office_agencies.py` already uses, so a page load that
  follows another page load costs one `stat()`.
- **Any failure — missing, unreadable, torn, timed out — falls through to
  the local name immediately.** A memo signature is not worth a blocked
  request. This is pinned by a test that makes the read raise and asserts
  the local name comes back with no exception.

`PUT /api/me/display-name` writes the roster **and** the local machine
file. Writing both is not redundancy: the local copy is the offline
fallback. If the roster write fails, the local write still succeeds and
the endpoint still returns 200 — but the response is whatever
`display_name()` resolves at that moment, not necessarily the name just
typed, because `display_name()` reads the roster first. If a roster row
with a typed name already exists and only this roster write fails, the
response carries the PREVIOUS roster name — the ladder is telling the
truth about what a memo generated on this machine WILL print (the roster
name, whenever the share can be read). The Settings page renders the
returned value, so the analyst sees the save did not fully take and can
retry once the share is back, rather than being told a name took effect
that the roster does not actually hold. (Found in review, 2026-08-25.)

**Known limit, accepted:** a name typed on two different PCs before this
ships can leave the roster and one local file disagreeing; online the
roster wins, offline that PC's local name wins, so the memo signature can
differ by network state on that one machine. The migration below makes
this rare, and the Settings page shows the resolved name so the person
can see and fix it.

**On first touch, an existing local typed name is migrated up** to the
roster as `name_source: "typed"` if the roster has no typed name. Nobody
re-types what they already entered. **⚠ This copies a name the person
typed for their own machine onto the shared drive without asking them** —
listed under "Calls for Destin to confirm" below, because it is a stance
change, not a mechanism.

### U7 — Hidden, never deleted — and `hidden` is admin config, so it lives in `settings.json`

`hidden_users: []` is added to `settings.json` beside `user_limits` and
`exempt_users`, written through the existing `PUT /api/admin/settings`
with the existing `_validate` (same blank-username rule). **No
hide/unhide routes; nothing under `<data_dir>/users/` is ever written by
anyone but its own user.**

Why here and not in the roster file (the first draft's shape): hiding is
something the ADMIN decides about someone ELSE. Putting it in that
person's roster file makes the admin's machine a second writer on a file
the person's own machine touches daily, with no lock — and a touch that
read the row before the hide and wrote after it would silently un-hide
them. Moving it to `settings.json` removes the race outright instead of
adding a lock to manage it, and puts it where every other per-person
admin decision already is.

A hidden person is removed from every dropdown and from the People table,
collapsing to one line beneath it with a **Show** pill (U13). Their ledger rows are untouched and still
count in office totals — **deleting a person would make last year's spend
stop adding up**, and the ledger is the accounting record.

If a hidden person opens the app again, their roster `last_seen` updates
as normal (their own machine writes their own file — nothing about hiding
touches that path), and the People table shows "seen since hidden" beside
them. The hidden flag is not cleared automatically; that is the admin's
call.

**No inactivity auto-hide.** An analyst on leave or secondment would
silently lose their limit row, and a limit that quietly stops applying is
the exact class of failure this whole change exists to remove.

### U8 — Spend limits stay in `settings.json`; the roster supplies the keys

`user_limits` and `exempt_users` are not moved. They are admin-only
configuration, already validated in `app/routes/admin.py::_validate`, and
moving them buys nothing while costing a migration. (`hidden_users` joins
them for the same reason — U7.)

The People panel presents them as **one control per person** —
*office default* / *a specific amount* / *no limit* — written back through
the existing `PUT /api/admin/settings`. Storage mapping:

| Control | Storage |
|---|---|
| office default | absent from both fields |
| a specific amount | `user_limits[username] = n` |
| no limit | listed in `exempt_users` |

Setting one clears the other, so a person can never be in both — which is
possible today and resolved silently by `limit_for`'s exempt-wins rule.
The key written is the roster's current observed spelling; U0 makes the
spelling irrelevant to lookup.

### U9 — (merged into U0)

Kept as a number so earlier references resolve. The case-insensitive
matching and its visible guard are U0, applied to `is_admin` as well as
`limit_for` — the first draft folded only `limit_for` and left the admin
gate's identical reasoning untouched.

### U10 — Every typed username box becomes a dropdown

- Admin transfer (`AdvancedPanel.tsx`) → a picker of non-hidden people,
  excluding the current admin (U0 decides "current").
- Per-person limits (`ProviderPanel.tsx`) → deleted; replaced by the People
  panel's per-row control. The **office-wide default stays where it is** —
  it is not about an individual. **Consequence to see at the mockup:**
  "limits" then lives in two panels, a default in one and per-person in
  another.
- Exempt list (`ProviderPanel.tsx`) → deleted; folded into the same control.

**The day-one state is its own state.** U11 says a successor must open
the app before they can be handed admin, so on the day it matters the
picker is *reachable and has nobody to offer*. That is not U12's
"unreachable" and must not render as a blank select. The picker says
"Nobody else has opened the app yet" and offers nothing. A fresh install
with one person is the common case, not an edge.

### U11 — Admin transfer is dropdown-only (no typed escape hatch)

Destin's call, 2026-08-25. A successor must open the app once before they
can be handed admin. That is a thirty-second ask, it removes the single
most dangerous typo in the product, and the genuine emergency — successor
unreachable, current admin gone — is already covered by the documented
`RESET-ADMIN.txt` path.

Recorded as a deliberate door closing, not an oversight.

This does not conflict with U12. U11 governs normal operation; U12 governs
the degraded case where the roster cannot be READ at all, where a picker
would be empty and therefore useless. A typed box behind a "we could not
read the people list" message is a different thing from a typed box
offered as an everyday convenience.

### U12 — An unreachable share must never render as "there are no people"

The roster reads empty when the folder is unreadable, and empty is also
what a brand-new install looks like. The two are **different facts and the
app must say which it has** — the same lesson `app/routes/issues.py` and
the books panel each learned the hard way.

`GET /api/admin/users` returns `unreachable: true` when the directory
cannot be listed, distinguished from an empty listing the way
`app/issue_reports.py:102` does it (`os.listdir`, not `Path.glob` —
pathlib swallows the error, and a guard written around `Path.glob` has
been proven on this project to be dead code).

The realistic failure is PARTIAL — the folder is unreadable, or a
permission changed — not a share that has vanished entirely. A share that
is wholly gone is caught upstream by the launch health ladder, and
`load_settings` already degrades a missing `settings.json` to defaults, so
the admin page is in a different conversation by then. `store/config.py`'s
`data_dir()` also CREATES the directory as a side effect, so the roster
folder's absence must be told from its unreadability the way
`app/health.py` discriminates on the root data dir — not inferred from an
empty listing.

When `unreachable` is true:
- The People panel says the folder could not be read, and shows nothing else.
- **Every dropdown degrades to today's free-text box** with today's warning
  copy, rather than to an empty, unusable picker.
- A count of individually unreadable rows is reported and displayed
  ("2 people's records couldn't be read"), never silently omitted.

### U13 — ONE People table, sortable on every column, both directions

**Proposed shape, pending G-U0.** One table, every person in it. Hidden
people are not rows in it: they collapse to one line beneath the table
("1 person hidden (Pat Chen, last seen Jun 30) · Show"), which expands
them in place. There is no Status column and no orphan section (U14).

The first draft had three separate tables (active / "No longer here" /
orphan limits) sharing an extracted `SortableTable`; the second had one
table with a Status column, a "show hidden" tick box and a flagged
orphan box. Destin rejected both as too complicated at the mockup
(2026-08-25). What stands is the plain table above, one action pill per
row (**never** bare link text — his standing rule), and one collapsed
line for the hidden.

Click a heading to sort; click again to reverse. An arrow in the heading
states which column and which direction, and `aria-sort` carries the same
fact to a screen reader.

| Column | First click | Second click |
|---|---|---|
| Name | A→Z | Z→A |
| Username | A→Z | Z→A |
| Last seen | most recent first | longest-absent first |
| Spent this month | highest first | lowest first |
| Monthly limit | highest amount first, then office default, then no limit | reversed |

Default is **highest spend first**, matching today's table, because that is
the question the page is usually opened to answer (to confirm at G-U0).

One ordering is explicit rather than emergent: a person with **no
recorded name** sorts LAST in a name sort **in both directions**.
Reversing a sort must not promote the least informative rows to the top
of the page. Every row has been seen — a roster file only exists because
somebody opened the app — so there is no never-seen case.

### U14 — A limit for a username nobody has matched is NOT shown

Destin's call, 2026-08-25, from the mockup: a box announcing *"a limit is
set for `tmartin` but nobody by that name has opened the app"* is wasteful
and confusing. It does not render.

Any key in `user_limits`, `exempt_users` or `hidden_users` that matches no
roster person **under U0** is left exactly where it is in `settings.json`
— not shown, not deleted, not warned about. It applies to nobody, so it
costs nothing; and if that person ever opens the app, their row appears
with that limit already on it. The first draft surfaced these as a
"never seen" section; that section is gone.

**One exception, and it is the U0 collision guard, not an orphan
notice:** if a stored key folds to a person who IS in the roster under a
different spelling (`DMOSS` in `user_limits`, `dmoss` in the roster), that
is the same person and the row shows their limit — with the exact-match
rule deciding which value wins when both spellings are stored (U0).

### U15 — The People panel is admin-only

Destin's call, 2026-08-25. It lives on the Admin page and its rows carry
spend figures. A plain everyone-can-see roster would need to be a separate
surface with the money removed — more build for less value.

Non-admins get **no** new endpoint. `GET /api/admin/users` sits behind
`require_admin` exactly like `/api/admin/usage`.

### U16 — The by-person spend tab is left alone

The People table shows the same per-person spend, sortable, with real
names. The "Who spent what → by person" tab therefore becomes largely
redundant. It is **not** deleted here: removing a working screen as a side
effect of an unrelated change is how surprises get introduced. Recorded so
whoever notices the duplication knows it was seen and left deliberately.

The *by model* and *by answer mode* tabs are unaffected.

---

## Calls settled at the mockup (G-U0, 2026-08-25)

Destin approved the third version of the mockup ("okay this is fine")
after rejecting two: the first for too many columns, badges and boxes,
the second for its stray-limit notice. What that approval fixes:

1. **The table as drawn** — one row per person (name with the username in
   small type beneath), Last seen, Spent this month, Monthly limit as a
   dropdown on the row, one **Hide** pill per row, hidden people as one
   collapsed line beneath with a **Show** pill.
2. **Default sort: highest spend first.**
3. **Placement:** its own section directly above Spending; the
   office-wide default stays in AI Mode → Spending limits with a one-line
   pointer to People.
4. **Real names from Windows are written to the shared drive** (one small
   file per person) — accepted as stated on the mockup page.
5. **A name already typed on someone's own PC is copied up to the share**
   on their next visit, without asking — accepted as stated.
6. **No orphan-limit notice** (U14); **no Status column, no "show hidden"
   tick box** (U13); **every action is a pill, never bare link text** —
   a standing rule, not a per-screen choice.

---

## Components

| Module | Responsibility | Depends on |
|---|---|---|
| `users/whoami.py` (new) | The ONE answer to "who is this process running as": `JLBC_USER` override > `getpass.getuser()` > `""`. Plus `same_person()` and `roster_key()` (U0, U2). | nothing but stdlib |
| `users/registry.py` (new) | Read one / list all / touch. Degrades on read, raises on write. **No hide.** | `store.config`, `users.whoami` |
| `app/identity.py` | Re-exports `current_user` from `users.whoami` so no existing caller changes. `is_admin` compares under U0. `display_name()` gains the cached, fail-fast roster source (U6). | + `users.registry` |
| `ingest/{jobs,claim,lock}.py` | Their three private `_current_user()` copies are replaced by `users.whoami.current_user`. **Behaviour note:** those copies fell back to the string `"unknown"`; the resolver falls back to `""`. The three call sites keep `or "unknown"` so job records, claim files and the lock owner read the same in Notepad as before — the only change is that `JLBC_USER` is now honoured there too. | + `users.whoami` |
| `app/routes/admin.py` | `GET /api/admin/users` (merged payload). `/api/me` gains the background touch. `PUT /api/me/display-name` writes both stores. `PUT /api/admin/settings` accepts `hidden_users`. | + `users.registry` |
| `harness/settings.py` | `hidden_users` field; `limit_for` folds per U0 with a three-line self-contained fold. No new import. | unchanged |
| `webapp/src/admin/PeoplePanel.tsx` (new) | The one table, the sort, the per-row limit control, hide/unhide (a settings write), the status column. | `api.ts` |
| `webapp/src/admin/{AdvancedPanel,ProviderPanel}.tsx` | Typed boxes → picker; per-person limit rows deleted. | `api.ts` |

**`users/` is a new top-level package**, matching `funds/`, `citation/`,
`memo/`. `users/whoami.py` is a leaf with no first-party imports so that
`ingest/` can use it without importing `app/` (the dependency runs
`app → ingest`, and reversing it would be circular). It ships in the
Windows bundle automatically — `packaging/build_bundle.py` selects app
files via `git ls-files` (verified for `harness/guides/` in the
document-guide work), so the only thing to remember is to stage the files.

**Invariant 7 is unaffected.** Nothing under `harness/` imports `users` —
`limit_for`'s fold is self-contained — so no allowlist changes. If a later
change needs it, `users/registry.py` writes files and must NOT be admitted
wholesale; admit a read-only module the way `funds/names.py` was.

---

## Data flow

```
page load  →  GET /api/me
                 ├─ responds immediately (unchanged shape; display_name via
                 │  the cached single-file roster read, falling through to
                 │  the local name on ANY failure)
                 └─ BackgroundTask: users.registry.touch(username, windows_name)
                        ├─ reads <data_dir>/users/<key>.json (own file only)
                        └─ writes it  (≤1×/person/day; only its own user's file)

admin page →  GET /api/admin/users
                 ├─ users.registry.list_all()      → name, username, seen dates
                 ├─ ledger.breakdown(month,"user") → this month's spend per username
                 └─ settings.{user_limits,exempt_users,hidden_users}
              joined under U0 into ONE merged payload, hidden flagged per row;
              the panel never joins two endpoints itself

limit edit →  PUT /api/admin/settings  (existing route, existing validation)
hide       →  PUT /api/admin/settings  (hidden_users — same route, same validation)
```

---

## Error handling

| Failure | Behaviour |
|---|---|
| Share unreachable | `unreachable: true`; panel says so; **dropdowns fall back to typed boxes** (U12) |
| One person's file torn or non-object JSON | That row is skipped; the count of skipped files is displayed |
| Roster read fails during `display_name()` | Falls through to the local name at once; no exception, no wait (U6) |
| Roster write fails during touch | Caught, stderr, dropped. `/api/me` unaffected (U4) |
| Roster write fails during a name save | Local machine file still written; endpoint still 200 (U6) |
| Hide fails | It is a `settings.json` write and **raises** like every other settings write → the admin sees the error (U7) |
| Two stored keys fold to one person | Exact match wins; warning rendered on that row (U0) |
| A limit/hidden key matches nobody under U0 | Ignored: left in place, not shown (U14) |
| Windows name reads blank on a touch | Existing name kept (U5) |

---

## Gates

**G-U0 — The UI shape is approved from a rendered mockup BEFORE any code.**
One HTML mockup at
`docs/superpowers/specs/assets/2026-08-25-user-roster-mockup/people-panel.html`
showing: the People table in its default sort with the per-row limit
dropdown in all three states and the hidden line beneath; the transfer
picker in its populated AND its "nobody else yet" state; and
`ProviderPanel` after its rows are cut. Two earlier versions were
rejected on sight (too many columns, badges and boxes; blue link text as
controls). Destin settles the calls listed above on that page. STATUS.md
records the Upload page being rejected on sight after a faithfully-built
spec, and no test, review or eval can catch a UI shape that implements a
misread requirement — this gate is the only thing that can.

**G-U1 — Nothing about answering questions changes.**
`uv run python -m eval.run_eval` against a same-day CONTROL on the
unmodified tree, same query set. `ingest/` is touched (the `_current_user`
unification), which triggers the CLAUDE.md eval rule; the change is only
which module supplies a username string to a job record, and the eval is
60 seconds, so it is run rather than argued about. Expect identical
numbers.

**G-U2 — A limit set from the People panel actually applies, across
Windows' own casing drift.**
Executed, not asserted, end to end: touch the roster as `DMOSS`, set a
limit for that row from the panel, then call `check_limit("dmoss")` and
confirm the cap is returned. Then the same for the admin seat: transfer
admin to `DMOSS` from the picker and confirm `is_admin(settings, "dmoss")`
is true. Both are the bug U0 exists to fix, and the second is the lockout
mode the first draft left in place.

**G-U3 — An unreachable share does not produce a confident wrong answer.**
With the users folder made unreadable, `GET /api/admin/users` reports
`unreachable`, the panel says the folder could not be read, and the admin
transfer control renders a typed box rather than an empty picker. Driven
against the real route, with a prober-shaped failure production can
actually produce — the books-panel lesson: an offline test that raises
from a monkeypatch proves nothing if production returns falsy instead.
And the mirror case: the folder readable with one file in it renders the
"nobody else has opened the app yet" picker, not the typed box and not a
blank select.

---

## Testing

**pytest**
- Registry: round-trip, day-bucketing (a second touch the same day writes
  nothing — verified by mtime), name precedence (U5), a blank Windows read
  does not erase a name (U5), blank save clears the typed name (U5),
  local-name migration (U6).
- U0: `same_person` and `roster_key` agree; `roster_key("DMOSS") ==
  roster_key("dmoss")` including for a name needing sanitisation; a
  source-level guard that no module outside `users/whoami.py` calls
  `.casefold()`/`.lower()` on a username or calls `getpass.getuser()`, so
  neither the fold nor the resolver can grow a second copy
  (`tests/test_packaging_manifest.py`'s `git ls-files` precedent — new
  files must be staged).
- `display_name()`: the roster read raising, timing out, or returning a
  torn file falls through to the local name with no exception; a second
  call with an unchanged file does not re-open it (the mtime cache).
- Degradation: missing folder, unreadable folder (`os.listdir`, chmod-000,
  the `Path.glob` dead-code trap), one torn file among good ones,
  non-object JSON (`null`, `[]`, `5` — the `raw.get` AttributeError trap
  that once 500'd the history rail).
- `limit_for` and `is_admin`: exact wins over folded; folded resolves;
  both-keys-present reports the collision.
- `hidden_users` round-trips through `PUT /api/admin/settings` and its
  validation rejects a blank entry like the other two lists.
- A hidden person's own touch leaves them hidden (structural now — the
  touch cannot reach `settings.json` — but pinned so the structure cannot
  be undone by a later "convenience").
- A `DMOSS` limit with a `dmoss` roster row renders on that person's row
  (U0); a key with no fold-match renders NOWHERE and is left in
  `settings.json` byte-for-byte (U14).
- `/api/me` responds correctly with the roster write failing AND with the
  roster read failing.

**vitest**
- Sorting: every column, both directions, `aria-sort` correct, the no-name
  ordering pinned (U13).
- The limit control writes the right one of the two settings fields and
  clears the other (U8).
- `unreachable` renders the message and the typed fallback, not an empty
  picker (U12); a reachable roster with nobody else renders the
  "nobody else yet" sentence (U10).
- Hidden people are absent from the transfer picker; the current admin is
  absent from it under U0.
- The hidden line shows the count and expands in place; no row in the
  main table is hidden; no control on the panel is a bare link (a spec
  asserts no `adm-link` class renders in `PeoplePanel`).
- A guard that the panel is mounted — deleting the `<PeoplePanel/>` line
  must turn a spec red. This has been a real defect twice on this project
  (`ReportLinksPanel`, the citation annotation), and `Admin.test.tsx` has
  previously made 69 failing fetches that guaranteed a panel was invisible
  in every spec, so the mount guard must be verified failing by mutation.

**Mutation-verify before claiming any of this works.** In place, then
`git checkout` — a scratch-copy mutation silently passes.

---

## Risks and known limits

1. **Real names go onto the shared drive**, auto-filled from Windows. This
   reverses M6's posture for names specifically (though not its mechanism —
   the roster is its own file and never touches `settings.json` or the API
   key). It is an internal office tool that already records who spent what,
   so the exposure is small, but it is a change of stance and **belongs in
   the administrator handbook** — which does not exist yet (Plan 5
   Track 5), so it goes on that handbook's list, and in the meantime in
   this spec and STATUS.md.
2. **The roster only knows people who have opened the app.** A new hire has
   no row until day one, which is what makes U11 a door closing and U10's
   "nobody else yet" state a real state.
3. **`getpass.getuser()` reads `USERNAME`**, which a user can set. This is
   an accounting record, not authentication (S11), and nothing changes that.
4. **The by-person spend tab now duplicates the People table** (U16).
5. **A shared or service account will get a row.** That is what hiding is
   for; there is no way to tell a person from a service account
   automatically, and guessing would hide a real analyst.
6. **~20 files in one folder on an SMB share, listed on every admin page
   load.** Same order as `ingest/jobs.py::load_active` (14 files per poll)
   after Plan C, which was measured at 0.008 MB. The per-user read on
   `/api/me` is one file, cached (U6). No listing cache is specified; if
   it ever matters, the same `(mtime, size)` stamp is the shape to copy.
7. **Legacy `user_limits` written by hand may hold two casings of one
   person, or a username nobody has.** U0 keeps the exact match and warns
   on the collision; a key matching nobody is silently inert (U14).
   Nothing is merged or removed for the admin.
