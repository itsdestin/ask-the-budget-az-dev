# Central user roster — design

**Date:** 2026-08-25
**Status:** approved by Destin (design), spec pending review
**Decisions:** U1–U16 · **Gates:** G-U1, G-U2, G-U3

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

**Matching is exact and case-sensitive by deliberate choice**
(`harness/settings.py::limit_for`). `dmoss` and `DMOSS` are two different
people. The comment there justifies it on the grounds that folding would
silently merge two rows *an admin typed* — sound reasoning while rows are
typed, and the reason U9 below can reverse it once they are not.

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

**Three separate implementations answer "who is this?"**
`app/identity.py::current_user` honours the `JLBC_USER` override;
`ingest/jobs.py:667`, `ingest/claim.py:366` and `ingest/lock.py:408` each
carry a private `_current_user()` that does not. Nobody sees this today,
and it means an uploaded document can be stamped with a different name
than the same person's AI usage.

---

## Scope

**In:** a shared user roster, automatic registration, central names, an
admin People panel (sortable, with spend and limit editing), dropdowns
replacing every typed username, one canonical username resolver.

**Out:** authentication of any kind. This roster is an accounting and
convenience record, exactly as S11 says of the ledger. The admin gate
stays SOFT and nothing may be moved behind it that would be harmful if
bypassed. Also out: a non-admin roster surface (U15), deleting the
by-person spend tab (U16), any change to how conversations or transcripts
are stored.

---

## Decisions

### U1 — The roster is one small file per person

`<data_dir>/users/<key>.json`. **Not** one shared list.

A single shared list would mean ~20 machines rewriting one file, which is
precisely the risk that kept names off the share in the first place (M6).
One file per person makes collision structurally impossible: **a machine
only ever writes its own user's file.** Two existing precedents in this
repo take the same shape for the same reason — `ingest/jobs.py` (one JSON
per job) and `app/issue_reports.py` (one JSON per report), both of which
state in their own docstrings that a folder of small JSON files is chosen
so a colleague with no code access can read it in Notepad.

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
  "last_seen":  "2026-08-25T09:14:03-07:00",
  "hidden": false,
  "hidden_at": "",
  "hidden_by": ""
}
```

`version: 1` is stamped for the reason the chat transcripts stamp it: a
file with no stamp reads back as 0, so "written before versioning" and
"written today" stay distinguishable, and that cannot be added
retroactively.

### U2 — The filename is a sanitised key; the file holds the observed username

Windows SAM names disallow `" / \ [ ] : ; | = , + * ? < >`, but a
domain-qualified name can carry a backslash, and Windows filenames are
case-insensitive while Linux (dev, CI) filenames are not. Deriving the
filename from the username directly would therefore fold cases on one
platform and not the other.

The key is `username.strip().casefold()` with every character outside
`[a-z0-9._-]` replaced by `-`, truncated to 64 characters, with an
8-character hash of the original appended when sanitisation changed
anything. The **exact observed username** is stored inside the file and is
the only string ever compared or displayed. Case folding is thus a
deliberate, cross-platform-identical decision (U9), not an accident of the
filesystem.

### U3 — Registration happens on `GET /api/me`, at most once per person per day

`webapp/src/components/Header.tsx:45` calls `/api/me` on every page load on
every route, to decide whether the Admin pill renders. That is already the
one request every user makes, so it is where a person gets written down.

`last_seen` is bucketed to the **calendar day** (Arizona-local, matching
`harness/ledger.py`'s fixed UTC-7 shard rule). A write happens only when
the day changed, the Windows name changed, or the person is new. Twenty
people is therefore ~20 tiny writes per day office-wide, not one per page
load.

### U4 — Registration is background, never blocking, never raising

The touch runs in a Starlette `BackgroundTask` on the `/api/me` response,
so a slow or unreachable share cannot delay the request that decides
whether the nav renders. Every failure is caught, printed to stderr with
the real error, and dropped. **`/api/me` must behave identically whether
or not the roster write succeeds.**

This is the opposite posture to `harness/ledger.py::record_usage`, which
raises — and deliberately so. A missing ledger row means money was spent
and not recorded, which the caller must know. A missing roster touch means
a `last_seen` date is a day stale.

### U5 — A name auto-fills from Windows and is never overwritten once typed

Resolution order for what the roster records:

1. A name the person typed on their Settings page → `name_source: "typed"`.
   **Never** overwritten by a later Windows read.
2. Otherwise, `GetUserNameEx(NameDisplay)` — the AD full name the app
   already reads for memo signatures (`app/identity.py::_windows_display_name`)
   → `name_source: "windows"`, refreshed on each touch.
3. Otherwise, no name. The row shows the username alone.

On a domain-joined office the roster therefore arrives populated with real
names with nobody typing anything.

### U6 — `display_name()` gains the roster as its top source; the local file becomes a fallback

New order: **roster typed name > local typed name > Windows > username.**

This preserves M5's reversal (a typed override must beat auto-detection,
because a *wrong* AD name is likelier than a missing one) and preserves
M6's reason for the local file — it is still what answers when the share
is unreachable.

`PUT /api/me/display-name` writes the roster **and** the local machine
file. Writing both is not redundancy: the local copy is the offline
fallback, and keeping them in step means a share outage does not silently
change what a memo says. If the roster write fails, the local write still
succeeds and the endpoint still returns 200 — the analyst's memo is
correct on the machine they are sitting at, which is the thing they asked
for.

**On first touch, an existing local name is migrated up** to the roster as
`name_source: "typed"` if the roster has no typed name. Nobody re-types
what they already entered.

### U7 — Hidden, never deleted

`hidden: true` removes a person from every dropdown and moves their row
into a collapsed "No longer here" list. Their ledger rows are untouched and
still count in office totals — **deleting a person would make last year's
spend stop adding up**, and the ledger is the accounting record.

If a hidden person opens the app again, `last_seen` updates and the row
is surfaced with a note that they have been seen since being hidden. The
`hidden` flag is not cleared automatically; that is the admin's call.

**No inactivity auto-hide.** An analyst on leave or secondment would
silently lose their limit row, and a limit that quietly stops applying is
the exact class of failure this whole change exists to remove.

### U8 — Spend limits stay in `settings.json`; the roster supplies the keys

`user_limits` and `exempt_users` are not moved. They are admin-only
configuration, already validated in `app/routes/admin.py::_validate`, and
moving them buys nothing while costing a migration.

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

### U9 — Username matching becomes case-insensitive, with a visible guard

`Settings.limit_for` currently exact-matches, and its comment rejects
folding because folding would silently merge two rows *an admin typed*.
Once every row comes from a dropdown keyed on the roster, the UI cannot
create two rows for one person, so that reasoning no longer holds and the
existing silent no-op (`DMOSS` vs `dmoss`) becomes the larger cost.

`limit_for` resolves **exact match first, then a case-insensitive match**
over its own dict. Self-contained in `harness/settings.py` — no new import,
no Invariant 7 change.

**The guard is not optional:** if two keys fold to one person, the exact
match wins and the People panel renders a warning on that row naming both
keys. Silently picking one is what the original comment was right to
refuse; saying so on screen is the honest version.

### U10 — Every typed username box becomes a dropdown

- Admin transfer (`AdvancedPanel.tsx`) → a picker of non-hidden people.
- Per-person limits (`ProviderPanel.tsx`) → deleted; replaced by the People
  panel's per-row control. The **office-wide default stays where it is** —
  it is not about an individual.
- Exempt list (`ProviderPanel.tsx`) → deleted; folded into the same control.

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

### U13 — The People table sorts on every column, both directions

Click a heading to sort; click again to reverse. An arrow in the heading
states which column and which direction, and `aria-sort` carries the same
fact to a screen reader.

| Column | First click | Second click |
|---|---|---|
| Name | A→Z | Z→A |
| Username | A→Z | Z→A |
| Last seen | most recent first | longest-absent first |
| Spent this month | highest first | lowest first |
| Limit | no limit → highest → lowest → office default | reversed |

Default is **highest spend first**, matching today's table, because that is
the question the page is usually opened to answer.

One ordering must be explicit rather than emergent: a person with **no
recorded name** sorts LAST in a name sort **in both directions**, rather
than to the top under an empty string. Reversing a sort must not promote
the least informative rows to the top of the page.

Every row in this table has been seen — a roster file only exists because
somebody opened the app — so there is no "never seen" case here. Limits
typed for a username nobody has matched are a different thing and live in
their own section (U14).

The same sortable table renders the "No longer here" list (U7) and the
orphan-limits list (U14), so the three cannot drift apart.

### U14 — Orphan limits are surfaced, not deleted

Any key in `user_limits` or `exempt_users` that matches no roster person
appears in a "Limits set for someone the app has never seen" section, per
row, flagged. **This is the first time the app would ever report the
existing silent bug**, and it is expected to find something in the live
config.

Nothing is auto-removed. When that person first opens the app the row
merges into the main table on its own.

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

## Components

| Module | Responsibility | Depends on |
|---|---|---|
| `users/whoami.py` (new) | The ONE answer to "who is this process running as". `JLBC_USER` override > `getpass.getuser()` > `""`. Plus `roster_key()` (U2). | nothing but stdlib |
| `users/registry.py` (new) | Read / list / touch / hide the roster. Degrades on read, raises on write. | `store.config`, `users.whoami` |
| `app/identity.py` | Re-exports `current_user` from `users.whoami` so no existing caller changes. `display_name()` gains the roster source (U6). | + `users.registry` |
| `ingest/{jobs,claim,lock}.py` | Their three private `_current_user()` copies are replaced by `users.whoami.current_user`. | + `users.whoami` |
| `app/routes/admin.py` | `GET /api/admin/users`, `POST /api/admin/users/{key}/hide`, `POST /.../unhide`. `/api/me` gains the background touch. `PUT /api/me/display-name` writes both stores. | + `users.registry` |
| `harness/settings.py` | `limit_for` gains the case-insensitive fallback (U9). No new import. | unchanged |
| `webapp/src/admin/PeoplePanel.tsx` (new) | The table, the sort, the per-row limit control, hide/unhide, the orphan section. | `api.ts` |
| `webapp/src/components/SortableTable.tsx` (new) | Sort behaviour + `aria-sort`, extracted so the hidden list and the main list cannot drift. | — |
| `webapp/src/admin/{AdvancedPanel,ProviderPanel}.tsx` | Typed boxes → picker; per-person limit rows deleted. | `api.ts` |

**`users/` is a new top-level package**, matching `funds/`, `citation/`,
`memo/`. `users/whoami.py` is a leaf with no first-party imports so that
`ingest/` can use it without importing `app/` (the dependency runs
`app → ingest`, and reversing it would be circular).

**Invariant 7 is unaffected.** Nothing under `harness/` imports `users` —
`limit_for`'s fold is self-contained — so no allowlist changes. If a later
change needs it, `users/registry.py` writes files and must NOT be admitted
wholesale; admit a read-only module the way `funds/names.py` was.

---

## Data flow

```
page load  →  GET /api/me
                 ├─ responds immediately (unchanged shape + roster name)
                 └─ BackgroundTask: users.registry.touch(username, windows_name)
                        └─ writes <data_dir>/users/<key>.json  (≤1×/person/day)

admin page →  GET /api/admin/users
                 ├─ users.registry.list_all()      → name, username, seen dates, hidden
                 ├─ ledger.breakdown(month,"user") → this month's spend per username
                 └─ settings.user_limits/exempt    → each person's cap + orphan keys
              one merged payload; the panel never joins two endpoints itself

limit edit →  PUT /api/admin/settings  (existing route, existing validation)
hide       →  POST /api/admin/users/{key}/hide   → rewrites that one file
```

---

## Error handling

| Failure | Behaviour |
|---|---|
| Share unreachable | `unreachable: true`; panel says so; **dropdowns fall back to typed boxes** (U12) |
| One person's file torn | That row is skipped; the count of skipped files is displayed |
| Roster write fails during touch | Caught, stderr, dropped. `/api/me` unaffected (U4) |
| Roster write fails during a name save | Local machine file still written; endpoint still 200 (U6) |
| Roster write fails during hide | **Raises** → the admin sees the error. A silent no-op hide would leave a departed colleague in every dropdown while the screen says otherwise |
| Two keys fold to one person | Exact match wins; warning rendered on that row (U9) |
| A limit key matches nobody | Listed under orphan limits (U14) |

---

## Gates

**G-U1 — Nothing about answering questions changes.**
`uv run python -m eval.run_eval` against a same-day CONTROL on the
unmodified tree, same query set. `ingest/` is touched (the `_current_user`
unification), which triggers the CLAUDE.md eval rule; the change is only
which module supplies a username string to a job record, and the eval is
60 seconds, so it is run rather than argued about. Expect identical
numbers.

**G-U2 — A limit set from the People panel actually applies.**
Executed, not asserted: set a limit for a real roster person, then call
`check_limit` for that username and confirm the cap is returned — and
confirm it still returns for a differently-cased spelling of the same
username, which is the bug U9 exists to fix.

**G-U3 — An unreachable share does not produce a confident wrong answer.**
With the users folder made unreadable, `GET /api/admin/users` reports
`unreachable`, the panel says the folder could not be read, and the admin
transfer control renders a typed box rather than an empty picker. Driven
against the real route, with a prober-shaped failure production can
actually produce — the books-panel lesson: an offline test that raises
from a monkeypatch proves nothing if production returns falsy instead.

---

## Testing

**pytest**
- Registry: round-trip, day-bucketing (a second touch the same day writes
  nothing — verified by mtime), name precedence (U5), local-name migration
  (U6), hide/unhide, seen-since-hidden.
- Key derivation (U2): case folding is identical on POSIX and simulated
  Windows input; a name needing sanitisation still round-trips its exact
  username.
- Degradation: missing folder, unreadable folder (`os.listdir`, chmod-000,
  the `Path.glob` dead-code trap), one torn file among good ones,
  non-object JSON (`null`, `[]`, `5` — the `raw.get` AttributeError trap
  that once 500'd the history rail).
- `limit_for`: exact wins over folded; folded resolves; both-keys-present
  reports the collision.
- Orphan detection over a settings fixture with a key nobody matches.
- `/api/me` responds correctly with the roster write failing.
- One resolver: a source-level guard that no module outside
  `users/whoami.py` calls `getpass.getuser()`, so the three copies cannot
  grow back. (`tests/test_every_first_party_import_resolves` precedent —
  `git ls-files`, so new files must be staged.)

**vitest**
- Sorting: every column, both directions, `aria-sort` correct, no-name and
  never-seen orderings pinned (U13).
- The limit control writes the right one of the two settings fields and
  clears the other (U8).
- `unreachable` renders the message and the typed fallback, not an empty
  picker (U12).
- Hidden people are absent from the transfer picker.
- The orphan section renders and is absent when there are no orphans.
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
   the administrator handbook**, not just in the code.
2. **The roster only knows people who have opened the app.** A new hire has
   no row until day one, which is what makes U11 a door closing.
3. **`getpass.getuser()` reads `USERNAME`**, which a user can set. This is
   an accounting record, not authentication (S11), and nothing changes that.
4. **The by-person spend tab now duplicates the People table** (U16).
5. **A shared or service account will get a row.** That is what hiding is
   for; there is no way to tell a person from a service account
   automatically, and guessing would hide a real analyst.
6. **~20 files in one folder on an SMB share, read on every admin page
   load.** Same order as `ingest/jobs.py::load_active` (14 files per poll)
   after Plan C, which was measured at 0.008 MB. No caching is specified;
   if it ever matters, the mtime-stamp cache from
   `store/office_agencies.py` is the shape to copy.
